import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "migrations" / "031_kb_card_update_time.sql"
MANIFEST_PATH = ROOT / "migrations" / "migration_manifest.json"


def test_kb_card_update_time_migration_is_manifested_and_conservative():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["migrations"][-1] == {
        "sequence": 34,
        "id": "031_kb_card_update_time.sql",
    }
    assert "DROP TRIGGER IF EXISTS TRG_KB_METADATA_UPDATED_AT ON KB_METADATA" in normalized
    assert "HAVING COUNT(*) > 1" in normalized
    assert "STATUS IN ('COMPLETED', 'DELETED')" in normalized
    assert "WHERE STATE = 'COMMITTED'" in normalized
    assert "META.UPDATED_AT > RECOVERY.INFERRED_UPDATED_AT" in normalized


@pytest.mark.asyncio
async def test_kb_card_update_time_migration_recovers_duplicate_groups_twice():
    database_url = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set MIGRATION_TEST_DATABASE_URL for isolated PostgreSQL migration testing")

    asyncpg = pytest.importorskip("asyncpg")
    schema = f"kb_card_update_time_{os.urandom(8).hex()}"
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
    except asyncpg.InsufficientPrivilegeError:
        await connection.close()
        pytest.skip("MIGRATION_TEST_DATABASE_URL role cannot create an isolated schema")

    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        await connection.execute(
            "CREATE TABLE kb_metadata (name TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL)"
        )
        await connection.execute(
            "CREATE TABLE uploaded_files (kb_name TEXT NOT NULL, status TEXT NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL)"
        )
        await connection.execute(
            "CREATE TABLE kb_corpus_mutations (kb TEXT NOT NULL, state TEXT NOT NULL, "
            "committed_at TIMESTAMPTZ)"
        )
        await connection.execute(
            "INSERT INTO kb_metadata(name, created_at, updated_at) VALUES "
            "('a', '2026-08-01T00:00:00Z', '2026-08-05T00:00:00Z'), "
            "('b', '2026-08-02T00:00:00Z', '2026-08-05T00:00:00Z'), "
            "('single', '2026-08-01T00:00:00Z', '2026-08-04T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO uploaded_files(kb_name, status, updated_at) VALUES "
            "('a', 'completed', '2026-08-03T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO kb_corpus_mutations(kb, state, committed_at) VALUES "
            "('b', 'committed', '2026-08-04T12:00:00Z')"
        )

        migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
        await connection.execute(migration_sql)
        await connection.execute(migration_sql)

        rows = await connection.fetch("SELECT name, updated_at FROM kb_metadata ORDER BY name")
        values = {row["name"]: row["updated_at"].isoformat() for row in rows}
        assert values == {
            "a": "2026-08-03T00:00:00+00:00",
            "b": "2026-08-04T12:00:00+00:00",
            "single": "2026-08-04T00:00:00+00:00",
        }
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
