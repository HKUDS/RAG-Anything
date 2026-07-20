import asyncio
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile


def test_worker_subprocess_env_bounds_numeric_library_threads(monkeypatch):
    from raganything.services.kb_service import _worker_subprocess_env

    monkeypatch.setenv("DOCUMENT_WORKER_MAX_THREADS", "99")
    env = _worker_subprocess_env()
    assert {env[name] for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )} == {"4"}

    monkeypatch.setenv("DOCUMENT_WORKER_MAX_THREADS", "invalid")
    env = _worker_subprocess_env()
    assert env["OPENBLAS_NUM_THREADS"] == "1"


@pytest.mark.asyncio
async def test_deleted_upload_record_is_reused_by_new_registration(monkeypatch):
    import raganything.services.kb_service as kb_service

    now = datetime.now()
    captured = {}

    class FakePool:
        async def fetchrow(self, sql, *params):
            captured["sql"] = sql
            captured["params"] = params
            return {
                "id": 1,
                "filename": "report.docx",
                "file_path": "C:/uploads/report.docx",
                "file_hash": "hash-1",
                "file_size": 12,
                "kb_name": "demo-kb",
                "uploaded_by": 7,
                "task_id": "task-new",
                "status": "queued",
                "error_message": "",
                "created_at": now,
                "updated_at": now,
            }

    kb_service._uploaded_files_has_error_message = True
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: FakePool()
    )

    row = await kb_service.pg_register_upload(
        "report.docx", "C:/uploads/report.docx", "hash-1", 12,
        "demo-kb", 7, task_id="task-new",
    )

    assert row["task_id"] == "task-new"
    assert "ON CONFLICT (file_hash, kb_name) DO UPDATE" in captured["sql"]
    assert "WHERE uploaded_files.status = 'deleted'" in captured["sql"]


@pytest.mark.asyncio
async def test_upload_registration_reclaims_only_orphaned_terminal_metadata(monkeypatch):
    from raganything.routers import knowledge

    registrations = []

    async def fake_register(**kwargs):
        registrations.append(kwargs)
        return None if len(registrations) == 1 else {"id": 2, "status": "queued"}

    async def fake_no_document(_kb_name, _filename):
        return False

    reclaimed = []

    async def fake_reclaim(file_hash, kb_name):
        reclaimed.append((file_hash, kb_name))
        return True

    monkeypatch.setattr(knowledge, "pg_register_upload", fake_register)
    monkeypatch.setattr(knowledge, "_document_exists_for_upload_filename", fake_no_document)
    monkeypatch.setattr(knowledge, "pg_mark_upload_reusable", fake_reclaim)

    result = await knowledge._register_upload_with_stale_recovery(
        filename="report.docx",
        file_path="C:/uploads/report.docx",
        file_hash="hash-1",
        file_size=12,
        kb_name="demo-kb",
        uploaded_by=7,
        task_id="task-new",
    )

    assert result == {"id": 2, "status": "queued"}
    assert len(registrations) == 2
    assert reclaimed == [("hash-1", "demo-kb")]


@pytest.mark.asyncio
async def test_upload_registration_keeps_existing_document_deduplicated(monkeypatch):
    from raganything.routers import knowledge

    async def fake_register(**_kwargs):
        return None

    async def fake_document_exists(_kb_name, _filename):
        return True

    async def unexpected_reclaim(*_args):
        raise AssertionError("an existing document must not release its upload record")

    monkeypatch.setattr(knowledge, "pg_register_upload", fake_register)
    monkeypatch.setattr(knowledge, "_document_exists_for_upload_filename", fake_document_exists)
    monkeypatch.setattr(knowledge, "pg_mark_upload_reusable", unexpected_reclaim)

    result = await knowledge._register_upload_with_stale_recovery(
        filename="report.docx",
        file_path="C:/uploads/report.docx",
        file_hash="hash-1",
        file_size=12,
        kb_name="demo-kb",
        uploaded_by=7,
        task_id="task-new",
    )

    assert result is None


