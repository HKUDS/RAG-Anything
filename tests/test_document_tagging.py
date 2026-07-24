import asyncio

import pytest


@pytest.mark.asyncio
async def test_wait_for_document_tagging_until_ready(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    states = [
        {"tag_status": "running", "tag_raw_status": "running"},
        {"tag_status": "ready", "tag_raw_status": "completed"},
    ]

    async def health(_kb, _doc_ids):
        return {"doc-1": states.pop(0)}

    monkeypatch.setattr(document_tagging, "get_document_tag_health", health)
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)
    result = await document_tagging.wait_for_document_tagging(
        "demo", "doc-1", timeout=1, poll_interval=0,
    )

    assert result["tag_status"] == "ready"


@pytest.mark.asyncio
async def test_wait_for_document_tagging_retries_transient_health_read(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    calls = 0

    async def health(_kb, _doc_ids):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary database outage")
        return {"doc-1": {"tag_status": "ready", "tag_raw_status": "completed"}}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(document_tagging, "get_document_tag_health", health)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)

    result = await document_tagging.wait_for_document_tagging(
        "demo", "doc-1", timeout=1, poll_interval=0,
    )

    assert calls == 2
    assert result["tag_status"] == "ready"


class _Transaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_args):
        return None


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_enqueue_document_tagging_is_idempotent_and_versioned(monkeypatch):
    from raganything.services import document_quality, document_tagging, kb_service

    calls = []

    class Connection:
        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            return {
                "id": 1,
                "kb_name": args[0],
                "doc_id": args[1],
                "status": "queued",
                "attempt_count": 0,
            }

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))
    async def load_status(_kb):
        return {"doc-1": {"chunks_list": ["chunk-1"]}}
    async def load_chunks(_kb):
        return {"chunk-1": {"content": "valid text"}}
    async def ready_quality(*_args, **_kwargs):
        return {"ready": True}
    monkeypatch.setattr(kb_service, "_load_doc_status_json", load_status)
    monkeypatch.setattr(kb_service, "_load_text_chunks_json", load_chunks)
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", ready_quality)

    job = await document_tagging.enqueue_document_tagging(
        "demo", "doc-1", filename="paper.docx", user_id=7, task_id="task-1",
    )

    sql, args = calls[0]
    assert "ON CONFLICT (kb_name, doc_id)" in sql
    assert "tagger_version" in sql
    assert "rerun_requested = document_tag_jobs.status = 'running'" in sql
    assert "priority" in sql
    assert "upload_task_id" in sql
    assert "document_tag_jobs.status = 'running'" in sql
    assert "document_tag_jobs.upload_task_id <> ''" in sql
    assert "task-1" in args
    assert args[-1] == document_tagging.TAGGER_VERSION
    assert job["status"] == "queued"


@pytest.mark.asyncio
async def test_complete_tag_job_requeues_rerun_with_fresh_retry_budget(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))

    await document_tagging.complete_tag_job(9, {
        "assigned": 4,
        "chunk_count": 2,
        "eligible_chunk_count": 2,
        "tagged_chunk_count": 2,
        "not_applicable_count": 0,
        "content_fingerprint": "abc",
    }, "lease-9")

    sql, args = calls[0]
    assert "WHEN rerun_requested THEN 'queued'" in sql
    assert "attempt_count = CASE WHEN rerun_requested THEN 0" in sql
    assert "rerun_requested = FALSE" in sql
    assert args[0] == 9
    assert args[-1] == "lease-9"


@pytest.mark.asyncio
async def test_failed_running_job_prioritizes_requested_rerun(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))
    monkeypatch.setattr(document_tagging.random, "uniform", lambda *_args: 1.0)

    await document_tagging.fail_tag_job(
        {
            "id": 8, "attempt_count": 5, "max_attempts": 5,
            "lease_token": "lease-8",
        },
        RuntimeError("old revision failed"),
    )

    sql, args = calls[0]
    assert "WHEN rerun_requested THEN 'queued'" in sql
    assert "attempt_count = CASE WHEN rerun_requested THEN 0" in sql
    assert "rerun_requested = FALSE" in sql
    assert args[1] == "terminal_failed"
    assert args[-1] == "lease-8"


