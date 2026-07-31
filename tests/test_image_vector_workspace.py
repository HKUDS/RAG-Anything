from contextlib import asynccontextmanager

import numpy as np
import pytest

from raganything.embedding.image_vector_repo import ImageVectorRepository


class _Connection:
    def __init__(self):
        self.executed = []
        self.fetched = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "DELETE 1"

    async def fetch(self, sql, *args):
        self.fetched.append((sql, args))
        return []

    async def fetchval(self, sql, *args):
        self.fetched.append((sql, args))
        return 0


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
async def test_pg_vision_vectors_are_scoped_by_workspace(monkeypatch, tmp_path):
    connection = _Connection()
    pool = _Pool(connection)
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: pool
    )

    repo_a = ImageVectorRepository(str(tmp_path / "kb-a"))
    repo_b = ImageVectorRepository(str(tmp_path / "kb-b"))
    repo_a._use_pg = True
    repo_b._use_pg = True

    metadata = {
        "doc_id": "doc-same-content",
        "entity_name": "figure",
        "image_path": "figure.png",
    }
    await repo_a.upsert("same-image", np.array([1.0, 0.0]), metadata)
    await repo_b.upsert("same-image", np.array([1.0, 0.0]), metadata)
    await repo_a.delete_by_doc_id("doc-same-content")
    await repo_b.delete_by_doc_id("doc-same-content")

    upsert_calls = [call for call in connection.executed if "INSERT INTO" in call[0]]
    assert len(upsert_calls) == 2
    assert "$11::double precision[]" in upsert_calls[0][0]
    assert upsert_calls[0][1][10] == [1.0, 0.0]
    assert upsert_calls[0][1][0] != upsert_calls[1][1][0]
    assert upsert_calls[0][1][1] == repo_a._workspace
    assert upsert_calls[1][1][1] == repo_b._workspace

    delete_calls = [call for call in connection.executed if "DELETE FROM" in call[0]]
    assert [call[1] for call in delete_calls] == [
        (
            repo_a._workspace,
            "doc-same-content",
            repo_a._profile_id,
            repo_a._profile_fingerprint,
        ),
        (
            repo_b._workspace,
            "doc-same-content",
            repo_b._profile_id,
            repo_b._profile_fingerprint,
        ),
    ]

    await repo_a.query(np.array([1.0, 0.0]), top_k=3)
    query_sql, query_args = connection.fetched[-1]
    assert "array_cosine_similarity" in query_sql
    assert "<=>" not in query_sql
    assert query_args[0] == [1.0, 0.0]


@pytest.mark.asyncio
async def test_pg_vision_orphan_scan_does_not_read_other_workspaces(monkeypatch, tmp_path):
    connection = _Connection()
    pool = _Pool(connection)
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: pool
    )
    repo = ImageVectorRepository(str(tmp_path / "kb-a"))
    repo._use_pg = True

    await repo.get_orphan_ids({"doc-current"})

    sql, args = connection.fetched[0]
    assert "WHERE workspace = $1" in sql
    assert args == (
        repo._workspace,
        repo._profile_id,
        repo._profile_fingerprint,
    )


@pytest.mark.asyncio
async def test_pg_vision_records_are_scoped_by_profile(monkeypatch, tmp_path):
    connection = _Connection()
    pool = _Pool(connection)
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: pool
    )
    workspace = str(tmp_path / "kb")
    old_repo = ImageVectorRepository(
        workspace, profile_id="embedding-a", profile_fingerprint="fingerprint-a"
    )
    target_repo = ImageVectorRepository(
        workspace, profile_id="embedding-b", profile_fingerprint="fingerprint-b"
    )
    old_repo._use_pg = True
    target_repo._use_pg = True
    metadata = {"doc_id": "document", "entity_name": "figure"}

    await old_repo.upsert("same-image", np.array([1.0, 0.0]), metadata)
    await target_repo.upsert("same-image", np.array([1.0, 0.0]), metadata)

    calls = [call for call in connection.executed if "INSERT INTO" in call[0]]
    assert calls[0][1][0] != calls[1][1][0]
    assert calls[0][1][12:15] == ("embedding-a", "fingerprint-a", 0)
    assert calls[1][1][12:15] == ("embedding-b", "fingerprint-b", 0)


@pytest.mark.asyncio
async def test_pgvector_upgrade_schema_uses_vector_cast_and_distance(monkeypatch, tmp_path):
    from raganything.embedding import image_vector_repo

    connection = _Connection()
    pool = _Pool(connection)
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: pool
    )
    monkeypatch.setattr(image_vector_repo, "_pg_embedding_kind", "vector")
    repo = ImageVectorRepository(str(tmp_path / "kb-vector"))
    repo._use_pg = True

    await repo.upsert("image", np.array([1.0, 0.0]), {"doc_id": "doc"})
    await repo.query(np.array([1.0, 0.0]), top_k=2)

    insert_sql, insert_args = next(
        call for call in connection.executed if "INSERT INTO" in call[0]
    )
    query_sql, query_args = connection.fetched[-1]
    assert "$11::vector" in insert_sql
    assert insert_args[10] == "[1.0,0.0]"
    assert "embedding <=> $1::vector" in query_sql
    assert "array_cosine_similarity" not in query_sql
    assert query_args[0] == "[1.0,0.0]"


def test_workspace_migration_is_present():
    from pathlib import Path

    migration = Path("migrations/014_image_vision_workspace.sql").read_text(
        encoding="utf-8"
    )
    assert "ADD COLUMN IF NOT EXISTS workspace" in migration
    assert "idx_ivv_workspace_doc_id" in migration


def test_nano_vector_files_are_scoped_by_profile_id(tmp_path):
    first = ImageVectorRepository(
        str(tmp_path), profile_id="embedding-a", profile_fingerprint="same"
    )
    second = ImageVectorRepository(
        str(tmp_path), profile_id="embedding-b", profile_fingerprint="same"
    )

    assert first._db_path != second._db_path
