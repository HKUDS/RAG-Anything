import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "migrations" / "027_agent_conversation_summary_columns.sql"
PG_SETUP_PATH = ROOT / "scripts" / "pg_setup.py"


def test_summary_repair_migration_is_idempotent_and_preserves_data():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()

    assert "ADD COLUMN IF NOT EXISTS SUMMARY TEXT" in normalized
    assert "ADD COLUMN IF NOT EXISTS SUMMARY_UPDATED_AT TIMESTAMPTZ" in normalized
    assert "CREATE INDEX IF NOT EXISTS IDX_AGENT_CONVERSATIONS_SUMMARY" in normalized
    assert "ON AGENT_CONVERSATIONS (SUMMARY_UPDATED_AT)" in normalized
    assert "WHERE SUMMARY IS NOT NULL" in normalized
    assert normalized.count("IF NOT EXISTS") == 3


def test_pg_setup_runs_migrations_024_through_027_in_order():
    source = PG_SETUP_PATH.read_text(encoding="utf-8")
    migration_names = [
        "024_upload_task_cancellation.sql",
        "025_remove_user_email.sql",
        "026_kb_updated_at_semantics.sql",
        "027_agent_conversation_summary_columns.sql",
    ]
    positions = [source.index(f'"migrations" / "{name}"') for name in migration_names]

    assert positions == sorted(positions)


class _SummaryPool:
    def __init__(self):
        self.summary = None
        self.summary_updated_at = None
        self.calls = []

    async def fetchrow(self, query, thread_id):
        self.calls.append(("fetchrow", query, thread_id))
        if "summary_updated_at" in query:
            return {"summary_updated_at": self.summary_updated_at}
        return {"summary": self.summary}

    async def execute(self, query, summary, updated_at, thread_id):
        self.calls.append(("execute", query, summary, updated_at, thread_id))
        self.summary = summary
        self.summary_updated_at = updated_at
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_pg_summary_write_read_timestamp_round_trip(monkeypatch):
    from raganything.services import pg_agent_repo

    pool = _SummaryPool()
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)

    assert await pg_agent_repo.pg_get_summary("thread-1") is None
    assert await pg_agent_repo.pg_update_summary("thread-1", "compressed context")
    assert await pg_agent_repo.pg_get_summary("thread-1") == "compressed context"

    updated_at = await pg_agent_repo.pg_get_summary_updated_at("thread-1")
    assert isinstance(updated_at, datetime)
    assert updated_at.tzinfo == timezone.utc
    assert pool.summary_updated_at == updated_at


@pytest.mark.asyncio
async def test_summary_repair_migration_executes_twice_in_isolated_schema():
    database_url = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set MIGRATION_TEST_DATABASE_URL for isolated PostgreSQL migration testing")

    asyncpg = pytest.importorskip("asyncpg")
    schema = f"summary_migration_test_{os.urandom(8).hex()}"
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        await connection.execute(f'SET search_path TO "{schema}"')
        await connection.execute(
            "CREATE TABLE agent_conversations ("
            "id TEXT PRIMARY KEY, updated_at TIMESTAMPTZ"
            ")"
        )
        migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")

        await connection.execute(migration_sql)
        await connection.execute(migration_sql)

        columns = await connection.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'agent_conversations' "
            "AND column_name IN ('summary', 'summary_updated_at') "
            "ORDER BY column_name"
        )
        assert [row["column_name"] for row in columns] == ["summary", "summary_updated_at"]

        index = await connection.fetchrow(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'agent_conversations' "
            "AND indexname = 'idx_agent_conversations_summary'"
        )
        assert index is not None
        assert "summary_updated_at" in index["indexdef"]
        assert "summary IS NOT NULL" in index["indexdef"]
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