@pytest.mark.asyncio
async def test_integrity_mismatch_is_terminal_without_retry(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))
    monkeypatch.setattr(document_tagging.random, "uniform", lambda *_args: 1.0)

    await document_tagging.fail_tag_job(
        {
            "id": 10, "attempt_count": 1, "max_attempts": 5,
            "lease_token": "lease-integrity",
        },
        document_tagging.AutomaticTaggingIntegrityError(
            "document chunks are not fully visible"
        ),
    )

    _sql, args = calls[0]
    assert args[1] == "terminal_failed"
    assert args[2] is False
    assert args[-1] == "lease-integrity"


@pytest.mark.asyncio
async def test_cancelled_tag_job_releases_only_its_own_lease(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))

    await document_tagging.release_cancelled_tag_job({
        "id": 12,
        "lease_token": "lease-12",
    })

    sql, args = calls[0]
    assert "status = 'queued'" in sql
    assert "attempt_count = GREATEST(0, attempt_count - 1)" in sql
    assert "status = 'running' AND lease_token = $2" in sql
    assert args == (12, "lease-12")


@pytest.mark.asyncio
async def test_claim_due_tag_job_uses_lease_and_skip_locked(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            if "SELECT id" in sql:
                return {"id": 4}
            return {"id": 4, "status": "running", "attempt_count": 1}

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))

    job = await document_tagging.claim_due_tag_job()

    assert "FOR UPDATE SKIP LOCKED" in calls[0][0]
    assert "ORDER BY priority DESC" in calls[0][0]
    assert "lease_until" in calls[1][0]
    assert "lease_token = $3" in calls[1][0]
    assert job["status"] == "running"


@pytest.mark.asyncio
async def test_run_tag_job_delegates_to_persisted_chunk_generator(monkeypatch):
    from raganything.services import auto_tagging, document_tagging, kb_service

    recorded = []

    async def generate(kb, doc_id, *, filename, user_id):
        recorded.append((kb, doc_id, filename, user_id))
        return {"assigned": 8, "chunk_count": 2, "chunk_source": "postgres"}

    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)
    monkeypatch.setattr(kb_service, "_generate_uploaded_document_tags", generate)
    async def ready(*_args, **_kwargs):
        return {"quality": {"ready": True}}
    monkeypatch.setattr(document_tagging, "_validate_document_tagging_readiness", ready)

    result = await document_tagging.run_tag_job({
        "kb_name": "demo", "doc_id": "doc-1", "filename": "paper.docx", "user_id": 7,
    })

    assert result["assigned"] == 8
    assert recorded == [("demo", "doc-1", "paper.docx", 7)]


@pytest.mark.asyncio
async def test_run_tag_job_retries_when_chunks_are_not_visible(monkeypatch):
    from raganything.services import auto_tagging, document_tagging, kb_service

    generated = False

    async def generate(*_args, **_kwargs):
        nonlocal generated
        generated = True
        return {"assigned": 0, "chunk_count": 0, "chunk_source": "none"}

    async def not_ready(*_args, **_kwargs):
        raise RuntimeError("persisted chunks are not visible")

    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)
    monkeypatch.setattr(kb_service, "_generate_uploaded_document_tags", generate)
    monkeypatch.setattr(document_tagging, "_validate_document_tagging_readiness", not_ready)

    with pytest.raises(RuntimeError, match="not visible"):
        await document_tagging.run_tag_job({
            "kb_name": "demo", "doc_id": "doc-1", "filename": "paper.docx",
        })
    assert generated is False


