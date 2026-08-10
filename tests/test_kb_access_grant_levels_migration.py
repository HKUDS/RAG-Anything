import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_access_grant_level_migration_is_manifested_and_backfills_role_capabilities():
    sql = (ROOT / "migrations" / "033_kb_access_grant_levels.sql").read_text(encoding="utf-8")
    normalized = " ".join(sql.split()).upper()
    manifest = json.loads((ROOT / "migrations" / "migration_manifest.json").read_text(encoding="utf-8"))

    assert manifest["migrations"][-2] == {
        "sequence": 36,
        "id": "033_kb_access_grant_levels.sql",
    }
    assert "ADD COLUMN IF NOT EXISTS ACCESS_LEVEL TEXT NOT NULL DEFAULT 'READ'" in normalized
    assert "ROLES.PERMISSIONS ? 'KB:WRITE'" in normalized
    assert "THEN 'OPERATE' ELSE 'READ'" in normalized
    assert "CHECK (ACCESS_LEVEL IN ('READ', 'OPERATE'))" in normalized


def test_kb_manage_permission_migration_is_manifested_and_idempotent():
    sql = (ROOT / "migrations" / "034_kb_manage_permission.sql").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "migrations" / "migration_manifest.json").read_text(encoding="utf-8"))

    assert manifest["migrations"][-1] == {
        "sequence": 37,
        "id": "034_kb_manage_permission.sql",
    }
    assert "WHEN permissions ? 'kb:manage' THEN permissions" in sql
    assert "'super_admin', 'dept_admin', 'teacher'" in sql


@pytest.mark.asyncio
async def test_access_grant_level_migration_backfills_and_repeats_on_postgres():
    database_url = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set MIGRATION_TEST_DATABASE_URL for isolated PostgreSQL migration testing")
    asyncpg = pytest.importorskip("asyncpg")
    schema = f"kb_grant_levels_{os.urandom(8).hex()}"
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
    except asyncpg.InsufficientPrivilegeError:
        await connection.close()
        pytest.skip("MIGRATION_TEST_DATABASE_URL role cannot create an isolated schema")
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        await connection.execute("CREATE TABLE roles (id INTEGER PRIMARY KEY, permissions JSONB NOT NULL)")
        await connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, role_id INTEGER NOT NULL)")
        await connection.execute("CREATE TABLE kb_metadata (name TEXT PRIMARY KEY)")
        await connection.execute(
            "CREATE TABLE kb_access_grants (kb_name TEXT NOT NULL REFERENCES kb_metadata(name), "
            "user_id INTEGER NOT NULL, granted_by INTEGER NOT NULL, granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "PRIMARY KEY(kb_name, user_id))"
        )
        await connection.execute(
            "INSERT INTO roles VALUES (1, '[\"kb:write\"]'), (2, '[]'); "
            "INSERT INTO users VALUES (11, 1), (12, 2); "
            "INSERT INTO kb_metadata VALUES ('team-kb'); "
            "INSERT INTO kb_access_grants(kb_name, user_id, granted_by) VALUES ('team-kb', 11, 1), ('team-kb', 12, 1)"
        )
        migration_sql = (ROOT / "migrations" / "033_kb_access_grant_levels.sql").read_text(encoding="utf-8")
        await connection.execute(migration_sql)
        await connection.execute(migration_sql)
        rows = await connection.fetch("SELECT user_id, access_level FROM kb_access_grants ORDER BY user_id")
        assert [(row["user_id"], row["access_level"]) for row in rows] == [(11, "operate"), (12, "read")]
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
