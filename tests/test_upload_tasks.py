import asyncio
from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile


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