@pytest.mark.asyncio
async def test_tag_readiness_uses_authoritative_status_and_persisted_chunks(monkeypatch):
    from types import SimpleNamespace

    from raganything.services import (
        document_quality,
        document_tagging,
        kb_chunk_repo,
        kb_service,
    )

    async def get_kb(kb_name):
        assert kb_name == "demo"
        return SimpleNamespace(lightrag=SimpleNamespace())

    async def load_status(kb_name, doc_id):
        assert (kb_name, doc_id) == ("demo", "doc-1")
        return {
            "status": "processed",
            "chunks_count": 2,
            "chunks_list": ["chunk-1", "chunk-2"],
        }

    async def persisted(_lightrag, doc_id):
        assert doc_id == "doc-1"
        return [
            {"id": "chunk-1", "content": "first"},
            {"id": "chunk-2", "content": "second"},
        ]

    async def quality(kb_name, chunk_ids, text_chunks):
        assert kb_name == "demo"
        assert chunk_ids == ["chunk-1", "chunk-2"]
        assert set(text_chunks) == {"chunk-1", "chunk-2"}
        return {"ready": True, "expected_count": 2}

    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", load_status)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", persisted)
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", quality)

    result = await document_tagging._validate_document_tagging_readiness(
        "demo", "doc-1",
    )

    assert result["chunk_ids"] == ["chunk-1", "chunk-2"]
    assert result["quality"]["ready"] is True


@pytest.mark.asyncio
async def test_tag_readiness_rejects_incomplete_multimodal_state(monkeypatch):
    from types import SimpleNamespace

    from raganything.services import kb_service, kb_chunk_repo, document_tagging

    async def get_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace())

    async def load_status(_kb_name, _doc_id):
        return {
            "status": "failed",
            "chunks_count": 1,
            "chunks_list": ["chunk-1"],
            "metadata": {
                "content_ready": False,
                "multimodal_processed": False,
                "failure_stage": "worker_timeout",
            },
        }

    async def should_not_query(*_args, **_kwargs):
        raise AssertionError("incomplete multimodal documents must not be tagged")

    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", load_status)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", should_not_query)

    with pytest.raises(RuntimeError, match="not ready for automatic tagging"):
        await document_tagging._validate_document_tagging_readiness(
            "demo", "doc-partial"
        )


@pytest.mark.asyncio
async def test_tag_chunk_load_is_document_scoped_and_never_repairs_status(monkeypatch):
    from types import SimpleNamespace

    from raganything.services import kb_service

    async def load_by_id(kb_name, doc_id):
        assert (kb_name, doc_id) == ("demo", "doc-1")
        return {
            "status": "processed",
            "chunks_count": 2,
            "chunks_list": ["chunk-1", "chunk-2"],
            "metadata": {},
        }

    async def load_all(_kb_name):
        raise AssertionError("tagging must not hydrate every document status")

    class TextChunks:
        async def get_by_ids(self, chunk_ids):
            assert chunk_ids == ["chunk-1", "chunk-2"]
            return [
                {"id": "chunk-1", "content": "first"},
                {"id": "chunk-2", "content": "second"},
            ]

    class DocStatus:
        async def upsert(self, _data):
            raise AssertionError("tagging must not repair document status")

    async def get_kb(_kb_name):
        return SimpleNamespace(
            lightrag=SimpleNamespace(text_chunks=TextChunks(), doc_status=DocStatus())
        )

    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", load_by_id)
    monkeypatch.setattr(kb_service, "_load_doc_status_json", load_all)
    monkeypatch.setattr(kb_service, "get_kb", get_kb)

    chunks, recovery = await kb_service._load_automatic_tag_chunks("demo", "doc-1")

    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-1", "chunk-2"]
    assert recovery == {
        "chunk_count": 2,
        "status_retries": 0,
        "status_repaired": False,
        "chunk_source": "doc_status",
    }


@pytest.mark.asyncio
async def test_run_tag_job_does_not_complete_when_tagging_is_disabled(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: False)

    with pytest.raises(document_tagging.AutomaticTaggingDisabledError):
        await document_tagging.run_tag_job({"kb_name": "demo", "doc_id": "doc-1"})


@pytest.mark.asyncio
async def test_disabled_worker_leaves_jobs_unclaimed(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    async def ensure():
        return None

    async def claim():
        raise AssertionError("disabled tagging must not claim persisted jobs")

    async def stop_after_one_sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(document_tagging, "ensure_document_tag_jobs_table", ensure)
    monkeypatch.setattr(document_tagging, "claim_due_tag_job", claim)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", stop_after_one_sleep)
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: False)

    with pytest.raises(asyncio.CancelledError):
        await document_tagging.document_tagging_loop(0)


