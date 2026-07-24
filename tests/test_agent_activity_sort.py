from datetime import datetime, timezone

import pytest

from raganything.services import pg_agent_repo


class _FakePool:
    def __init__(self, rows, failures=0):
        self.rows = rows
        self.failures = failures
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("activity aggregation unavailable")
        return self.rows


def _agent_row(**overrides):
    row = {
        "id": "agent-1",
        "name": "Agent One",
        "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
        "conversation_count": 0,
        "last_conversation_at": None,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_list_agents_uses_current_users_conversations_for_activity(monkeypatch):
    pool = _FakePool([
        _agent_row(
            conversation_count=1,
            last_conversation_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        )
    ])
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)
    monkeypatch.setattr(pg_agent_repo, "_json_list_agents", lambda **_kwargs: [])

    agents = await pg_agent_repo.pg_list_agents(user_id=42, is_admin=False)

    query, args = pool.calls[0]
    assert "owner_id = $1" in query
    assert args == (42,)
    assert agents[0]["conversation_count"] == 1
    assert agents[0]["last_conversation_at"] == "2026-07-03T00:00:00+00:00"


@pytest.mark.asyncio
async def test_list_agents_uses_all_conversations_for_admin_activity(monkeypatch):
    pool = _FakePool([
        _agent_row(
            conversation_count=3,
            last_conversation_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
        )
    ])
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)
    monkeypatch.setattr(pg_agent_repo, "_json_list_agents", lambda **_kwargs: [])

    agents = await pg_agent_repo.pg_list_agents(user_id=1, is_admin=True)

    query, args = pool.calls[0]
    assert "WHERE agent_id = a.id\n" in query
    assert "owner_id = $1" not in query
    assert args == ()
    assert agents[0]["conversation_count"] == 3
    assert agents[0]["last_conversation_at"] == "2026-07-04T00:00:00+00:00"


@pytest.mark.asyncio
async def test_list_agents_ignores_legacy_json_after_postgres_migration(monkeypatch):
    pool = _FakePool([_agent_row()])
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)
    monkeypatch.setattr(
        pg_agent_repo,
        "_json_list_agents",
        lambda **_kwargs: [{"id": "legacy-agent", "name": "Legacy", "updated_at": "2026-06-01T00:00:00+00:00"}],
    )

    agents = await pg_agent_repo.pg_list_agents(user_id=42, is_admin=False)
    by_id = {agent["id"]: agent for agent in agents}

    assert by_id["agent-1"]["conversation_count"] == 0
    assert by_id["agent-1"]["last_conversation_at"] is None
    assert "legacy-agent" not in by_id


@pytest.mark.asyncio
async def test_list_agents_keeps_pg_agents_when_activity_aggregation_fails(monkeypatch):
    pool = _FakePool([_agent_row()], failures=1)
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)
    monkeypatch.setattr(pg_agent_repo, "_json_list_agents", lambda **_kwargs: [])

    agents = await pg_agent_repo.pg_list_agents(user_id=42, is_admin=False)

    assert len(pool.calls) == 2
    assert "LEFT JOIN LATERAL" in pool.calls[0][0]
    assert "SELECT * FROM agents" in pool.calls[1][0]
    assert agents[0]["conversation_count"] is None
    assert agents[0]["last_conversation_at"] is None