def test_parse_worker_progress_line_uses_text_and_multimodal_counts():
    from raganything.services.kb_service import _parse_worker_progress_line

    state = {}

    event = _parse_worker_progress_line(
        "[PROGRESS] phase=parsing status=start file=alpha.docx",
        state,
    )
    assert event["phase"] == "parsing"
    assert event["phase_status"] == "start"
    assert "progress" not in event

    event = _parse_worker_progress_line(
        "INFO: Parsing C:\\tmp\\alpha.docx complete! Extracted 52 content blocks",
        state,
    )
    assert event["progress"] == 25

    event = _parse_worker_progress_line(
        "INFO: Chunk 3 of 6 extracted 21 Ent + 19 Rel chunk-abc",
        state,
    )
    assert event["phase"] == "entity-extraction"
    assert 30 <= event["progress"] <= 70

    event = _parse_worker_progress_line(
        "INFO: Starting multimodal content processing...",
        state,
    )
    assert state["track"] == "multimodal"
    assert event["phase"] == "multimodal-tasks"
    assert event["progress"] == 90

    event = _parse_worker_progress_line(
        "INFO: Multimodal chunk generation progress: 2/3 (66.7%)",
        state,
    )
    assert event["phase"] == "multimodal-tasks"
    assert 91 <= event["progress"] <= 94

    event = _parse_worker_progress_line(
        "INFO: Chunk 2 of 3 extracted 5 Ent + 4 Rel chunk-def",
        state,
    )
    assert event["phase"] == "multimodal-tasks"
    assert 95 <= event["progress"] <= 97


def test_parse_worker_progress_line_maps_merge_milestones():
    from raganything.services.kb_service import _parse_worker_progress_line

    text_state = {"track": "text"}
    event = _parse_worker_progress_line(
        "INFO: Phase 2: Processing 19 relations from doc-123 (async: 14)",
        text_state,
    )
    assert event["phase"] == "graph-building"
    assert event["phase_status"] == "relations"
    assert event["progress"] == 82

    multimodal_state = {"track": "multimodal"}
    event = _parse_worker_progress_line(
        "INFO: Phase 3: Updating final 24(24+0) entities and 48 relations from doc-456",
        multimodal_state,
    )
    assert event["phase"] == "graph-building"
    assert event["phase_status"] == "finalizing"
    assert event["progress"] == 99


@pytest.mark.asyncio
async def test_list_upload_tasks_merges_runtime_status(monkeypatch):
    from raganything.routers.knowledge import list_upload_tasks

    uploads = [
        {
            "task_id": "task-processing",
            "filename": "alpha.pdf",
            "file_size": 2048,
            "status": "queued",
            "error_message": "",
            "created_at": "2026-07-08T10:00:00",
            "updated_at": "2026-07-08T10:01:00",
        },
        {
            "task_id": "task-completed",
            "filename": "beta.pdf",
            "file_size": 8192,
            "status": "completed",
            "error_message": "",
            "created_at": "2026-07-08T09:00:00",
            "updated_at": "2026-07-08T09:05:00",
        },
    ]

    async def fake_pg_list_uploads(**_kwargs):
        return uploads, len(uploads)

    async def fake_get_all_tasks():
        return [
            {
                "id": "task-processing",
                "kb": "demo-kb",
                "status": "processing",
                "progress": 42,
                "phase": "embedding",
                "updated_at": "2026-07-08T10:02:00",
            },
            {
                "id": "ignored-task",
                "kb": "other-kb",
                "status": "processing",
                "progress": 88,
            },
        ]

    monkeypatch.setattr("raganything.routers.knowledge.pg_list_uploads", fake_pg_list_uploads)
    monkeypatch.setattr("raganything.routers.knowledge.get_all_tasks", fake_get_all_tasks)

    result = await list_upload_tasks(
        kb="demo-kb",
        current_user={"id": 1, "is_admin": False},
    )

    assert result["total"] == 2
    assert result["tasks"][0]["task_id"] == "task-processing"
    assert result["tasks"][0]["status"] == "processing"
    assert result["tasks"][0]["progress"] == 42
    assert result["tasks"][0]["phase"] == "embedding"
    assert result["tasks"][0]["file_size"] == 2048
    assert result["tasks"][0]["can_delete"] is False
    assert result["tasks"][1]["task_id"] == "task-completed"
    assert result["tasks"][1]["status"] == "completed"
    assert result["tasks"][1]["progress"] == 100
    assert result["tasks"][1]["file_size"] == 8192
    assert result["tasks"][1]["can_delete"] is False