@pytest.mark.asyncio
async def test_reconciliation_enqueues_durable_documents_missing_jobs(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    queued = []

    class Connection:
        async def fetch(self, sql, *args):
            assert "LIGHTRAG_DOC_STATUS" in sql
            assert "u.status IN ('queued', 'processing', 'retry_wait')" in sql
            assert "d.created_at >=" in sql
            assert "j.id IS NULL" in sql
            assert "terminal_failed" not in sql
            assert args == (200,)
            return [{
                "kb_name": "demo",
                "doc_id": "doc-1",
                "file_path": "paper.docx",
                "upload_task_id": "task-1",
            }]

    async def enqueue(kb, doc_id, **kwargs):
        queued.append((kb, doc_id, kwargs))
        return {"id": 1}

    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)
    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))
    monkeypatch.setattr(document_tagging, "enqueue_document_tagging", enqueue)

    count = await document_tagging.reconcile_missing_document_tags()

    assert count == 1
    assert queued == [(
        "demo", "doc-1", {
            "filename": "paper.docx", "task_id": "task-1", "priority": 0,
        }
    )]


@pytest.mark.asyncio
async def test_reconciliation_isolates_one_document_enqueue_failure(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    class Connection:
        async def fetch(self, _sql, *_args):
            return [
                {"kb_name": "demo", "doc_id": "bad", "file_path": "bad.pdf", "upload_task_id": "task-bad"},
                {"kb_name": "demo", "doc_id": "good", "file_path": "good.pdf", "upload_task_id": "task-good"},
            ]

    queued = []

    async def enqueue(_kb, doc_id, **_kwargs):
        if doc_id == "bad":
            raise RuntimeError("bad status")
        queued.append(doc_id)
        return {"id": 2}

    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)
    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))
    monkeypatch.setattr(document_tagging, "enqueue_document_tagging", enqueue)

    count = await document_tagging.reconcile_missing_document_tags()

    assert count == 1
    assert queued == ["good"]


@pytest.mark.asyncio
async def test_terminate_document_tagging_marks_noncompleted_job_terminal(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))

    await document_tagging.terminate_document_tagging(
        "demo", "doc-1", "tagging timed out",
    )

    sql, args = calls[0]
    assert "status = 'terminal_failed'" in sql
    assert "status <> 'completed'" in sql
    assert args == ("demo", "doc-1", "tagging timed out")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_status", "expected_upload_status"),
    [("completed", "completed"), ("terminal_failed", "failed")],
)
async def test_terminal_tag_jobs_reconcile_upload_after_restart(
    monkeypatch, job_status, expected_upload_status,
):
    from raganything.services import document_tagging, kb_service, state_service

    class Pool:
        async def fetch(self, sql, *args):
            assert "j.upload_task_id <> ''" in sql
            assert "u.kb_name = j.kb_name" in sql
            assert "u.status IN ('queued', 'processing', 'retry_wait')" in sql
            assert args == (200,)
            return [{
                "task_id": "task-1",
                "kb_name": "demo",
                "doc_id": "doc-1",
                "status": job_status,
                "last_error": "tagger failed" if job_status == "terminal_failed" else "",
            }]

    calls = []

    async def complete(task_id, **kwargs):
        calls.append(("complete", task_id, kwargs))

    async def fail(task_id, error, **kwargs):
        calls.append(("fail", task_id, error, kwargs))

    async def update(task_id, status, **kwargs):
        calls.append(("upload", task_id, status, kwargs))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: Pool())
    monkeypatch.setattr(state_service, "complete_task", complete)
    monkeypatch.setattr(state_service, "fail_task", fail)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)

    count = await document_tagging.reconcile_terminal_tag_uploads()

    assert count == 1
    upload = next(call for call in calls if call[0] == "upload")
    assert upload[2] == expected_upload_status
    if job_status == "completed":
        assert calls[0][0] == "complete"
    else:
        assert calls[0] == (
            "fail",
            "task-1",
            "tagger failed",
            {"outcome": "terminal_failed", "failure_stage": "tagging", "retryable": False},
        )


