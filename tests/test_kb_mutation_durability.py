"""Durable KB mutation and upload-claim contracts without a live database."""

from __future__ import annotations

import asyncio

import pytest

from raganything.services import kb_corpus_revision, kb_mutation, kb_service


@pytest.mark.asyncio
async def test_kb_mutation_does_not_bypass_an_active_reindex(monkeypatch):
    called = False

    async def blocked(*_args, **_kwargs):
        raise RuntimeError("reindex_in_progress")

    async def operation():
        nonlocal called
        called = True

    monkeypatch.setattr(kb_mutation, "acquire_kb_mutation_lease", blocked)

    with pytest.raises(RuntimeError, match="reindex_in_progress"):
        await kb_mutation.run_kb_mutation_with_lease(
            "demo", "task-1", operation, mutation_kind="content"
        )
    assert called is False


@pytest.mark.asyncio
async def test_kb_mutation_lease_loss_cancels_the_operation(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def immediate_sleep(_seconds):
        await started.wait()

    async def heartbeat_lost(*_args, **_kwargs):
        return False

    async def release(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kb_mutation, "acquire_kb_mutation_lease", lambda *_args, **_kwargs: _async_value("lease-1"))
    monkeypatch.setattr(kb_mutation.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(kb_mutation, "heartbeat_kb_mutation_lease", heartbeat_lost)
    monkeypatch.setattr(kb_mutation, "release_kb_mutation_lease", release)

    with pytest.raises(RuntimeError, match="kb_mutation_lease_lost"):
        await kb_mutation.run_kb_mutation_with_lease(
            "demo", "task-1", operation, mutation_kind="content"
        )
    assert cancelled.is_set()


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_corpus_mutation_commits_once_after_the_operation(monkeypatch):
    calls = []

    async def begin(*args):
        calls.append(("begin", args))

    async def commit(*args):
        calls.append(("commit", args))
        return 9

    async def operation():
        calls.append(("operation", ()))
        return "done"

    monkeypatch.setattr(kb_corpus_revision, "begin_corpus_mutation", begin)
    monkeypatch.setattr(kb_corpus_revision, "commit_corpus_mutation", commit)

    assert await kb_corpus_revision.run_corpus_mutation("demo", "mutation-1", "content", operation) == "done"
    assert [name for name, _args in calls] == ["begin", "operation", "commit"]


@pytest.mark.asyncio
async def test_corpus_reconciliation_commits_each_stale_marker_once(monkeypatch):
    committed = []

    class Connection:
        async def fetch(self, _query):
            return [{"id": "old-1", "kb": "demo"}, {"id": "old-2", "kb": "other"}]

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    async def commit(kb, mutation_id):
        committed.append((kb, mutation_id))
        return 1

    monkeypatch.setattr(kb_corpus_revision, "get_pg_pool", lambda: Pool())
    monkeypatch.setattr(kb_corpus_revision, "commit_corpus_mutation", commit)

    assert await kb_corpus_revision.reconcile_pending_corpus_mutations() == 2
    assert committed == [("demo", "old-1"), ("other", "old-2")]


@pytest.mark.asyncio
async def test_upload_claim_and_heartbeat_are_owner_and_generation_fenced(monkeypatch):
    queries = []

    class Pool:
        async def fetchrow(self, query, *args):
            queries.append(("fetchrow", query, args))
            return {"processing_generation": 4}

        async def execute(self, query, *args):
            queries.append(("execute", query, args))
            return "UPDATE 1" if args[-1] == 4 else "UPDATE 0"

    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())

    assert await kb_service.pg_claim_upload_task("task-1", "demo", "owner-a") == 4
    assert await kb_service.pg_heartbeat_upload_claim("task-1", "demo", "owner-a", 4)
    assert not await kb_service.pg_heartbeat_upload_claim("task-1", "demo", "owner-a", 5)
    assert "processing_generation=processing_generation+1" in queries[0][1]
    assert "processing_owner=$3" in queries[1][1]
    assert "processing_generation=$4" in queries[1][1]


@pytest.mark.asyncio
async def test_kb_mutation_lease_binds_numeric_ttl_as_an_interval(monkeypatch):
    queries = []

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Connection:
        def transaction(self):
            return Transaction()

        async def execute(self, query, *args):
            queries.append((query, args))
            return "UPDATE 1"

        async def fetchval(self, _query, *_args):
            return False

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

        async def execute(self, query, *args):
            queries.append((query, args))
            return "UPDATE 1"

    monkeypatch.setattr(kb_mutation, "get_pg_pool", lambda: Pool())

    await kb_mutation.acquire_kb_mutation_lease(
        "demo", "task-1", "owner-a", mutation_kind="upload", ttl_seconds=45
    )
    assert await kb_mutation.heartbeat_kb_mutation_lease(
        "lease-1", "owner-a", ttl_seconds=45
    )

    interval_queries = [query for query, _args in queries if "INTERVAL '1 second'" in query]
    assert len(interval_queries) == 2
    assert all("::text" not in query for query in interval_queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
async def test_stale_upload_owner_cannot_write_terminal_status(monkeypatch, terminal_status):
    calls = []

    class Pool:
        async def fetchrow(self, query, *args):
            calls.append((query, args))
            owner = args[-2]
            generation = args[-1]
            if owner != "owner-new" or generation != 5:
                return None
            return {
                "id": 1, "filename": "doc.pdf", "file_path": "doc.pdf",
                "file_hash": "hash", "file_size": 1, "kb_name": "demo",
                "uploaded_by": 7, "task_id": "task-1", "status": terminal_status,
                "error_message": "", "outcome": terminal_status,
                "warning_message": "", "created_at": None, "updated_at": None,
            }

    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())
    monkeypatch.setattr(kb_service, "_uploaded_files_has_error_message", True)
    monkeypatch.setattr(kb_service, "_uploaded_files_has_terminal_metadata", True)

    stale = await kb_service.pg_update_upload_status_by_task_id(
        "task-1", terminal_status, kb_name="demo", expected_current_status="processing",
        outcome=terminal_status, claim_owner="owner-old", claim_generation=4,
    )
    current = await kb_service.pg_update_upload_status_by_task_id(
        "task-1", terminal_status, kb_name="demo", expected_current_status="processing",
        outcome=terminal_status, claim_owner="owner-new", claim_generation=5,
    )

    assert stale is None
    assert current["status"] == terminal_status
    assert all("processing_owner" in query and "processing_generation" in query for query, _ in calls)