@pytest.mark.asyncio
async def test_delete_upload_task_deletes_queued_file(monkeypatch, tmp_path):
    from raganything.routers.knowledge import delete_upload_task

    staged_file = tmp_path / "queued.pdf"
    staged_file.write_text("queued", encoding="utf-8")

    upload = {
        "task_id": "task-queued",
        "filename": "queued.pdf",
        "status": "queued",
        "file_path": str(staged_file),
        "file_hash": "hash-1",
    }
    update_mock = AsyncMock(return_value={**upload, "status": "deleted"})
    delete_task_mock = AsyncMock()
    add_event_mock = AsyncMock()
    unregister_calls = []

    monkeypatch.setattr(
        "raganything.routers.knowledge.pg_get_upload_by_task_id",
        AsyncMock(return_value=upload),
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge.pg_update_upload_status_by_task_id",
        update_mock,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge.delete_task",
        delete_task_mock,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge.add_event",
        add_event_mock,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._unregister_processing_file",
        lambda kb_name, file_hash: unregister_calls.append((kb_name, file_hash)),
    )

    result = await delete_upload_task(
        task_id="task-queued",
        kb="demo-kb",
        current_user={"id": 7, "is_admin": False},
    )

    assert result["status"] == "deleted"
    assert not staged_file.exists()
    assert unregister_calls == [("demo-kb", "hash-1")]
    update_mock.assert_awaited_once_with(
        "task-queued",
        "deleted",
        kb_name="demo-kb",
        expected_current_status="queued",
        error_message="",
    )
    delete_task_mock.assert_awaited_once_with("task-queued")
    add_event_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_upload_task_rejects_non_queued(monkeypatch):
    from raganything.routers.knowledge import delete_upload_task

    monkeypatch.setattr(
        "raganything.routers.knowledge.pg_get_upload_by_task_id",
        AsyncMock(return_value={
            "task_id": "task-processing",
            "filename": "busy.pdf",
            "status": "processing",
            "file_path": "",
            "file_hash": "hash-2",
        }),
    )

    with pytest.raises(HTTPException) as exc:
        await delete_upload_task(
            task_id="task-processing",
            kb="demo-kb",
            current_user={"id": 3, "is_admin": False},
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_upload_files_all_skipped_returns_summary(monkeypatch, tmp_path):
    import raganything.routers.shared as shared
    from raganything.routers.knowledge import upload_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "raganything.routers.knowledge._compute_file_hash",
        lambda path: path,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._is_file_being_processed",
        lambda kb_name, file_hash: f"existing-{file_hash}",
    )

    queue = asyncio.Queue()

    async def fake_ensure_queue_draining(_kb_name):
        return queue, queue.qsize()

    monkeypatch.setattr(shared, "_ensure_queue_draining", fake_ensure_queue_draining)

    files = [
        UploadFile(filename="a.docx", file=BytesIO(b"a")),
        UploadFile(filename="b.docx", file=BytesIO(b"b")),
    ]
    endpoint = getattr(upload_files, "__wrapped__", upload_files)
    result = await endpoint(
        request=None,
        files=files,
        kb="demo-kb",
        current_user={"id": 1},
    )

    assert result["status"] == "skipped"
    assert result["tasks"] == []
    assert result["total"] == 0
    assert result["queue_size"] == 0
    assert result["skipped"] == ["a.docx", "b.docx"]
    assert "没有新任务入队" in result["message"]


@pytest.mark.asyncio
async def test_pg_list_uploads_falls_back_without_error_message_column(monkeypatch):
    import raganything.services.kb_service as kb_service

    class UndefinedColumnError(Exception):
        pass

    class FakeConn:
        def __init__(self):
            self.fetch_attempts = 0

        async def fetch(self, sql, *params):
            self.fetch_attempts += 1
            if self.fetch_attempts == 1:
                raise UndefinedColumnError('column "error_message" does not exist')
            now = datetime.now()
            return [{
                "id": 1,
                "filename": "alpha.pdf",
                "file_path": "/tmp/alpha.pdf",
                "file_hash": "hash-1",
                "file_size": 12,
                "kb_name": "demo-kb",
                "uploaded_by": 7,
                "task_id": "task-1",
                "status": "queued",
                "created_at": now,
                "updated_at": now,
            }]

        async def fetchrow(self, sql, *params):
            return {"total": 1}

    class FakeAcquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return FakeAcquire(self.conn)

    conn = FakeConn()
    kb_service._uploaded_files_has_error_message = None
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool",
        lambda: FakePool(conn),
    )

    uploads, total = await kb_service.pg_list_uploads(kb_name="demo-kb")

    assert total == 1
    assert uploads[0]["filename"] == "alpha.pdf"
    assert uploads[0]["error_message"] == ""
    assert kb_service._uploaded_files_has_error_message is False