def test_document_tag_health_requires_actual_persisted_coverage():
    from raganything.services import document_tagging

    base = {
        "status": "completed",
        "tagger_version": document_tagging.TAGGER_VERSION,
        "chunk_count": 3,
        "eligible_chunk_count": 2,
        "tagged_chunk_count": 2,
        "not_applicable_count": 1,
        "actual_tagged_chunk_count": 2,
        "last_error": "",
    }
    ready = document_tagging.derive_document_tag_health(base)
    drifted = document_tagging.derive_document_tag_health({
        **base, "actual_tagged_chunk_count": 1,
    })

    assert ready["tag_status"] == "ready"
    assert ready["tagged_chunks"] == 2
    assert drifted["tag_status"] == "pending"
    assert drifted["tagged_chunks"] == 1


def test_tagger_version_stays_stable_for_future_upload_only_rollout():
    from raganything.services import document_tagging

    assert document_tagging.TAGGER_VERSION == "7"


def test_document_tag_health_distinguishes_not_applicable_and_disabled():
    from raganything.services import document_tagging

    not_applicable = document_tagging.derive_document_tag_health({
        "status": "completed",
        "tagger_version": document_tagging.TAGGER_VERSION,
        "chunk_count": 2,
        "eligible_chunk_count": 0,
        "tagged_chunk_count": 0,
        "not_applicable_count": 2,
        "actual_tagged_chunk_count": 0,
    })
    disabled = document_tagging.derive_document_tag_health(None, enabled=False)

    assert not_applicable["tag_status"] == "not_applicable"
    assert disabled["tag_status"] == "disabled"
    assert disabled["tag_retryable"] is False


@pytest.mark.asyncio
async def test_tag_health_query_verifies_assignments_and_marks_missing_jobs(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    class Connection:
        async def fetch(self, sql, *args):
            if "LEFT JOIN LATERAL" in sql:
                assert "assignment_kind IN ('auto_document', 'auto_chunk')" in sql
                assert args == ("demo", ["doc-1", "doc-2", "doc-3"])
                return [{
                    "doc_id": "doc-1",
                    "status": "completed",
                    "tagger_version": document_tagging.TAGGER_VERSION,
                    "chunk_count": 1,
                    "eligible_chunk_count": 1,
                    "tagged_chunk_count": 1,
                    "not_applicable_count": 0,
                    "actual_tagged_chunk_count": 1,
                    "unique_auto_tag_count": 6,
                    "auto_tag_assignment_count": 8,
                    "last_error": "",
                }]
            assert "FROM LIGHTRAG_DOC_STATUS" in sql
            assert args == (
                "./rag_storage_demo", ["doc-1", "doc-2", "doc-3"], "demo",
            )
            return [{"id": "doc-2"}]

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)

    result = await document_tagging.get_document_tag_health(
        "demo", ["doc-1", "doc-2", "doc-3"]
    )

    assert result["doc-1"]["tag_status"] == "ready"
    assert result["doc-1"]["unique_auto_tag_count"] == 6
    assert result["doc-1"]["auto_tag_assignment_count"] == 8
    assert result["doc-1"]["avg_auto_tags_per_tagged_chunk"] == 8.0
    assert result["doc-2"]["tag_status"] == "pending"
    assert result["doc-3"]["tag_status"] == "unmanaged"
    assert result["doc-3"]["tag_retryable"] is False


@pytest.mark.asyncio
async def test_tagging_loop_survives_transient_claim_failure(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    claims = 0
    sleeps = 0

    async def no_op(*_args, **_kwargs):
        return 0

    async def claim():
        nonlocal claims
        claims += 1
        if claims == 1:
            raise ConnectionError("temporary database outage")
        return None

    async def controlled_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(document_tagging, "ensure_document_tag_jobs_table", no_op)
    monkeypatch.setattr(document_tagging, "reconcile_terminal_tag_uploads", no_op)
    monkeypatch.setattr(document_tagging, "cleanup_deleted_document_tag_assignments", no_op)
    monkeypatch.setattr(document_tagging, "reconcile_missing_document_tags", no_op)
    monkeypatch.setattr(document_tagging, "claim_due_tag_job", claim)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", controlled_sleep)
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)

    with pytest.raises(asyncio.CancelledError):
        await document_tagging.document_tagging_loop(interval_seconds=0)

    assert claims == 2


