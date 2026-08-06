import json
import pytest
from contextlib import asynccontextmanager

from raganything.embedding.identity import (
    canonical_text_embedding_identity,
    embedding_identity_from_settings,
    load_text_embedding_identity,
)
from raganything.services.user_settings import load_task_text_embedding_identity
from raganything.services.pg_embedding_identity import ensure_kb_embedding_identity


class _IdentityConnection:
    def __init__(self, *, tables=None, table_rows=None, registry_row=None,
                 existing_tables=None):
        # tables: requested vector table name -> actual table name or None
        self.tables = dict(tables or {})
        self.table_rows = dict(table_rows or {})
        self.registry_row = registry_row
        self.existing_tables = set(existing_tables or ())
        self.executed = []
        self.queries = []

    async def fetchrow(self, sql, *_args):
        self.queries.append(("fetchrow", sql, _args))
        if "information_schema.tables" in sql:
            actual = self.tables.get(_args[0])
            return None if actual is None else {"table_name": actual}
        if "kb_text_embedding_identities" in sql:
            return self.registry_row
        if "pg_catalog.pg_class" in sql:
            requested = str(_args[0]).lower()
            for physical in self.existing_tables:
                if physical.lower() == requested:
                    return {"relname": physical}
            return None
        raise AssertionError(f"unexpected query: {sql}")

    async def fetchval(self, sql, *_args):
        self.queries.append(("fetchval", sql, _args))
        if sql.startswith('SELECT COUNT(*) FROM "'):
            table = sql.split('"')[1]
            if table not in self.table_rows:
                raise AssertionError(f"COUNT on unexpected table: {table}")
            return self.table_rows[table]
        raise AssertionError(f"unexpected query: {sql}")

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        self.queries.append(("execute", sql, args))

    def transaction(self, *, readonly=False):
        return _IdentityTransaction()


class _IdentityPool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class _IdentityTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_identity_is_deterministic_and_secret_free():
    first = canonical_text_embedding_identity(
        provider="OpenAI-Compatible",
        model="text-embedding-v3",
        dimension=1024,
        endpoint_semantics="https://api.example.test/v1?api_key=should-not-be-used",
    )
    second = canonical_text_embedding_identity(
        provider="OpenAI-Compatible",
        model="text-embedding-v3",
        dimension=1024,
        endpoint_semantics="https://api.example.test/v1?api_key=should-not-be-used",
    )

    assert first == second
    assert len(first["table_suffix"]) <= 63
    assert "should-not-be-used" not in str(first)
    assert "api_key" not in str(first)
    assert first["model_name"] == first["table_suffix"]


def test_identity_hash_prevents_safe_name_collisions():
    dashed = canonical_text_embedding_identity(
        provider="provider", model="model-a", dimension=8, endpoint_semantics="host/v1"
    )
    underscored = canonical_text_embedding_identity(
        provider="provider", model="model_a", dimension=8, endpoint_semantics="host/v1"
    )

    assert dashed["table_suffix"] != underscored["table_suffix"]
    assert dashed["identity_hash"] != underscored["identity_hash"]


def test_identity_rejects_tampering_and_missing_snapshot():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )

    tampered = dict(identity, dimension=16)
    with pytest.raises(RuntimeError, match="text_embedding_identity_invalid"):
        load_text_embedding_identity(tampered)

    with pytest.raises(RuntimeError, match="text_embedding_identity_missing"):
        embedding_identity_from_settings({})
    with pytest.raises(RuntimeError, match="text_embedding_identity_missing"):
        load_task_text_embedding_identity({"settings": {"ingestion": {}}})


def test_snapshot_identity_loader_returns_canonical_identity():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )

    loaded = load_task_text_embedding_identity(
        {"settings": {"text_embedding_identity": identity}}
    )

    assert loaded == identity


def test_environment_resolution_is_used_only_without_snapshot(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "provider")
    monkeypatch.setenv("EMBEDDING_MODEL", "model")
    monkeypatch.setenv("EMBEDDING_DIM", "8")
    monkeypatch.setenv("EMBEDDING_ENDPOINT_SEMANTICS", "host/v1")

    resolved = embedding_identity_from_settings(None)
    assert resolved["model"] == "model"
    assert resolved["dimension"] == 8

    with pytest.raises(RuntimeError, match="text_embedding_identity_missing"):
        embedding_identity_from_settings({"ingestion": {}})


@pytest.mark.asyncio
async def test_kb_identity_registration_is_atomic_and_workspace_scoped(monkeypatch):
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection()

    await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))

    assert any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in connection.executed)
    insert_args = next(args for sql, args in connection.executed if "INSERT INTO" in sql)
    assert insert_args[0] == "kb-a"
    assert insert_args[1] == identity["identity_hash"]


@pytest.mark.asyncio
async def test_kb_identity_registration_rejects_legacy_and_conflicts(monkeypatch):
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    legacy = _IdentityConnection(
        tables={"LIGHTRAG_VDB_CHUNKS": "lightrag_vdb_chunks"},
        table_rows={"lightrag_vdb_chunks": 1},
    )
    with pytest.raises(RuntimeError, match="embedding_legacy_storage_incompatible"):
        await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(legacy))
    assert not any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in legacy.executed)

    conflict = _IdentityConnection(
        registry_row={"identity_hash": "other", "identity": {"identity_hash": "other"}}
    )
    with pytest.raises(RuntimeError, match="embedding_identity_conflict"):
        await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(conflict))


