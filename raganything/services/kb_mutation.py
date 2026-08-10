"""Durable KB mutation leases shared by ingestion and visual reindexing."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from raganything.services.pg_state_repo import get_pg_pool

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")
KB_MUTATION_LEASE_TTL_SECONDS = 300
KB_MUTATION_HEARTBEAT_INTERVAL_SECONDS = 15
KB_MUTATION_DB_GRACE_SECONDS = 180
# Heartbeats tolerate a temporarily unreachable PostgreSQL by counting
# consecutive failures (12 x 15s ~= 3 minutes) instead of cancelling on the
# first connection error. A reachable-but-lost lease (UPDATE 0) still
# cancels immediately.
_MUTATION_HEARTBEAT_MAX_CONSECUTIVE_FAILURES = (
    KB_MUTATION_DB_GRACE_SECONDS // KB_MUTATION_HEARTBEAT_INTERVAL_SECONDS
)
if (
    KB_MUTATION_DB_GRACE_SECONDS + KB_MUTATION_HEARTBEAT_INTERVAL_SECONDS
    >= KB_MUTATION_LEASE_TTL_SECONDS
):
    raise RuntimeError("KB mutation lease TTL must exceed DB grace plus heartbeat interval")


async def acquire_kb_mutation_lease(
    kb: str,
    task_id: str,
    owner: str,
    *,
    mutation_kind: str,
    ttl_seconds: int = KB_MUTATION_LEASE_TTL_SECONDS,
) -> str:
    """Acquire a durable mutation lease or fail if visual reindexing is active."""
    lease_id = str(uuid.uuid4())
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", f"kb-mutation:{kb}"
            )
            await conn.execute(
                "DELETE FROM kb_mutation_leases WHERE kb=$1 AND expires_at <= NOW()",
                kb,
            )
            reindexing = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM vision_reindex_jobs WHERE kb=$1 "
                "AND state IN ('queued','running'))",
                kb,
            )
            if reindexing:
                raise RuntimeError("reindex_in_progress")
            await conn.execute(
                "INSERT INTO kb_mutation_leases(id,kb,task_id,lease_owner,mutation_kind,expires_at) "
                "VALUES($1::uuid,$2,$3,$4,$5,NOW()+$6 * INTERVAL '1 second')",
                lease_id,
                kb,
                task_id,
                owner,
                mutation_kind,
                ttl_seconds,
            )
    return lease_id


async def heartbeat_kb_mutation_lease(
    lease_id: str,
    owner: str,
    *,
    ttl_seconds: int = KB_MUTATION_LEASE_TTL_SECONDS,
) -> bool:
    result = await get_pg_pool().execute(
        "UPDATE kb_mutation_leases SET heartbeat_at=NOW(),"
        "expires_at=NOW()+$3 * INTERVAL '1 second' "
        "WHERE id=$1::uuid AND lease_owner=$2 AND expires_at > NOW()",
        lease_id,
        owner,
        ttl_seconds,
    )
    return result == "UPDATE 1"


async def release_kb_mutation_lease(lease_id: str, owner: str) -> None:
    await get_pg_pool().execute(
        "DELETE FROM kb_mutation_leases WHERE id=$1::uuid AND lease_owner=$2",
        lease_id,
        owner,
    )


async def run_kb_mutation_with_lease(
    kb: str,
    task_id: str,
    operation: Callable[[], Awaitable[_Result]],
    *,
    mutation_kind: str,
) -> _Result:
    """Run one KB mutation and cancel it if the durable lease is lost."""
    owner = f"kb-mutation:{os.getpid()}:{uuid.uuid4()}"
    try:
        lease_id = await acquire_kb_mutation_lease(
            kb, task_id, owner, mutation_kind=mutation_kind
        )
    except RuntimeError as exc:
        pg_unavailable = "PG pool not initialized" in str(exc)
        is_production = os.getenv("RAGANYTHING_ENV", "development").strip().lower() == "production"
        if is_production or not pg_unavailable:
            raise
        return await operation()
    operation_task = asyncio.create_task(operation(), name=f"kb-mutation-{task_id}")
    lease_lost = asyncio.Event()
    heartbeat_error: BaseException | None = None

    async def heartbeat() -> None:
        nonlocal heartbeat_error
        consecutive_failures = 0
        try:
            while True:
                await asyncio.sleep(KB_MUTATION_HEARTBEAT_INTERVAL_SECONDS)
                try:
                    alive = await heartbeat_kb_mutation_lease(lease_id, owner)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    from raganything.services.pg_state_repo import is_transient_pg_connection_error
                    if not is_transient_pg_connection_error(exc):
                        heartbeat_error = exc
                        operation_task.cancel()
                        return
                    consecutive_failures += 1
                    if consecutive_failures >= _MUTATION_HEARTBEAT_MAX_CONSECUTIVE_FAILURES:
                        lease_lost.set()
                        operation_task.cancel()
                        return
                    continue
                if not alive:
                    lease_lost.set()
                    operation_task.cancel()
                    return
                consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            heartbeat_error = exc
            lease_lost.set()
            operation_task.cancel()
            logger.warning("KB mutation heartbeat failed for task=%s", task_id, exc_info=True)

    heartbeat_task = asyncio.create_task(heartbeat(), name=f"kb-mutation-heartbeat-{task_id}")
    try:
        try:
            return await operation_task
        except asyncio.CancelledError as exc:
            if heartbeat_error is not None:
                raise heartbeat_error
            if lease_lost.is_set():
                raise RuntimeError("kb_mutation_lease_lost") from exc
            raise
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        try:
            await release_kb_mutation_lease(lease_id, owner)
        except Exception:
            logger.warning("KB mutation lease release failed for task=%s", task_id, exc_info=True)