@pytest.mark.asyncio
async def test_tagging_loop_retries_queue_initialization(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    initializations = 0
    sleeps = 0

    async def ensure():
        nonlocal initializations
        initializations += 1
        if initializations == 1:
            raise ConnectionError("temporary database outage")

    async def no_op(*_args, **_kwargs):
        return 0

    async def no_job():
        return None

    async def controlled_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(document_tagging, "ensure_document_tag_jobs_table", ensure)
    monkeypatch.setattr(document_tagging, "reconcile_terminal_tag_uploads", no_op)
    monkeypatch.setattr(document_tagging, "cleanup_deleted_document_tag_assignments", no_op)
    monkeypatch.setattr(document_tagging, "reconcile_missing_document_tags", no_op)
    monkeypatch.setattr(document_tagging, "claim_due_tag_job", no_job)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", controlled_sleep)
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)

    with pytest.raises(asyncio.CancelledError):
        await document_tagging.document_tagging_loop(interval_seconds=0)

    assert initializations == 2


@pytest.mark.asyncio
async def test_tagging_loop_survives_disabled_job_defer_failure(monkeypatch):
    from raganything.services import auto_tagging, document_tagging

    async def no_op(*_args, **_kwargs):
        return 0

    async def claim():
        return {"id": 7, "kb_name": "demo", "doc_id": "doc-1"}

    async def disabled(_job):
        raise document_tagging.AutomaticTaggingDisabledError

    async def defer(_job):
        raise ConnectionError("temporary database outage")

    async def stop_after_recovery(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(document_tagging, "ensure_document_tag_jobs_table", no_op)
    monkeypatch.setattr(document_tagging, "reconcile_terminal_tag_uploads", no_op)
    monkeypatch.setattr(document_tagging, "cleanup_deleted_document_tag_assignments", no_op)
    monkeypatch.setattr(document_tagging, "reconcile_missing_document_tags", no_op)
    monkeypatch.setattr(document_tagging, "claim_due_tag_job", claim)
    monkeypatch.setattr(document_tagging, "run_tag_job", disabled)
    monkeypatch.setattr(document_tagging, "defer_disabled_tag_job", defer)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", stop_after_recovery)
    monkeypatch.setattr(auto_tagging, "automatic_tagging_enabled", lambda: True)

    with pytest.raises(asyncio.CancelledError):
        await document_tagging.document_tagging_loop(interval_seconds=0)


@pytest.mark.asyncio
async def test_tag_list_uses_stable_offset_pagination(monkeypatch):
    from raganything.services import kb_tag_repo

    calls = []

    class Connection:
        async def fetch(self, sql, *args):
            calls.append((sql, args))
            return [{
                "id": 9,
                "display_name": "冷却液温度传感器",
                "document_count": 2,
                "chunk_count": 5,
            }]

    async def get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(kb_tag_repo, "_get_tag_pool", get_pool)

    result = await kb_tag_repo.list_tags("demo", "冷却", limit=200, offset=400)

    assert result[0]["id"] == 9
    assert "t.id ASC" in calls[0][0]
    assert "LIMIT $3 OFFSET $4" in calls[0][0]
    assert calls[0][1] == ("demo", "冷却", 200, 400)


@pytest.mark.asyncio
async def test_manual_tag_write_uses_document_lock_and_promotes_retained_auto_tag(monkeypatch):
    from raganything.services import kb_tag_repo

    calls = []
    fetch_count = 0

    class Connection:
        def transaction(self):
            return _Transaction()

        async def execute(self, sql, *args):
            calls.append((sql, args))

        async def fetch(self, sql, *args):
            nonlocal fetch_count
            fetch_count += 1
            if fetch_count == 1:
                return [{"tag_id": 5, "normalized_name": "水泵轴承"}]
            return [{
                "id": 5,
                "display_name": "水泵轴承",
                "assignment_kind": "manual",
            }]

    async def get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(kb_tag_repo, "_get_tag_pool", get_pool)

    tags = await kb_tag_repo.replace_chunk_tags(
        "demo", "doc-1", "chunk-1", ["水泵轴承"], user_id=7,
    )

    assert tags[0]["assignment_kind"] == "manual"
    assert "pg_advisory_xact_lock" in calls[0][0]
    promotion = next(sql for sql, _args in calls if "SET assignment_kind" in sql)
    assert "created_by = $6" in promotion


@pytest.mark.asyncio
async def test_manual_completion_never_overwrites_a_running_job(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))

    await document_tagging.record_document_tagging_complete(
        "demo", "doc-1", {"chunk_count": 1}
    )

    assert "status <> 'running'" in calls[0][0]


