from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_fail_task_preserves_last_progress_context(monkeypatch):
    from raganything.services import state_service

    tasks = {
        "task-1": {
            "id": "task-1",
            "progress": 88,
            "phase": "graph",
            "phase_status": "extracting",
            "message": "43/44 chunks",
        }
    }
    monkeypatch.setattr(state_service, "processing_tasks", tasks)
    monkeypatch.setattr(state_service, "_task_pg_ready", lambda: False)

    await state_service.fail_task("task-1", "LLM timed out")

    task = tasks["task-1"]
    assert task["status"] == "failed"
    assert task["error"] == "LLM timed out"
    assert task["progress"] == 88
    assert task["phase"] == "graph"
    assert task["phase_status"] == "extracting"
    assert task["message"] == "43/44 chunks"


@pytest.mark.asyncio
async def test_defer_task_keeps_progress_and_marks_retryable(monkeypatch):
    from raganything.services import state_service

    tasks = {
        "task-1": {
            "id": "task-1",
            "status": "processing",
            "progress": 97,
            "phase": "tagging",
        }
    }
    monkeypatch.setattr(state_service, "processing_tasks", tasks)
    monkeypatch.setattr(state_service, "_task_pg_ready", lambda: False)

    await state_service.defer_task(
        "task-1", "tag queue unavailable", failure_stage="tagging",
    )

    assert tasks["task-1"]["status"] == "retry_wait"
    assert tasks["task-1"]["progress"] == 97
    assert tasks["task-1"]["failure_stage"] == "tagging"
    assert tasks["task-1"]["retryable"] is True


@pytest.mark.asyncio
async def test_complete_degraded_task_sets_explicit_outcome(monkeypatch):
    from raganything.services import state_service

    tasks = {"task-1": {"id": "task-1", "progress": 88, "phase": "graph"}}
    monkeypatch.setattr(state_service, "processing_tasks", tasks)
    monkeypatch.setattr(state_service, "_task_pg_ready", lambda: False)

    await state_service.complete_task(
        "task-1", outcome="degraded", warning="graph pending",
    )

    assert tasks["task-1"]["status"] == "completed"
    assert tasks["task-1"]["progress"] == 100
    assert tasks["task-1"]["outcome"] == "degraded"
    assert tasks["task-1"]["warning"] == "graph pending"


@pytest.mark.asyncio
async def test_fail_task_accepts_warning_message_and_ignores_late_progress(monkeypatch):
    from raganything.services import state_service

    tasks = {
        "task-1": {
            "id": "task-1",
            "status": "processing",
            "progress": 88,
            "phase": "graph",
            "message": "43/44 chunks",
        }
    }
    monkeypatch.setattr(state_service, "processing_tasks", tasks)
    monkeypatch.setattr(state_service, "_task_pg_ready", lambda: False)

    await state_service.fail_task(
        "task-1",
        "LLM timed out",
        outcome="terminal_failed",
        warning_message="manual retry required",
    )
    await state_service.update_task_progress(
        "task-1", 99, message="late worker update", phase="embedding",
    )

    task = tasks["task-1"]
    assert task["progress"] == 88
    assert task["phase"] == "graph"
    assert task["message"] == "43/44 chunks"
    assert task["outcome"] == "terminal_failed"
    assert task["warning_message"] == "manual retry required"


@pytest.mark.asyncio
async def test_pg_fail_task_updates_only_terminal_fields(monkeypatch):
    from raganything.services import pg_state_repo, state_service

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: Pool())

    await state_service._pg_fail_task(
        "task-1",
        "LLM timed out",
        outcome="failed",
        warning="retry later",
        failure_stage="tagging",
        retryable=False,
    )

    sql, args = calls[0]
    assignments = sql.split("WHERE", 1)[0]
    assert "progress=" not in assignments
    assert "phase=" not in assignments
    assert " message=" not in assignments
    assert "outcome=" in assignments
    assert "warning_message=" in assignments
    assert "failure_stage=" in assignments
    assert "retryable=" in assignments
    assert args == (
        "task-1", "LLM timed out", "failed", "retry later", "tagging", False,
    )


@pytest.mark.asyncio
async def test_upload_status_persists_degraded_outcome_columns(monkeypatch):
    from raganything.services import kb_service, pg_state_repo

    calls = []

    class Pool:
        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            return {
                "id": 1,
                "filename": "paper.docx",
                "file_path": "paper.docx",
                "file_hash": "hash-1",
                "file_size": 10,
                "kb_name": "demo",
                "uploaded_by": 7,
                "task_id": "task-1",
                "status": "completed",
                "error_message": "graph pending",
                "outcome": "degraded",
                "warning_message": "graph pending",
                "created_at": "2026-07-21T00:00:00Z",
                "updated_at": "2026-07-21T00:00:01Z",
            }

    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: Pool())
    monkeypatch.setattr(kb_service, "_uploaded_files_has_error_message", None)
    monkeypatch.setattr(kb_service, "_uploaded_files_has_terminal_metadata", None)

    result = await kb_service.pg_update_upload_status_by_task_id(
        "task-1",
        "completed",
        kb_name="demo",
        error_message="graph pending",
        outcome="degraded",
        warning_message="graph pending",
    )

    sql, args = calls[0]
    assert "outcome = COALESCE" in sql
    assert "warning_message = COALESCE" in sql
    assert args == (
        "completed",
        "graph pending",
        "degraded",
        "graph pending",
        "task-1",
        "demo",
    )
    assert result["outcome"] == "degraded"
    assert result["warning_message"] == "graph pending"