@pytest.mark.asyncio
async def test_pg_content_updates_batch_uses_completed_and_deleted_rows(monkeypatch):
    import raganything.services.kb_service as kb_service

    captured = {}

    class FakePool:
        async def fetch(self, sql, *params):
            captured["sql"] = sql
            captured["params"] = params
            return [
                {"kb_name": "kb-a", "last_content_updated_at": datetime(2026, 7, 3, 9, 15)},
            ]

    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: FakePool(),
    )

    updates = await kb_service.pg_get_latest_content_updates_batch(["kb-a", "kb-a", "kb-b"])

    assert updates == {"kb-a": "2026-07-03T09:15:00"}
    assert "MAX(updated_at) AS last_content_updated_at" in captured["sql"]
    assert captured["params"] == (["kb-a", "kb-b"], ["completed", "deleted"])


@pytest.mark.asyncio
async def test_pg_content_updates_batch_fails_open(monkeypatch):
    import raganything.services.kb_service as kb_service

    class FailingPool:
        async def fetch(self, *_args):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: FailingPool(),
    )

    assert await kb_service.pg_get_latest_content_updates_batch(["kb-a"]) == {}


@pytest.mark.asyncio
async def test_list_kbs_embeds_latest_content_update_and_falls_back_to_created(monkeypatch):
    from raganything.routers import knowledge

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01T08:00:00", "owner_id": 1},
            "kb-b": {"name": "KB B", "created": "2026-07-02T08:00:00", "owner_id": 1},
            "kb-private": {"name": "Private", "created": "2026-07-04T08:00:00", "owner_id": 2},
        }

    async def fake_batch_stats(_names):
        return {}

    async def fake_content_updates(names):
        assert names == ["kb-a", "kb-b"]
        return {"kb-a": "2026-07-03T09:15:00+00:00"}

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", fake_batch_stats)
    monkeypatch.setattr(knowledge, "pg_get_latest_content_updates_batch", fake_content_updates)

    result = await knowledge.list_kbs(current_user={
        "id": 1, "username": "alice", "is_admin": False, "allowed_kbs": [],
    })

    updates = {
        kb["name"]: kb["last_content_updated_at"]
        for kb in result["knowledge_bases"]
    }
    assert updates == {
        "kb-a": "2026-07-03T09:15:00+00:00",
        "kb-b": "2026-07-02T08:00:00",
    }


@pytest.mark.asyncio
async def test_list_kbs_content_update_lookup_failure_keeps_created_fallback(monkeypatch):
    from raganything.routers import knowledge

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01T08:00:00", "owner_id": 1},
        }

    async def fail_content_updates(_names):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", lambda _names: {})
    monkeypatch.setattr(knowledge, "pg_get_latest_content_updates_batch", fail_content_updates)

    result = await knowledge.list_kbs(current_user={
        "id": 1, "username": "alice", "is_admin": False, "allowed_kbs": [],
    })

    assert result["knowledge_bases"][0]["last_content_updated_at"] == "2026-07-01T08:00:00"


@pytest.mark.asyncio
async def test_list_kbs_keeps_content_update_when_stats_batch_fails(monkeypatch):
    from raganything.routers import knowledge

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01T08:00:00", "owner_id": 1},
        }

    async def fail_stats(_names):
        raise RuntimeError("statistics unavailable")

    async def fake_content_updates(_names):
        return {"kb-a": "2026-07-03T09:15:00+00:00"}

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", fail_stats)
    monkeypatch.setattr(knowledge, "pg_get_latest_content_updates_batch", fake_content_updates)

    result = await knowledge.list_kbs(current_user={
        "id": 1, "username": "alice", "is_admin": False, "allowed_kbs": [],
    })

    kb = result["knowledge_bases"][0]
    assert kb["last_content_updated_at"] == "2026-07-03T09:15:00+00:00"
    assert kb["stats"]["unavailable"] is True