@pytest.mark.asyncio
async def test_orphan_cleanup_only_removes_assignments_for_deleted_documents(monkeypatch):
    from raganything.services import document_tagging

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "DELETE 3" if len(calls) == 1 else "DELETE 1"

    monkeypatch.setattr(document_tagging, "get_pg_pool", lambda: _Pool(Connection()))

    removed = await document_tagging.cleanup_deleted_document_tag_assignments()

    assert removed == 3
    assert "LIGHTRAG_DOC_STATUS" in calls[0][0]
    assert "d.id = a.document_id" in calls[0][0]
    assert "LIGHTRAG_DOC_CHUNKS" not in calls[0][0]


@pytest.mark.asyncio
async def test_persisted_coverage_counts_only_automatic_assignments(monkeypatch):
    from raganything.services import kb_tag_repo

    calls = []
    next_tag_id = 0

    class Connection:
        def transaction(self):
            return _Transaction()

        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))

        async def executemany(self, sql, args):
            calls.append(("executemany", sql, args))

        async def fetch(self, sql, *args):
            calls.append(("fetch", sql, args))
            if "LIGHTRAG_DOC_CHUNKS" in sql:
                return [{"id": "chunk-1"}, {"id": "chunk-2"}]
            if "a.assignment_kind = $3" in sql:
                return []
            if "SELECT DISTINCT chunk_id" in sql:
                assert "assignment_kind = ANY($4::text[])" in sql
                assert set(args[3]) == {"auto_document", "auto_chunk"}
                return [{"chunk_id": "chunk-1"}]
            return []

    async def get_pool():
        return _Pool(Connection())

    async def upsert(*_args, **_kwargs):
        nonlocal next_tag_id
        next_tag_id += 1
        return {"id": next_tag_id}

    monkeypatch.setattr(kb_tag_repo, "_get_tag_pool", get_pool)
    monkeypatch.setattr(kb_tag_repo, "_upsert_tag", upsert)

    result = await kb_tag_repo.replace_automatic_document_tags(
        "demo",
        "doc-1",
        ["shared"],
        {"chunk-1": ["alpha"], "chunk-2": []},
        user_id=3,
        document_tag_names_by_chunk={"chunk-1": ["shared"], "chunk-2": []},
    )

    assert result["tagged_chunk_ids"] == ["chunk-1"]
    assert "pg_advisory_xact_lock" in calls[0][1]


@pytest.mark.asyncio
async def test_changed_or_deleted_chunk_set_aborts_before_tag_writes(monkeypatch):
    from raganything.services import kb_tag_repo

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction()

        async def execute(self, sql, *args):
            calls.append((sql, args))

        async def fetch(self, sql, *_args):
            assert "LIGHTRAG_DOC_CHUNKS" in sql
            return [{"id": "chunk-1"}]

    async def get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(kb_tag_repo, "_get_tag_pool", get_pool)

    with pytest.raises(kb_tag_repo.TagDocumentChangedError):
        await kb_tag_repo.replace_automatic_document_tags(
            "demo",
            "doc-1",
            [],
            {"chunk-1": [], "chunk-deleted": []},
            user_id=3,
        )

    assert len(calls) == 1
    assert "pg_advisory_xact_lock" in calls[0][0]
    assert calls[0][1] == (
        kb_tag_repo.document_mutation_lock_key("demo", "doc-1"),
    )