@pytest.mark.asyncio
async def test_kb_identity_registration_accepts_existing_jsonb_string_row():
    # asyncpg returns JSONB columns as JSON text; a matching stored row must
    # not raise a conflict on restart (regression for startup crash).
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection(
        registry_row={"identity_hash": identity["identity_hash"],
                     "identity": json.dumps(dict(identity), sort_keys=True)}
    )
    await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))
    assert not any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in connection.executed)


@pytest.mark.asyncio
async def test_kb_identity_registration_rejects_mismatched_jsonb_string():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection(
        registry_row={"identity_hash": identity["identity_hash"],
                     "identity": json.dumps({"identity_hash": "other"}, sort_keys=True)}
    )
    with pytest.raises(RuntimeError, match="embedding_identity_conflict"):
        await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))


@pytest.mark.asyncio
async def test_kb_identity_registration_rejects_unsafe_workspace_override(monkeypatch):
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    monkeypatch.setenv("PG_WORKSPACE", "other-kb")
    with pytest.raises(RuntimeError, match="embedding_workspace_override_rejected"):
        await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(_IdentityConnection()))


def test_identity_suffix_stays_short_for_long_model_name():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model-" * 100, dimension=1024, endpoint_semantics="host/v1"
    )

    assert len(identity["table_suffix"]) <= 30


@pytest.mark.asyncio
async def test_kb_identity_registration_succeeds_when_vector_tables_are_missing():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection()

    await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))

    assert any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in connection.executed)
    # Regression: when the legacy tables are absent, no COUNT may be issued; the
    # old code raised on the missing table and the next statement failed with
    # InFailedSQLTransactionError, aborting startup.
    assert not any(sql.startswith("SELECT COUNT(*) FROM") for _m, sql, _a in connection.queries)
    info = next(sql for _m, sql, _a in connection.queries if "information_schema.tables" in sql)
    assert "lower(t.table_name)=lower($1)" in info
    assert "column_name='workspace'" in info


@pytest.mark.asyncio
async def test_kb_identity_registration_rejects_legacy_rows_in_any_table():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection(
        tables={"LIGHTRAG_VDB_CHUNKS": "lightrag_vdb_chunks"},
        table_rows={"lightrag_vdb_chunks": 2},
    )
    with pytest.raises(RuntimeError, match="embedding_legacy_storage_incompatible"):
        await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))
    assert not any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in connection.executed)


@pytest.mark.asyncio
async def test_kb_identity_registration_ignores_table_without_workspace_column():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection(tables={"LIGHTRAG_VDB_CHUNKS": None})

    await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))

    assert any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in connection.executed)
    info = next(sql for _m, sql, _a in connection.queries if "information_schema.tables" in sql)
    assert "column_name='workspace'" in info


@pytest.mark.asyncio
async def test_kb_identity_registration_matches_actual_table_name_case_insensitively():
    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection(
        tables={"LIGHTRAG_VDB_CHUNKS": "LIGHTRAG_VDB_CHUNKS"},
        table_rows={"LIGHTRAG_VDB_CHUNKS": 1},
    )
    with pytest.raises(RuntimeError, match="embedding_legacy_storage_incompatible"):
        await ensure_kb_embedding_identity("kb-a", identity, pool=_IdentityPool(connection))
    assert not any("INSERT INTO kb_text_embedding_identities" in sql for sql, _ in connection.executed)
    info = next(sql for _m, sql, _a in connection.queries if "information_schema.tables" in sql)
    assert "lower(t.table_name)=lower($1)" in info


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_prefers_identity_suffixed_table():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    physical = f"lightrag_vdb_chunks_{identity['model_name']}_8d"
    connection = _IdentityConnection(
        registry_row={"identity": json.dumps(dict(identity), sort_keys=True)},
        existing_tables={physical, "lightrag_vdb_chunks"},
    )

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table == physical
    assert any("SELECT identity FROM kb_text_embedding_identities" in sql
               for _m, sql, _a in connection.queries)


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_matches_lowercase_physical_table():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    # LightRAG DDL is unquoted, so PostgreSQL stores the physical name in
    # lowercase even though the candidate is requested in upper case.
    physical = f"lightrag_vdb_chunks_{identity['model_name']}_8d"
    connection = _IdentityConnection(
        registry_row={"identity": json.dumps(dict(identity), sort_keys=True)},
        existing_tables={physical},
    )

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table == physical


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_falls_back_to_legacy_without_registration():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    connection = _IdentityConnection(existing_tables={"lightrag_vdb_chunks"})

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table == "lightrag_vdb_chunks"


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_falls_back_to_legacy_when_suffixed_missing():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    identity = canonical_text_embedding_identity(
        provider="provider", model="model", dimension=8, endpoint_semantics="host/v1"
    )
    connection = _IdentityConnection(
        registry_row={"identity": json.dumps(dict(identity), sort_keys=True)},
        existing_tables={"lightrag_vdb_chunks"},
    )

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table == "lightrag_vdb_chunks"


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_falls_back_after_invalid_identity_json():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    connection = _IdentityConnection(
        registry_row={"identity": "{not-valid-json"},
        existing_tables={"lightrag_vdb_chunks"},
    )

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table == "lightrag_vdb_chunks"


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_parses_string_dimension():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    physical = "lightrag_vdb_chunks_provider_model_abc_1024d"
    connection = _IdentityConnection(
        registry_row={"identity": {"model_name": "provider_model_abc", "dimension": "1024"}},
        existing_tables={physical},
    )

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table == physical


@pytest.mark.asyncio
async def test_resolve_vector_chunk_table_returns_none_when_no_table_exists():
    from raganything.services.pg_embedding_identity import resolve_vector_chunk_table

    connection = _IdentityConnection(registry_row={"identity": {}})

    table = await resolve_vector_chunk_table(connection, "./rag_storage_kb-a")

    assert table is None
