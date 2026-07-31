"""Durable quota-lease behavior without depending on a live PostgreSQL server."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

import pytest

from raganything.services import user_settings


class _Transaction(AbstractAsyncContextManager):
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self):
        self.leases: list[dict[str, object]] = []
        self.advisory_locks: list[str] = []
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self):
        return _Transaction()

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "pg_advisory_xact_lock" in query:
            self.advisory_locks.append(args[0])
            return "SELECT 1"
        if query.startswith("DELETE FROM user_quota_leases WHERE expires_at"):
            self.leases[:] = [lease for lease in self.leases if not lease.get("expired")]
            return "DELETE 0"
        if query.startswith("INSERT INTO user_quota_leases"):
            self.leases.append({
                "id": args[0], "user_id": args[1], "task_id": args[2],
                "owner": args[3], "expired": False,
            })
            return "INSERT 0 1"
        if query.startswith("UPDATE user_quota_leases"):
            for lease in self.leases:
                if lease["id"] == args[0] and lease["owner"] == args[1]:
                    lease["heartbeats"] = int(lease.get("heartbeats", 0)) + 1
                    lease["expired"] = False
                    return "UPDATE 1"
            return "UPDATE 0"
        if query.startswith("DELETE FROM user_quota_leases WHERE id"):
            before = len(self.leases)
            self.leases[:] = [
                lease for lease in self.leases
                if not (lease["id"] == args[0] and lease["owner"] == args[1])
            ]
            return f"DELETE {before - len(self.leases)}"
        raise AssertionError(f"Unexpected SQL: {query}")

    async def fetch(self, query, *args):
        active = [lease for lease in self.leases if not lease["expired"]]
        if "WHERE user_id=$1" in query:
            active = [lease for lease in active if lease["user_id"] == args[0]]
        return [{"id": lease["id"]} for lease in active]


class _Acquire(AbstractAsyncContextManager):
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self):
        self.conn = _Connection()

    def acquire(self):
        return _Acquire(self.conn)


@pytest.fixture
def quota_pool(monkeypatch):
    pool = _Pool()
    monkeypatch.setattr(user_settings, "get_pg_pool", lambda: pool)
    return pool


@pytest.mark.asyncio
async def test_global_provider_worker_cap_is_enforced_across_users(quota_pool):
    first = await user_settings.acquire_quota_lease(1, "task-a", "worker-a", 4, outer_limit=2)
    second = await user_settings.acquire_quota_lease(2, "task-b", "worker-b", 4, outer_limit=2)
    denied = await user_settings.acquire_quota_lease(3, "task-c", "worker-c", 4, outer_limit=2)

    assert first and second
    assert denied is None
    # The count-and-insert operation locks both scopes before inspecting rows.
    assert quota_pool.conn.advisory_locks[:2] == ["quota:global", "quota:user:1"]

    await user_settings.release_quota_lease(first, "worker-a")
    assert await user_settings.acquire_quota_lease(3, "task-c", "worker-c", 4, outer_limit=2)


@pytest.mark.asyncio
async def test_lease_heartbeat_owner_check_and_delayed_owner_renewal(quota_pool):
    first = await user_settings.acquire_quota_lease(7, "task-a", "owner-a", 1)
    assert first
    assert not await user_settings.heartbeat_quota_lease(first, "wrong-owner")
    assert await user_settings.heartbeat_quota_lease(first, "owner-a")

    quota_pool.conn.leases[0]["expired"] = True
    assert await user_settings.heartbeat_quota_lease(first, "owner-a")
    assert quota_pool.conn.leases[0]["expired"] is False


@pytest.mark.asyncio
async def test_reclaimed_quota_lease_remains_fenced_from_old_owner(quota_pool):
    first = await user_settings.acquire_quota_lease(7, "task-a", "owner-a", 1)
    assert first
    quota_pool.conn.leases[0]["expired"] = True
    replacement = await user_settings.acquire_quota_lease(7, "task-b", "owner-b", 1)

    assert replacement
    assert len(quota_pool.conn.leases) == 1
    assert quota_pool.conn.leases[0]["id"] == replacement
    assert not await user_settings.heartbeat_quota_lease(first, "owner-a")


@pytest.mark.asyncio
async def test_quota_lease_intervals_bind_numeric_ttls(quota_pool):
    lease_id = await user_settings.acquire_quota_lease(
        7, "task-a", "owner-a", 1, ttl_seconds=30
    )
    assert lease_id
    assert await user_settings.heartbeat_quota_lease(lease_id, "owner-a", ttl_seconds=45)

    interval_statements = [
        (query, args)
        for query, args in quota_pool.conn.executed
        if "INTERVAL '1 second'" in query
    ]
    assert len(interval_statements) == 2
    assert all("::text" not in query for query, _ in interval_statements)
    assert interval_statements[0][1][-1] == 30
    assert interval_statements[1][1][-1] == 45