@pytest.mark.asyncio
async def test_document_tag_deletion_uses_same_lock_as_generation(monkeypatch):
    from raganything.services import kb_tag_repo

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction()

        async def execute(self, sql, *args):
            calls.append((sql, args))

    async def get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(kb_tag_repo, "_get_tag_pool", get_pool)
    await kb_tag_repo.delete_document_tags("demo", "doc-1")

    assert "pg_advisory_xact_lock" in calls[0][0]
    assert calls[0][1] == (
        kb_tag_repo.document_mutation_lock_key("demo", "doc-1"),
    )
    assert "DELETE FROM chunk_tag_assignments" in calls[1][0]


def test_quality_filter_removes_media_paths_page_markers_and_hashes():
    from raganything.services.auto_tagging import build_automatic_tag_plan

    plan = build_automatic_tag_plan(
        [
            {
                "chunk_id": "media",
                "content": """
                    [第 2 页]
                    [图片]
                    图片路径: C:\\Users\\demo\\output\\image_0.png
                    full_doc_id: doc-550bb224a0a4a293b5cafc9239c99aa7
                """,
            },
            {
                "chunk_id": "text",
                "content": "糖尿病视网膜病变筛查使用深度学习识别眼底图像病灶。",
            },
        ],
        filename="7.毕业设计（论文）.docx",
    )

    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    lowered = {tag.casefold() for tag in generated}
    assert not {"users", "output", "image_0", "full_doc_id", "docx"}.intersection(lowered)
    assert plan.chunk_tags["media"] == ()


def test_every_generated_tag_has_source_evidence_and_local_scope():
    from raganything.services.auto_tagging import build_automatic_tag_plan

    chunks = [
        {
            "chunk_id": "model",
            "content": "MobileNetV3 improves diabetic retinopathy screening for retinal images.",
        },
        {
            "chunk_id": "privacy",
            "content": "Diabetic retinopathy screening requires patient privacy and audit controls.",
        },
    ]
    filename = "retinopathy-screening-platform.docx"
    plan = build_automatic_tag_plan(chunks, filename=filename)
    document_evidence = (filename + " " + " ".join(chunk["content"] for chunk in chunks)).casefold()

    assert plan.document_tags
    assert all(tag.casefold() in document_evidence for tag in plan.document_tags)
    for chunk in chunks:
        local_evidence = chunk["content"].casefold()
        assert all(
            tag.casefold() in local_evidence
            for tag in plan.chunk_tags[chunk["chunk_id"]]
        )


def test_document_topics_are_only_attached_to_chunks_with_evidence():
    from raganything.services.auto_tagging import build_automatic_tag_plan

    plan = build_automatic_tag_plan(
        [
            {"chunk_id": "physics", "content": "量子纠缠实验验证了量子通信协议。"},
            {"chunk_id": "payroll", "content": "工资薪金核算包含社会保险与个人所得税。"},
        ],
        filename="量子纠缠研究.docx",
    )

    assert plan.document_tags
    assert all(
        tag in "量子纠缠实验验证了量子通信协议。"
        for tag in plan.document_tags_by_chunk["physics"]
    )
    assert not set(plan.document_tags_by_chunk["payroll"]).intersection(
        {"量子", "纠缠", "量子纠缠"}
    )
    assert plan.chunk_tags["payroll"]


def test_generic_academic_boilerplate_does_not_become_tags():
    from raganything.services.auto_tagging import build_automatic_tag_plan

    plan = build_automatic_tag_plan([
        {
            "chunk_id": "generic",
            "content": "本研究通过实验结果表明，系统实现了功能，提高了整体性能，具有重要意义。",
        }
    ])

    generated = set(plan.document_tags) | set(plan.chunk_tags["generic"])
    assert not generated.intersection(
        {"结果表明", "实验", "性能", "意义", "整体", "本研究", "实现", "功能"}
    )