@pytest.mark.asyncio
async def test_verify_document_persisted_rejects_failed_status(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def fake_load_doc_status_json(_kb_name):
        return {
            "doc-1": {
                "file_path": "alpha.docx",
                "status": "failed",
                "chunks_count": 5,
            }
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_json", fake_load_doc_status_json)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)

    with pytest.raises(RuntimeError, match="status=failed"):
        await kb_service._verify_document_persisted("demo-kb", "alpha.docx")


@pytest.mark.asyncio
async def test_parser_stage_failure_creates_retryable_doc_status(monkeypatch):
    import raganything.services.kb_service as kb_service

    created = []

    async def fake_load_doc_status_json(_kb_name):
        return {}

    async def fake_persist(kb_name, filename, error_message, task_id):
        created.append((kb_name, filename, error_message, task_id))
        return "doc-failed-1"

    monkeypatch.setattr(kb_service, "_load_doc_status_json", fake_load_doc_status_json)
    monkeypatch.setattr(kb_service, "_persist_failed_doc_status", fake_persist)

    await kb_service._fix_stuck_doc_status(
        "demo-kb", "broken.pdf", "parser failed", "task-1"
    )

    assert created == [("demo-kb", "broken.pdf", "parser failed", "task-1")]


@pytest.mark.asyncio
async def test_failed_upload_persists_document_before_terminal_task(monkeypatch):
    from raganything.services import kb_service
    from raganything.services import state_service, ws_service

    calls = []

    async def fake_fix(kb_name, filename, error_message, task_id):
        calls.append(("document", kb_name, filename, error_message, task_id))

    async def fake_upsert(task_id, task_data):
        calls.append(("task", task_id, task_data))

    async def fake_event(event_name, **kwargs):
        calls.append(("event", event_name, kwargs))

    monkeypatch.setattr(kb_service, "_fix_stuck_doc_status", fake_fix)
    monkeypatch.setattr(state_service, "upsert_task_state", fake_upsert)
    monkeypatch.setattr(ws_service, "add_event", fake_event)

    await kb_service._finalize_failed_upload(
        "task-1", "demo-kb", "broken.pdf", 7, "parser failed", None
    )

    assert [call[0] for call in calls] == ["document", "task", "event"]
    assert calls[1][2]["status"] == "failed"
    assert calls[1][2]["error"] == "parser failed"


@pytest.mark.asyncio
async def test_retry_document_creates_visible_queued_task_and_resets_upload(monkeypatch, tmp_path):
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "broken.pdf").write_bytes(b"not-a-pdf")

    async def fake_doc_status(_kb_name):
        return {
            "doc-failed-1": {
                "file_path": "broken.pdf",
                "status": "failed",
                "chunks_count": 0,
            }
        }

    deleted = []

    class _DocStatus:
        async def delete(self, ids):
            deleted.extend(ids)

        async def index_done_callback(self):
            return None

    async def fake_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(doc_status=_DocStatus()))

    queue = asyncio.Queue()

    async def fake_queue(_kb_name):
        return queue, queue.qsize()

    state_calls = []
    upload_updates = []
    events = []

    async def fake_state(task_id, payload):
        state_calls.append((task_id, payload))

    async def fake_upload_update(*args, **kwargs):
        upload_updates.append((args, kwargs))
        return True

    async def fake_event(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(knowledge, "_load_doc_status_json", fake_doc_status)
    monkeypatch.setattr(knowledge, "get_kb", fake_kb)
    monkeypatch.setattr("raganything.routers.shared._ensure_queue_draining", fake_queue)
    monkeypatch.setattr(knowledge, "upsert_task_state", fake_state)
    monkeypatch.setattr(knowledge, "pg_update_upload_status", fake_upload_update)
    monkeypatch.setattr(knowledge, "_compute_file_hash", lambda _path: "hash-1")
    monkeypatch.setattr(knowledge, "add_event", fake_event)

    result = await knowledge.retry_document(
        "doc-failed-1", kb="demo-kb", current_user={"id": 7}
    )

    assert result["status"] == "queued"
    assert deleted == ["doc-failed-1"]
    assert state_calls[0][1]["status"] == "queued"
    assert state_calls[0][1]["phase"] == "queued"
    assert upload_updates[0][0][:3] == ("hash-1", "demo-kb", "queued")
    assert upload_updates[0][1]["task_id"] == result["task_id"]
    assert queue.get_nowait()["task_id"] == result["task_id"]
    assert events[0][0][0] == "upload_retry_queued"