@pytest.mark.asyncio
async def test_degraded_document_requires_and_persists_all_text_chunks(monkeypatch):
    from raganything.services import document_quality, kb_service

    persisted = {}

    class DocStatus:
        async def upsert(self, records):
            persisted.update(records)

        async def index_done_callback(self):
            return None

    rag = SimpleNamespace(lightrag=SimpleNamespace(doc_status=DocStatus()))
    monkeypatch.setattr(kb_service, "kb_instances", {"demo": rag})

    async def chunks(_kb_name):
        return {
            "chunk-1": {"llm_cache_list": ["cache-1"]},
            "chunk-2": {"llm_cache_list": []},
        }

    monkeypatch.setattr(kb_service, "_load_text_chunks_json", chunks)
    async def ready_quality(*_args, **_kwargs):
        return {"ready": True}
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", ready_quality)
    info = {
        "status": "failed",
        "file_path": "paper.docx",
        "chunks_count": 2,
        "chunks_list": ["chunk-1", "chunk-2"],
        "metadata": {"retry_count": 1},
    }

    metadata = await kb_service._mark_degraded_document(
        "demo", "doc-1", info, error_message="request timed out",
    )

    assert metadata == persisted["doc-1"]["metadata"]
    assert persisted["doc-1"]["status"] == "failed"
    assert metadata["content_ready"] is True
    assert metadata["graph_status"] == "pending"
    assert metadata["failure_stage"] == "entity_extraction"
    assert metadata["retryable"] is True
    assert metadata["failed_chunk_ids"] == ["chunk-2"]
    assert metadata["retry_count"] == 1
    assert metadata["last_error"] == "request timed out"


@pytest.mark.asyncio
async def test_degraded_document_rejects_missing_text_chunk(monkeypatch):
    from raganything.services import kb_service

    async def chunks(_kb_name):
        return {"chunk-1": {"llm_cache_list": ["cache-1"]}}

    monkeypatch.setattr(kb_service, "_load_text_chunks_json", chunks)
    result = await kb_service._mark_degraded_document(
        "demo",
        "doc-1",
        {
            "status": "failed",
            "chunks_count": 2,
            "chunks_list": ["chunk-1", "chunk-2"],
        },
        error_message="request timed out",
    )

    assert result is None


@pytest.mark.asyncio
async def test_finalize_partial_upload_completes_with_degraded_outcome(monkeypatch):
    from raganything.services import document_tagging, kb_service, state_service, ws_service

    calls = []

    async def no_op(*_args, **_kwargs):
        return None

    async def find_degraded(*_args, **_kwargs):
        return "doc-1", {"content_ready": True}

    async def complete(task_id, **kwargs):
        calls.append(("complete", task_id, kwargs))

    async def fail(*_args, **_kwargs):
        raise AssertionError("partial upload must not be finalized as failed")

    async def update_upload(task_id, status, **kwargs):
        calls.append(("upload", task_id, status, kwargs))

    async def event(name, **kwargs):
        calls.append(("event", name, kwargs))

    async def enqueue(*_args, **_kwargs):
        return {"id": 1, "status": "queued"}

    async def wait(*_args, **_kwargs):
        return {"tag_status": "ready"}

    monkeypatch.setattr(kb_service, "_fix_stuck_doc_status", no_op)
    monkeypatch.setattr(kb_service, "_find_degraded_document", find_degraded)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update_upload)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(state_service, "complete_task", complete)
    monkeypatch.setattr(state_service, "fail_task", fail)
    monkeypatch.setattr(ws_service, "add_event", event)
    monkeypatch.setattr(document_tagging, "enqueue_document_tagging", enqueue)
    monkeypatch.setattr(document_tagging, "wait_for_document_tagging", wait)

    await kb_service._finalize_failed_upload(
        "task-1", "demo", "paper.docx", 7, "request timed out", "hash-1",
    )

    assert calls[0] == (
        "complete",
        "task-1",
        {"outcome": "degraded", "warning": "文本内容已入库，知识图谱抽取待补全"},
    )
    assert calls[1][0:2] == ("event", "upload_complete")
    assert calls[1][2]["outcome"] == "degraded"
    assert calls[2][0:3] == ("upload", "task-1", "completed")
    assert calls[2][3]["outcome"] == "degraded"
    assert calls[2][3]["warning_message"]


@pytest.mark.asyncio
async def test_doc_processor_persists_failed_chunk_metadata():
    from raganything.processor.doc_processor import DocProcessorMixin

    class DocStatusStore:
        def __init__(self):
            self.record = {
                "status": "failed",
                "file_path": "paper.docx",
                "chunks_count": 2,
                "chunks_list": ["chunk-1", "chunk-2"],
                "metadata": {},
            }

        async def get_by_id(self, _doc_id):
            return self.record

        async def upsert(self, records):
            self.record = records["doc-1"]

        async def index_done_callback(self):
            return None

    class TextChunks:
        async def get_by_ids(self, _ids):
            return [
                {"llm_cache_list": ["cache-1"]},
                {"llm_cache_list": []},
            ]

    class Processor(DocProcessorMixin):
        pass

    processor = Processor()
    processor.lightrag = SimpleNamespace(
        doc_status=DocStatusStore(), text_chunks=TextChunks(),
    )

    result = await processor._persist_degraded_graph_status(
        "doc-1", "paper.docx", TimeoutError("LLM timed out"),
    )

    metadata = processor.lightrag.doc_status.record["metadata"]
    assert result is True
    assert processor.lightrag.doc_status.record["status"].value == "failed"
    assert metadata["content_ready"] is True
    assert metadata["failed_chunk_ids"] == ["chunk-2"]
    assert metadata["retryable"] is True
