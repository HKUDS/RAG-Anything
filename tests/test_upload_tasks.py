import asyncio
from datetime import datetime
import inspect
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _task_settings_snapshot(monkeypatch):
    """Workers are snapshot-only; unit tests provide the queued PG snapshot."""
    from raganything.services import user_settings

    async def snapshot(_task_id):
        return {
            "revision": 1,
            "fingerprint": "test-settings-fingerprint",
            "settings": {"ingestion": {"chunking_strategy": "recursive", "enable_image": True, "enable_table": True, "enable_equation": True, "enable_video": False}},
        }

    monkeypatch.setattr(user_settings, "get_task_settings_snapshot", snapshot)


def test_upload_worker_accepts_queued_vision_metadata():
    from raganything.services import kb_service

    queued_task = {
        "task_id": "task-1",
        "file_path": "C:/uploads/report.docx",
        "filename": "report.docx",
        "kb_name": "demo",
        "chunking_strategy": "recursive",
        "user_id": 7,
        "vision_vlm_profile_id": "vlm-a",
        "vision_vlm_profile_fingerprint": "vlm-fingerprint",
        "settings_snapshot_id": "task-1",
    }

    bound = inspect.signature(kb_service._process_uploaded_file).bind(**queued_task)

    assert bound.arguments["vision_vlm_profile_id"] == "vlm-a"
    assert bound.arguments["vision_vlm_profile_fingerprint"] == "vlm-fingerprint"
    assert bound.arguments["settings_snapshot_id"] == "task-1"


def test_upload_queue_claim_owner_has_uuid_factory():
    from raganything.services import kb_service

    assert callable(kb_service.uuid.uuid4)


@pytest.mark.asyncio
async def test_retired_video_profile_is_terminal_and_never_retried(monkeypatch, tmp_path):
    from raganything.services import kb_service, state_service, ws_service

    file_path = tmp_path / "retired.mp4"
    file_path.write_bytes(b"video")
    calls = []

    class Stream:
        def __init__(self, lines):
            self._lines = iter(lines)

        async def readline(self):
            return next(self._lines, b"")

    class FailedWorker:
        returncode = 1
        stdout = Stream([
            'WORKER_ERROR_JSON {"stage":"video_profile","root_type":"RetiredVideoProfileError","failure_code":"video_profile_retired","retryable":false,"message":"请重新上传该视频"}\n'.encode("utf-8")
        ])
        stderr = Stream([])

        async def wait(self):
            return self.returncode

    async def no_op(*_args, **_kwargs):
        return None

    async def update_upload(*args, **kwargs):
        calls.append(("upload", args, kwargs))
        return {"task_id": args[0]}

    async def fail_task(*args, **kwargs):
        calls.append(("task", args, kwargs))

    async def event(*args, **kwargs):
        calls.append(("event", args, kwargs))

    async def fake_subprocess(*_args, **_kwargs):
        return FailedWorker()

    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update_upload)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(kb_service, "_finalize_failed_upload", AsyncMock())
    monkeypatch.setattr(state_service, "processing_tasks", {})
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "complete_task", no_op)
    monkeypatch.setattr(state_service, "fail_task", fail_task)
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", event)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)

    await kb_service._process_uploaded_file(
        "task-retired", str(file_path), "retired.mp4", kb_name="demo", user_id=7,
    )

    uploads = [call for call in calls if call[0] == "upload"]
    assert uploads == [
        (
            "upload",
            ("task-retired", "processing"),
            {"kb_name": "demo", "error_message": "", "claim_owner": None, "claim_generation": None},
        ),
        (
            "upload",
            ("task-retired", "failed"),
            {
                "kb_name": "demo",
                "error_message": "请重新上传该视频",
                "claim_owner": None,
                "claim_generation": None,
            },
        ),
    ]
    task_failure = next(call for call in calls if call[0] == "task")
    assert task_failure == (
        "task",
        ("task-retired", "请重新上传该视频"),
        {
            "failure_stage": "video_profile",
            "retryable": False,
        },
    )
    failure_event = next(
        call for call in calls
        if call[0] == "event" and call[1] == ("upload_error",)
    )
    assert failure_event[2]["failure_stage"] == "video_profile"
    kb_service._finalize_failed_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_keeps_task_pending_when_worker_survives_kill(monkeypatch):
    from raganything.services import kb_service

    class StuckProcess:
        returncode = None

        def __init__(self):
            self.signals = []
            self._never = asyncio.Event()

        def terminate(self):
            self.signals.append("terminate")

        def kill(self):
            self.signals.append("kill")

        async def wait(self):
            await self._never.wait()

    proc = StuckProcess()
    cleanup = AsyncMock()
    monkeypatch.setattr(kb_service, "_UPLOAD_CANCELLATION_WORKER_WAIT_SECONDS", 0.001)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {"demo": [(proc, "task-1")]})
    monkeypatch.setattr(kb_service, "_cleanup_cancelled_upload_document", cleanup)
    kb_service._upload_cancellation_tasks.clear()

    await kb_service._finish_upload_cancellation(
        {"task_id": "task-1", "file_hash": "hash-1"}, "demo"
    )

    assert proc.signals == ["terminate", "kill"]
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_content_upload_uses_a_persisted_snapshot_and_isolated_instance(monkeypatch):
    from raganything.routers import knowledge

    snapshots = []
    inserted = []
    finalized = []

    async def fake_snapshot(task_id, user_id, **overrides):
        snapshots.append((task_id, user_id, overrides))
        return SimpleNamespace(chunking_strategy="recursive")

    class IsolatedInstance:
        lightrag = None

        async def insert_content_list(self, content_list, **kwargs):
            inserted.append((content_list, kwargs))

        async def finalize_storages(self):
            finalized.append(True)

    async def fake_instance(task_id, kb):
        assert snapshots and task_id == snapshots[0][0]
        assert kb == "demo"
        return IsolatedInstance()

    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", fake_snapshot)
    monkeypatch.setattr(knowledge, "_get_snapshot_task_kb", fake_instance)

    result = await knowledge.upload_content(
        knowledge.PasteContentRequest(title="note", content="snapshot scoped"),
        kb="demo",
        current_user={"id": 9},
        chunking_strategy="recursive",
        enable_image="false",
    )

    assert result["status"] == "completed"
    assert snapshots[0][1] == 9
    assert snapshots[0][2]["enable_image"] == "false"
    assert inserted[0][1]["chunking_strategy"] == "recursive"
    assert finalized == [True]
from fastapi import HTTPException
from starlette.datastructures import UploadFile


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["maintenance-manual.pdf", "maintenance-manual.docx"])
async def test_uploaded_document_id_resolution_refreshes_stale_cache_for_all_formats(
    monkeypatch, filename,
):
    import raganything.services.kb_service as kb_service

    class RetirableCache(dict):
        async def retire(self, name, *, persist_vector_stores=True):
            assert persist_vector_stores is False
            self.pop(name, None)
            return True

    cache = RetirableCache(demo=object())
    calls = 0
    sleeps = []

    async def fake_verify(kb_name, persisted_filename):
        nonlocal calls
        calls += 1
        assert kb_name == "demo"
        assert persisted_filename == filename
        assert "demo" not in cache
        return None if calls == 1 else "doc-current"

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(kb_service, "kb_instances", cache)
    monkeypatch.setattr(kb_service, "_verify_document_persisted", fake_verify)
    monkeypatch.setattr(kb_service.asyncio, "sleep", fake_sleep)

    document_id = await kb_service._resolve_uploaded_document_id(
        "demo", filename, attempts=3, retry_delay=0.25,
    )

    assert document_id == "doc-current"
    assert calls == 2
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_uploaded_document_id_resolution_returns_pending_when_pg_stays_hidden(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def unavailable(_kb_name, _filename):
        raise kb_service.DocumentStatusPendingError("not visible")

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(kb_service, "kb_instances", {})
    monkeypatch.setattr(kb_service, "_verify_document_persisted", unavailable)
    monkeypatch.setattr(kb_service.asyncio, "sleep", fake_sleep)

    document_id = await kb_service._resolve_uploaded_document_id(
        "demo", "manual.pdf", attempts=2, retry_delay=0,
    )

    assert document_id is None
    assert sleeps == [0.0]


@pytest.mark.asyncio
async def test_verify_document_persisted_treats_empty_pg_status_as_pending(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def no_statuses(_kb_name):
        return {}

    monkeypatch.setattr(kb_service, "_load_doc_status_json", no_statuses)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    with pytest.raises(kb_service.DocumentStatusPendingError, match="暂时无数据"):
        await kb_service._verify_document_persisted("demo", "manual.pdf")


@pytest.mark.asyncio
async def test_verify_document_persisted_treats_pg_no_match_as_pending(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def existing_statuses(_kb_name):
        return {
            "doc-other": {
                "file_path": "other.pdf",
                "status": "processed",
                "chunks_count": 3,
            }
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_json", existing_statuses)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    with pytest.raises(kb_service.DocumentStatusPendingError, match="暂未找到"):
        await kb_service._verify_document_persisted("demo", "manual.pdf")


@pytest.mark.asyncio
async def test_uploaded_document_id_resolution_fails_fast_for_explicit_failure(monkeypatch):
    import raganything.services.kb_service as kb_service

    sleeps = []

    async def failed(_kb_name, _filename):
        raise kb_service.DocumentProcessingFailedError("status=failed")

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(kb_service, "kb_instances", {})
    monkeypatch.setattr(kb_service, "_verify_document_persisted", failed)
    monkeypatch.setattr(kb_service.asyncio, "sleep", fake_sleep)

    with pytest.raises(kb_service.DocumentProcessingFailedError, match="status=failed"):
        await kb_service._resolve_uploaded_document_id(
            "demo", "manual.pdf", attempts=5, retry_delay=1,
        )

    assert sleeps == []


@pytest.mark.asyncio
async def test_verify_document_persisted_rejects_terminal_zero_chunk_row(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def terminal_status(_kb_name):
        return {
            "doc-current": {
                "file_path": "manual.pdf",
                "status": "processed",
                "chunks_count": 0,
            }
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_json", terminal_status)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    with pytest.raises(kb_service.DocumentProcessingFailedError, match="chunks=0"):
        await kb_service._verify_document_persisted("demo", "manual.pdf")


@pytest.mark.asyncio
async def test_deferred_tag_generation_resolves_and_writes_tags(monkeypatch):
    import raganything.services.kb_service as kb_service

    generated = []

    async def fake_resolve(kb_name, filename, **kwargs):
        assert kwargs == {"attempts": 10, "retry_delay": 2.0}
        assert (kb_name, filename) == ("demo", "a1b2c3d4_manual.pdf")
        return "doc-current"

    async def fake_generate(kb_name, document_id, *, filename, user_id):
        generated.append((kb_name, document_id, filename, user_id))
        return {"chunk_source": "postgres", "assigned": 6}

    monkeypatch.setattr(kb_service, "_resolve_uploaded_document_id", fake_resolve)
    monkeypatch.setattr(kb_service, "_generate_uploaded_document_tags", fake_generate)

    await kb_service._retry_deferred_uploaded_document_tags(
        "demo",
        "a1b2c3d4_manual.pdf",
        display_filename="manual.pdf",
        user_id=7,
    )

    assert generated == [("demo", "doc-current", "manual.pdf", 7)]


@pytest.mark.asyncio
async def test_deferred_tag_task_is_tracked_until_completion(monkeypatch):
    import raganything.services.kb_service as kb_service

    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_retry(
        _kb_name, _persisted_filename, *, display_filename, user_id,
    ):
        assert user_id == 7
        assert display_filename == "manual.pdf"
        started.set()
        await release.wait()

    monkeypatch.setattr(
        kb_service, "_retry_deferred_uploaded_document_tags", fake_retry,
    )
    kb_service._deferred_auto_tag_tasks.clear()

    kb_service._schedule_deferred_uploaded_document_tags(
        "demo",
        "a1b2c3d4_manual.pdf",
        display_filename="manual.pdf",
        user_id=7,
    )
    await started.wait()
    assert len(kb_service._deferred_auto_tag_tasks) == 1

    task = next(iter(kb_service._deferred_auto_tag_tasks))
    release.set()
    await task
    await asyncio.sleep(0)

    assert kb_service._deferred_auto_tag_tasks == {}


@pytest.mark.asyncio
async def test_verify_document_persisted_prefers_newest_same_name_upload(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def duplicate_statuses(_kb_name):
        return {
            "doc-old": {
                "file_path": "11111111_manual.pdf",
                "status": "processed",
                "chunks_count": 2,
                "updated_at": "2026-07-19T10:00:00",
            },
            "doc-current": {
                "file_path": "22222222_manual.pdf",
                "status": "processed",
                "chunks_count": 3,
                "updated_at": "2026-07-20T10:00:00",
            },
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_json", duplicate_statuses)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    document_id = await kb_service._verify_document_persisted("demo", "manual.pdf")

    assert document_id == "doc-current"


@pytest.mark.asyncio
async def test_cancel_deferred_tag_tasks_only_cancels_requested_kb(monkeypatch):
    import raganything.services.kb_service as kb_service

    release = asyncio.Event()

    async def wait_forever():
        await release.wait()

    first = asyncio.create_task(wait_forever())
    second = asyncio.create_task(wait_forever())
    kb_service._deferred_auto_tag_tasks.clear()
    kb_service._deferred_auto_tag_tasks.update({first: "first", second: "second"})
    first.add_done_callback(
        lambda completed: kb_service._deferred_auto_tag_tasks.pop(completed, None)
    )
    second.add_done_callback(
        lambda completed: kb_service._deferred_auto_tag_tasks.pop(completed, None)
    )

    await kb_service._cancel_deferred_auto_tag_tasks("first")

    assert first.cancelled()
    assert not second.done()
    release.set()
    await second
    await asyncio.sleep(0)
    assert kb_service._deferred_auto_tag_tasks == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("display_filename", "persisted_filename"),
    [
        ("manual.pdf", "a1b2c3d4_manual.pdf"),
        ("manual.docx", "a1b2c3d4_manual.docx"),
    ],
)
async def test_successful_upload_stays_completed_when_document_id_is_deferred(
    monkeypatch, tmp_path, display_filename, persisted_filename,
):
    import raganything.services.kb_service as kb_service
    import raganything.services.state_service as state_service
    import raganything.services.ws_service as ws_service

    file_path = tmp_path / persisted_filename
    file_path.write_bytes(b"document")
    pg_statuses = []
    completed = []
    finalized = []

    class EmptyStream:
        async def readline(self):
            return b""

    class SuccessfulWorker:
        returncode = 0
        stdout = EmptyStream()
        stderr = EmptyStream()

        async def wait(self):
            return 0

    subprocess_args = []

    async def fake_subprocess(*args, **_kwargs):
        subprocess_args.extend(args)
        return SuccessfulWorker()

    async def fake_pg_status(_task_id, status, **_kwargs):
        pg_statuses.append(status)

    async def fake_resolve(kb_name, filename, **_kwargs):
        assert (kb_name, filename) == ("demo", persisted_filename)
        return None

    async def fake_complete(task_id):
        completed.append(task_id)

    async def no_op(*_args, **_kwargs):
        return None

    async def fake_finalize(*args, **_kwargs):
        finalized.append((args, _kwargs))

    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", fake_pg_status)
    monkeypatch.setattr(kb_service, "_resolve_uploaded_document_id", fake_resolve)
    monkeypatch.setattr(kb_service, "_finalize_failed_upload", fake_finalize)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(state_service, "processing_tasks", {"task-current": {}})
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "complete_task", fake_complete)
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", no_op)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)

    await kb_service._process_uploaded_file(
        "task-current",
        str(file_path),
        display_filename,
        kb_name="demo",
        user_id=7,
    )

    assert completed == []
    assert pg_statuses == ["processing"]
    assert "不能确认自动标签是否完成" in finalized[0][0][4]
    assert "--task-id" in subprocess_args
    assert not {"--strategy", "--enable-image", "--enable-table", "--enable-equation", "--enable-video"} & set(subprocess_args)


@pytest.mark.asyncio
async def test_terminal_tag_failure_bypasses_generic_worker_failure_finalizer(
    monkeypatch, tmp_path,
):
    import raganything.services.document_tagging as document_tagging
    import raganything.services.kb_service as kb_service
    import raganything.services.state_service as state_service
    import raganything.services.ws_service as ws_service

    file_path = tmp_path / "manual.pdf"
    file_path.write_bytes(b"document")
    tag_failures = []
    generic_failures = []

    class EmptyStream:
        async def readline(self):
            return b""

    class SuccessfulWorker:
        returncode = 0
        stdout = EmptyStream()
        stderr = EmptyStream()

        async def wait(self):
            return 0

    async def fake_subprocess(*_args, **_kwargs):
        return SuccessfulWorker()

    async def resolve(*_args, **_kwargs):
        return "doc-1"

    async def enqueue(*_args, **_kwargs):
        return {"id": 1, "status": "queued"}

    async def wait(*_args, **_kwargs):
        return {
            "tag_status": "failed",
            "tag_error_message": "tagging attempts exhausted",
        }

    async def finalize_tagging(*args, **kwargs):
        tag_failures.append((args, kwargs))

    async def finalize_generic(*args, **kwargs):
        generic_failures.append((args, kwargs))

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", no_op)
    monkeypatch.setattr(kb_service, "_resolve_uploaded_document_id", resolve)
    monkeypatch.setattr(kb_service, "_finalize_tagging_failure", finalize_tagging)
    monkeypatch.setattr(kb_service, "_finalize_failed_upload", finalize_generic)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(document_tagging, "enqueue_document_tagging", enqueue)
    monkeypatch.setattr(document_tagging, "wait_for_document_tagging", wait)
    monkeypatch.setattr(state_service, "processing_tasks", {"task-current": {}})
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "complete_task", no_op)
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", no_op)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)

    await kb_service._process_uploaded_file(
        "task-current",
        str(file_path),
        "manual.pdf",
        kb_name="demo",
        user_id=7,
    )

    assert len(tag_failures) == 1
    assert tag_failures[0][0][4:6] == ("doc-1", "tagging attempts exhausted")
    assert generic_failures == []


@pytest.mark.asyncio
async def test_tag_enqueue_failure_stays_recoverable_and_nonterminal(
    monkeypatch, tmp_path,
):
    import raganything.services.document_tagging as document_tagging
    import raganything.services.kb_service as kb_service
    import raganything.services.state_service as state_service
    import raganything.services.ws_service as ws_service

    file_path = tmp_path / "manual.pdf"
    file_path.write_bytes(b"document")
    deferred = []
    terminal = []
    generic = []

    class EmptyStream:
        async def readline(self):
            return b""

    class SuccessfulWorker:
        returncode = 0
        stdout = EmptyStream()
        stderr = EmptyStream()

        async def wait(self):
            return 0

    async def fake_subprocess(*_args, **_kwargs):
        return SuccessfulWorker()

    async def resolve(*_args, **_kwargs):
        return "doc-1"

    async def enqueue(*_args, **_kwargs):
        raise ConnectionError("tag queue database unavailable")

    async def defer(*args, **kwargs):
        deferred.append((args, kwargs))

    async def finalize_tag(*args, **kwargs):
        terminal.append((args, kwargs))

    async def finalize_generic(*args, **kwargs):
        generic.append((args, kwargs))

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", no_op)
    monkeypatch.setattr(kb_service, "_resolve_uploaded_document_id", resolve)
    monkeypatch.setattr(kb_service, "_defer_tagging_schedule", defer)
    monkeypatch.setattr(kb_service, "_finalize_tagging_failure", finalize_tag)
    monkeypatch.setattr(kb_service, "_finalize_failed_upload", finalize_generic)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(document_tagging, "enqueue_document_tagging", enqueue)
    monkeypatch.setattr(state_service, "processing_tasks", {"task-current": {}})
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "complete_task", no_op)
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", no_op)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)

    await kb_service._process_uploaded_file(
        "task-current",
        str(file_path),
        "manual.pdf",
        kb_name="demo",
        user_id=7,
    )

    assert len(deferred) == 1
    assert deferred[0][0][3] == "doc-1"
    assert "暂时无法入队" in deferred[0][0][4]
    assert terminal == []
    assert generic == []


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
        def acquire(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def transaction(self):
            return self

        async def execute(self, _sql, *_params):
            return "SELECT 1"

        async def fetchval(self, _sql, *_params):
            return False

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


def test_parse_worker_progress_line_accepts_namespaced_phase_for_watchdog():
    from raganything.services.kb_service import _parse_worker_progress_line

    state = {"track": "text"}
    event = _parse_worker_progress_line(
        "[PROGRESS] phase=multimodal-tasks/graph-building "
        "status=relations file=manual.pdf",
        state,
    )

    assert event["phase"] == "multimodal-tasks/graph-building"
    assert event["phase_status"] == "relations"
    assert event["progress"] == 97
    assert state["track"] == "multimodal"


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
            "outcome": "degraded",
            "warning_message": "graph pending",
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
    assert result["tasks"][0]["can_delete"] is True
    assert result["tasks"][1]["task_id"] == "task-completed"
    assert result["tasks"][1]["status"] == "completed"
    assert result["tasks"][1]["progress"] == 100
    assert result["tasks"][1]["file_size"] == 8192
    assert result["tasks"][1]["outcome"] == "degraded"
    assert result["tasks"][1]["warning_message"] == "graph pending"
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
async def test_delete_upload_task_accepts_processing_cancellation(monkeypatch):
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

    cancel = AsyncMock(return_value={"status": "cancelling"})
    monkeypatch.setattr("raganything.routers.knowledge.cancel_inflight_upload", cancel)

    result = await delete_upload_task(
        task_id="task-processing",
        kb="demo-kb",
        current_user={"id": 3, "is_admin": False},
    )

    assert result.status_code == 202
    cancel.assert_awaited_once_with("task-processing", "demo-kb")


@pytest.mark.asyncio
async def test_list_upload_tasks_marks_retry_wait_cancellable_and_cancelling_locked(monkeypatch):
    from raganything.routers.knowledge import list_upload_tasks

    async def uploads(**_kwargs):
        return ([
            {"task_id": "retry", "filename": "retry.pdf", "status": "retry_wait", "created_at": "", "updated_at": ""},
            {"task_id": "stopping", "filename": "stopping.pdf", "status": "cancelling", "created_at": "", "updated_at": ""},
        ], 2)

    async def tasks():
        return [{"id": "stopping", "kb": "demo-kb", "status": "processing"}]

    monkeypatch.setattr("raganything.routers.knowledge.pg_list_uploads", uploads)
    monkeypatch.setattr("raganything.routers.knowledge.get_all_tasks", tasks)
    monkeypatch.setattr(
        "raganything.routers.knowledge.cancel_inflight_upload",
        AsyncMock(return_value={"status": "cancelling"}),
    )
    result = await list_upload_tasks(kb="demo-kb", current_user={"id": 1, "is_admin": False})

    assert [(task["status"], task["can_delete"]) for task in result["tasks"]] == [
        ("retry_wait", True), ("cancelling", False)
    ]


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
    monkeypatch.setattr(
        "raganything.routers.knowledge._resolve_upload_vlm_snapshot",
        AsyncMock(return_value=SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )),
    )

    queue = asyncio.Queue()

    enqueued = []

    async def fake_enqueue(task_info):
        enqueued.append(task_info)
        queue.put_nowait(task_info)
        return queue, queue.qsize() - 1

    monkeypatch.setattr(shared, "_enqueue_upload_task", fake_enqueue)

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
    assert result["skipped_details"] == [
        {"filename": "a.docx", "file_index": 0},
        {"filename": "b.docx", "file_index": 1},
    ]
    assert not list((tmp_path / "uploads").iterdir())
    assert "没有新任务入队" in result["message"]


@pytest.mark.asyncio
async def test_upload_files_continues_after_snapshot_failure(monkeypatch, tmp_path):
    import raganything.routers.shared as shared
    from raganything.routers.knowledge import upload_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "raganything.routers.knowledge._resolve_upload_vlm_snapshot",
        AsyncMock(return_value=SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )),
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._is_file_being_processed",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._register_upload_with_stale_recovery",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._register_processing_file",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "raganything.routers.knowledge._delete_upload_settings_snapshot",
        AsyncMock(),
    )

    calls = 0

    async def snapshot(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("settings unavailable")
        return SimpleNamespace(
            chunking_strategy="recursive",
            enable_image=True,
            enable_table=True,
            enable_equation=True,
            enable_video=True,
        )

    monkeypatch.setattr(
        "raganything.routers.knowledge._create_upload_settings_snapshot", snapshot
    )
    queue = asyncio.Queue()

    enqueued = []

    async def fake_enqueue(task_info):
        enqueued.append(task_info)
        queue.put_nowait(task_info)
        return queue, queue.qsize() - 1

    monkeypatch.setattr(shared, "_enqueue_upload_task", fake_enqueue)
    endpoint = getattr(upload_files, "__wrapped__", upload_files)
    result = await endpoint(
        request=None,
        files=[
            UploadFile(filename="first.mp4", file=BytesIO(b"first")),
            UploadFile(filename="second.mp4", file=BytesIO(b"second")),
        ],
        kb="demo-kb",
        current_user={"id": 1},
    )

    assert result["status"] == "queued"
    assert [task["filename"] for task in result["tasks"]] == ["second.mp4"]
    assert result["errors"] == [{
        "filename": "first.mp4",
        "file_index": 0,
        "code": "settings_snapshot_unavailable",
        "message": "无法创建任务设置快照",
    }]
    assert queue.qsize() == 1
    assert [task["filename"] for task in enqueued] == ["second.mp4"]
    assert result["tasks"][0]["file_index"] == 1


@pytest.mark.asyncio
async def test_batch_registration_failure_is_not_reported_as_a_duplicate_skip(monkeypatch, tmp_path):
    import raganything.routers.shared as shared
    from raganything.routers.knowledge import upload_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "raganything.routers.knowledge._resolve_upload_vlm_snapshot",
        AsyncMock(return_value=SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )),
    )
    monkeypatch.setattr("raganything.routers.knowledge._is_file_being_processed", lambda *_args: None)
    monkeypatch.setattr("raganything.routers.knowledge._register_upload_with_stale_recovery", AsyncMock(return_value=None))
    monkeypatch.setattr("raganything.routers.knowledge._delete_upload_settings_snapshot", AsyncMock())
    monkeypatch.setattr(
        "raganything.routers.knowledge._create_upload_settings_snapshot",
        AsyncMock(return_value=SimpleNamespace(
            chunking_strategy="recursive", enable_image=True, enable_table=True,
            enable_equation=True, enable_video=True,
        )),
    )

    async def unexpected_enqueue(_task):
        raise AssertionError("a failed registration must not enter the queue")

    monkeypatch.setattr(shared, "_enqueue_upload_task", unexpected_enqueue)
    endpoint = getattr(upload_files, "__wrapped__", upload_files)
    result = await endpoint(
        request=None,
        files=[UploadFile(filename="battery.mp4", file=BytesIO(b"content"))],
        kb="demo-kb",
        current_user={"id": 1},
    )

    assert result["status"] == "skipped"
    assert "skipped" not in result
    assert result["errors"] == [{
        "filename": "battery.mp4",
        "file_index": 0,
        "code": "upload_registration_failed",
        "message": "文件内容已存在或上传注册暂不可用，请稍后重试",
    }]
    assert not list((tmp_path / "uploads").iterdir())


def test_staged_upload_paths_are_unique_for_duplicate_batch_filenames(tmp_path):
    from raganything.routers.knowledge import _staged_upload_path, _strip_hash_prefix

    first = _staged_upload_path(tmp_path, "a1b2c3d4-0000-0000-0000-000000000000", "lesson.mp4")
    second = _staged_upload_path(tmp_path, "e5f60708-0000-0000-0000-000000000000", "lesson.mp4")

    assert first != second
    assert first.name == "a1b2c3d4000000000000000000000000_lesson.mp4"
    assert second.name == "e5f60708000000000000000000000000_lesson.mp4"
    assert _strip_hash_prefix(first.name) == "lesson.mp4"


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
async def test_pg_content_updates_batch_uses_monotonic_kb_revision(monkeypatch):
    import raganything.services.kb_service as kb_service

    captured = {}

    class FakePool:
        async def fetch(self, sql, *params):
            captured["sql"] = sql
            captured["params"] = params
            return [
                {"kb_name": "kb-a", "corpus_revision": 12},
            ]

    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool", lambda: FakePool(),
    )

    updates = await kb_service.pg_get_latest_content_updates_batch(["kb-a", "kb-a", "kb-b"])

    assert updates == {"kb-a": "12"}
    assert "FROM kb_metadata" in captured["sql"]
    assert captured["params"] == (["kb-a", "kb-b"],)


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
async def test_list_kbs_embeds_updated_at_and_falls_back_to_created(monkeypatch):
    from raganything.routers import knowledge

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01T08:00:00",
                     "updated_at": "2026-07-03T09:15:00+00:00", "owner_id": 1},
            "kb-b": {"name": "KB B", "created": "2026-07-02T08:00:00", "owner_id": 1},
            "kb-private": {"name": "Private", "created": "2026-07-04T08:00:00", "owner_id": 2},
        }

    async def fake_batch_stats(_names):
        return {}

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", fake_batch_stats)

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
async def test_list_kbs_empty_stats_still_returns_created_fallback(monkeypatch):
    from raganything.routers import knowledge

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01T08:00:00", "owner_id": 1},
        }

    async def fake_batch_stats(_names):
        return {}

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", fake_batch_stats)

    result = await knowledge.list_kbs(current_user={
        "id": 1, "username": "alice", "is_admin": False, "allowed_kbs": [],
    })

    kb = result["knowledge_bases"][0]
    assert kb["last_content_updated_at"] == "2026-07-01T08:00:00"
    assert kb["stats"]["unavailable"] is True


@pytest.mark.asyncio
async def test_list_kbs_stats_batch_failure_returns_list_with_unavailable_stats(monkeypatch):
    from raganything.routers import knowledge

    async def fake_load_kb_meta():
        return {
            "kb-a": {"name": "KB A", "created": "2026-07-01T08:00:00",
                     "updated_at": "2026-07-03T09:15:00+00:00", "owner_id": 1},
        }

    async def fail_stats(_names):
        raise RuntimeError("statistics unavailable")

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "_compute_kb_stats_batch_fast", fail_stats)

    result = await knowledge.list_kbs(current_user={
        "id": 1, "username": "alice", "is_admin": False, "allowed_kbs": [],
    })

    kb = result["knowledge_bases"][0]
    assert kb["last_content_updated_at"] == "2026-07-03T09:15:00+00:00"
    assert kb["stats"]["unavailable"] is True
    assert kb["stats"]["documents"] == 0


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
async def test_fix_stuck_status_does_not_rewrite_processed_exact_filename(monkeypatch):
    import raganything.services.kb_service as kb_service

    saved = []

    async def load(_kb_name):
        return {
            "doc-1": {
                "file_path": "manual.pdf",
                "status": "processed",
                "chunks_count": 2,
                "chunks_list": ["chunk-1", "chunk-2"],
            }
        }

    async def save(_kb_name, data):
        saved.append(data)

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load)
    monkeypatch.setattr(kb_service, "_save_doc_status_json", save)

    await kb_service._fix_stuck_doc_status(
        "demo-kb", "manual.pdf", "tagging failed", "task-1",
    )

    assert saved == []


@pytest.mark.asyncio
async def test_fix_stuck_status_does_not_claim_unscoped_failed_residue(monkeypatch):
    import raganything.services.kb_service as kb_service

    status = {
        "doc-old": {
            "file_path": "manual.pdf",
            "status": "failed",
            "chunks_count": 744,
            "metadata": {"cleanup_pending": True, "residual_data": True},
        }
    }
    saved = []

    async def load(_kb_name):
        return status

    async def save(_kb_name, data):
        saved.append(data)

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load)
    monkeypatch.setattr(kb_service, "_save_doc_status_json", save)

    await kb_service._fix_stuck_doc_status(
        "demo-kb", "manual.pdf", "worker timeout", "new-task", file_hash="new-hash"
    )

    assert saved == []
    assert status["doc-old"]["metadata"] == {
        "cleanup_pending": True,
        "residual_data": True,
    }


@pytest.mark.asyncio
async def test_fix_stuck_status_skips_ambiguous_unscoped_active_rows(monkeypatch):
    import raganything.services.kb_service as kb_service

    status = {
        "doc-unscoped": {"file_path": "manual.pdf", "status": "handling"},
        "doc-scoped": {
            "file_path": "manual.pdf",
            "status": "processing",
            "track_id": "other-task",
        },
    }
    saved = []

    async def load(_kb_name):
        return status

    async def save(_kb_name, data):
        saved.append(data)

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load)
    monkeypatch.setattr(kb_service, "_save_doc_status_json", save)

    await kb_service._fix_stuck_doc_status(
        "demo-kb", "manual.pdf", "worker timeout", "new-task", file_hash="new-hash"
    )

    assert saved == []
    assert status["doc-unscoped"]["status"] == "handling"
    assert status["doc-scoped"]["status"] == "processing"


@pytest.mark.asyncio
async def test_find_degraded_document_requires_current_upload_provenance(monkeypatch):
    import raganything.services.kb_service as kb_service

    async def load(_kb_name):
        return {
            "doc-old": {
                "file_path": "manual.pdf",
                "status": "failed",
                "metadata": {"content_ready": True},
            },
            "doc-current": {
                "file_path": "a1b2c3d4_manual.pdf",
                "status": "failed",
                "track_id": "task-current",
                "metadata": {
                    "task_id": "task-current",
                    "file_hash": "hash-current",
                    "content_ready": True,
                },
            },
        }

    called = []

    async def mark(_kb_name, doc_id, _info, *, error_message):
        called.append((doc_id, error_message))
        return {"content_ready": True}

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load)
    monkeypatch.setattr(kb_service, "_mark_degraded_document", mark)

    result = await kb_service._find_degraded_document(
        "demo-kb",
        "manual.pdf",
        "worker timeout",
        task_id="task-current",
        file_hash="hash-current",
    )

    assert result == ("doc-current", {"content_ready": True})
    assert called == [("doc-current", "worker timeout")]


@pytest.mark.asyncio
async def test_finalize_tagging_failure_preserves_document_and_marks_task(monkeypatch):
    from raganything.services import kb_service, state_service, ws_service

    calls = []

    async def fail(task_id, error, **kwargs):
        calls.append(("task", task_id, error, kwargs))

    async def event(name, **kwargs):
        calls.append(("event", name, kwargs))

    async def broadcast(payload):
        calls.append(("broadcast", payload))

    async def update(task_id, status, **kwargs):
        calls.append(("upload", task_id, status, kwargs))

    monkeypatch.setattr(state_service, "fail_task", fail)
    monkeypatch.setattr(ws_service, "add_event", event)
    monkeypatch.setattr(ws_service, "ws_broadcast", broadcast)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *args: calls.append(("unregister", args)))

    await kb_service._finalize_tagging_failure(
        "task-1",
        "demo-kb",
        "manual.pdf",
        7,
        "doc-1",
        "automatic tagging did not complete",
        "hash-1",
    )

    assert calls[0] == (
        "upload",
        "task-1",
        "failed",
        {"kb_name": "demo-kb", "error_message": "automatic tagging did not complete", "outcome": "terminal_failed", "claim_owner": None, "claim_generation": None},
    )
    assert calls[1] == (
        "task",
        "task-1",
        "automatic tagging did not complete",
        {"outcome": "terminal_failed", "failure_stage": "tagging", "retryable": False},
    )
    assert calls[2][0:2] == ("event", "upload_error")
    assert calls[2][2]["doc_id"] == "doc-1"
    assert calls[2][2]["failure_stage"] == "tagging"
    assert calls[3][0] == "broadcast"
    assert calls[4] == ("unregister", ("demo-kb", "hash-1"))


@pytest.mark.asyncio
async def test_failed_upload_persists_document_before_terminal_task(monkeypatch):
    from raganything.services import kb_service
    from raganything.services import state_service, ws_service

    calls = []

    async def fake_fix(kb_name, filename, error_message, task_id, *provenance):
        calls.append((
            "document", kb_name, filename, error_message, task_id, provenance,
        ))

    async def fake_fail(task_id, error, **kwargs):
        calls.append(("task", task_id, {"status": "failed", "error": error, **kwargs}))

    async def fake_event(event_name, **kwargs):
        calls.append(("event", event_name, kwargs))

    async def no_degraded_document(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kb_service, "_fix_stuck_doc_status", fake_fix)
    monkeypatch.setattr(kb_service, "_find_degraded_document", no_degraded_document)
    async def fake_upload_status(*_args, **_kwargs):
        return {"status": "failed"}

    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", fake_upload_status)
    monkeypatch.setattr(state_service, "fail_task", fake_fail)
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

    async def fake_queue(task_info):
        queue.put_nowait(task_info)
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

    snapshots = []

    async def fake_snapshot(task_id, user_id, **kwargs):
        snapshots.append((task_id, user_id, kwargs))

    monkeypatch.setattr(knowledge, "_load_doc_status_json", fake_doc_status)
    monkeypatch.setattr(knowledge, "get_kb", fake_kb)
    monkeypatch.setattr("raganything.routers.shared._enqueue_upload_task", fake_queue)
    monkeypatch.setattr(knowledge, "upsert_task_state", fake_state)
    monkeypatch.setattr(knowledge, "pg_update_upload_status", fake_upload_update)
    monkeypatch.setattr(knowledge, "_compute_file_hash", lambda _path: "hash-1")
    monkeypatch.setattr(knowledge, "add_event", fake_event)
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", fake_snapshot)
    monkeypatch.setattr(
        knowledge,
        "_resolve_upload_vlm_snapshot",
        AsyncMock(return_value=SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )),
    )

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
    assert snapshots == [(result["task_id"], 7, {"chunking_strategy": "recursive"})]


@pytest.mark.asyncio
async def test_completed_task_clears_recoverable_failure_fields(monkeypatch):
    from raganything.services import state_service

    task_id = "task-recovered"
    monkeypatch.setattr(state_service, "_task_pg_ready", lambda: False)
    monkeypatch.setattr(state_service, "processing_tasks", {
        task_id: {
            "status": "retry_wait",
            "progress": 97,
            "error": "temporary tag queue outage",
            "error_message": "temporary tag queue outage",
            "failure_stage": "tagging",
            "retryable": True,
        }
    })

    await state_service.complete_task(task_id)

    task = state_service.processing_tasks[task_id]
    assert task["status"] == "completed"
    assert task["progress"] == 100
    assert task["error_message"] == ""
    assert task["failure_stage"] == ""
    assert task["retryable"] is False


@pytest.mark.asyncio
async def test_degraded_graph_upload_waits_for_linked_tag_job(monkeypatch):
    from raganything.services import document_tagging, kb_service, state_service, ws_service

    calls = []

    async def no_op(*_args, **_kwargs):
        return None

    async def degraded(*_args, **_kwargs):
        return "doc-1", {"retryable": False}

    async def enqueue(*args, **kwargs):
        calls.append(("enqueue", args, kwargs))
        return {"id": 3, "status": "queued"}

    async def wait(*args, **kwargs):
        calls.append(("wait", args, kwargs))
        return {"tag_status": "ready"}

    async def complete(task_id, **kwargs):
        calls.append(("complete", task_id, kwargs))

    async def event(*args, **kwargs):
        calls.append(("event", args, kwargs))

    async def update(*args, **kwargs):
        calls.append(("upload", args, kwargs))

    monkeypatch.setattr(kb_service, "_fix_stuck_doc_status", no_op)
    monkeypatch.setattr(kb_service, "_find_degraded_document", degraded)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)
    monkeypatch.setattr(kb_service, "bump_kb_corpus_revision", no_op)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *args: calls.append(("unregister", args)))
    monkeypatch.setattr(document_tagging, "enqueue_document_tagging", enqueue)
    monkeypatch.setattr(document_tagging, "wait_for_document_tagging", wait)
    monkeypatch.setattr(state_service, "complete_task", complete)
    monkeypatch.setattr(ws_service, "add_event", event)

    await kb_service._finalize_failed_upload(
        "task-1", "demo", "manual.pdf", 7, "graph timeout", "hash-1",
    )

    assert calls[0] == (
        "enqueue",
        ("demo", "doc-1"),
        {"filename": "manual.pdf", "user_id": 7, "task_id": "task-1"},
    )
    assert calls[1][0] == "wait"
    assert next(call for call in calls if call[0] == "complete") == (
        "complete", "task-1", {"outcome": "degraded", "warning": "文本内容已入库，知识图谱抽取待补全"},
    )
    assert calls[-1] == ("unregister", ("demo", "hash-1"))


@pytest.mark.asyncio
async def test_worker_watchdog_refreshes_on_progress(monkeypatch):
    import asyncio
    import time
    from raganything.services import kb_service

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.finished = asyncio.Event()

        async def wait(self):
            await self.finished.wait()
            return self.returncode

        def finish(self):
            self.returncode = 0
            self.finished.set()

    process = FakeProcess()
    progress_event = asyncio.Event()
    state = {"last_progress_at": time.monotonic()}

    async def emit_progress_then_finish():
        await asyncio.sleep(0.05)
        state["last_progress_at"] = time.monotonic()
        progress_event.set()
        await asyncio.sleep(0.05)
        process.finish()

    producer = asyncio.create_task(emit_progress_then_finish())
    await kb_service._wait_for_worker_with_watchdog(
        process, progress_event, state, idle_timeout=0.2, max_elapsed=1.0,
    )
    await producer
    assert process.returncode == 0
    assert "watchdog_timeout" not in state


@pytest.mark.asyncio
async def test_worker_watchdog_times_out_without_progress():
    import asyncio
    import time
    from raganything.services import kb_service

    class FakeProcess:
        returncode = None

        async def wait(self):
            await asyncio.Event().wait()

    state = {"last_progress_at": time.monotonic()}
    with pytest.raises(asyncio.TimeoutError):
        await kb_service._wait_for_worker_with_watchdog(
            FakeProcess(), asyncio.Event(), state, idle_timeout=0.01,
        )
    assert state["watchdog_timeout"] == "idle"


def test_worker_watchdog_config_preserves_process_timeout_fallback(monkeypatch):
    from raganything.services import kb_service

    monkeypatch.delenv("PROCESS_IDLE_TIMEOUT", raising=False)
    monkeypatch.delenv("PROCESS_MAX_TIMEOUT", raising=False)
    monkeypatch.setenv("PROCESS_TIMEOUT", "7200")
    assert kb_service._worker_watchdog_config() == (7200.0, 0.0)

    monkeypatch.setenv("PROCESS_IDLE_TIMEOUT", "45")
    monkeypatch.setenv("PROCESS_MAX_TIMEOUT", "86400")
    assert kb_service._worker_watchdog_config() == (45.0, 86400.0)


@pytest.mark.asyncio
async def test_degraded_state_rejects_partial_multimodal_document(monkeypatch):
    from raganything.services import kb_service, document_quality

    quality_calls = 0

    async def quality(*_args, **_kwargs):
        nonlocal quality_calls
        quality_calls += 1
        return {"ready": True}

    monkeypatch.setattr(kb_service, "_load_text_chunks_json", lambda _kb: {})
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", quality)

    result = await kb_service._mark_degraded_document(
        "default",
        "doc-partial",
        {
            "chunks_count": 1,
            "chunks_list": ["chunk-1"],
            "metadata": {
                "content_ready": False,
                "multimodal_processed": False,
                "failure_stage": "worker_timeout",
            },
        },
        error_message="worker timeout",
    )

    assert result is None
    assert quality_calls == 0


@pytest.mark.asyncio
async def test_degraded_state_rejects_extra_persisted_chunk(monkeypatch):
    from raganything.services import kb_service, document_quality

    quality_calls = 0

    async def quality(*_args, **_kwargs):
        nonlocal quality_calls
        quality_calls += 1
        return {"ready": True}

    async def persisted(_kb_name, _doc_id):
        return {"chunk-1", "chunk-multimodal"}

    monkeypatch.setattr(
        kb_service, "_load_persisted_chunk_ids_for_document", persisted,
    )
    monkeypatch.setattr(kb_service, "_load_text_chunks_json", lambda _kb: {})
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", quality)

    result = await kb_service._mark_degraded_document(
        "default",
        "doc-partial",
        {
            "chunks_count": 1,
            "chunks_list": ["chunk-1"],
            "metadata": {
                "content_ready": True,
                "multimodal_processed": True,
            },
        },
        error_message="graph extraction timed out",
    )

    assert result is None
    assert quality_calls == 0


@pytest.mark.asyncio
async def test_retry_cleanup_targets_marked_doc_and_accepts_enum_status(monkeypatch):
    from enum import Enum
    from raganything.services import kb_service

    class Status(Enum):
        FAILED = "failed"

    target = {
        "status": Status.FAILED,
        "file_path": "manual.pdf",
        "chunks_list": ["chunk-old"],
        "metadata": {
            "cleanup_pending": True,
            "residual_data": True,
            "task_id": "retry-task",
            "file_hash": "hash-target",
        },
    }
    other = {
        "status": "failed",
        "file_path": "manual.pdf",
        "chunks_list": ["chunk-other"],
        "metadata": {
            "cleanup_pending": True,
            "residual_data": True,
            "task_id": "other-task",
            "file_hash": "hash-other",
        },
    }

    class FakeDocStatus:
        def __init__(self):
            self.records = {"doc-target": target}

        async def get_by_id(self, doc_id):
            return self.records.get(doc_id)

        async def upsert(self, payload):
            self.records.update(payload)

        async def index_done_callback(self):
            return None

    class FakeLightRAG:
        def __init__(self):
            self.doc_status = FakeDocStatus()
            self.deleted = []

        async def adelete_by_doc_id(self, doc_id, delete_llm_cache=False):
            self.deleted.append((doc_id, delete_llm_cache))
            self.doc_status.records.pop(doc_id, None)
            return SimpleNamespace(status="success")

    fake_lightrag = FakeLightRAG()
    fake_rag = SimpleNamespace(lightrag=fake_lightrag, multimodal_status_cache=None)

    async def load_status(_kb_name):
        return {"doc-target": target, "doc-other": other}

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load_status)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)
    monkeypatch.setattr(kb_service, "kb_instances", {"default": fake_rag})

    cleaned = await kb_service._cleanup_retry_document_residue(
        "default",
        "manual.pdf",
        "retry-task",
        "hash-target",
        retry_job_id=42,
    )

    assert cleaned == ["doc-target"]
    assert fake_lightrag.deleted == [("doc-target", True)]


@pytest.mark.asyncio
async def test_single_upload_persists_snapshot_before_queued_metadata(monkeypatch, tmp_path):
    from fastapi import UploadFile
    from raganything.routers import knowledge
    import raganything.routers.shared as shared

    monkeypatch.chdir(tmp_path)
    calls = []

    async def no_reindex(_kb):
        return None

    async def vlm_snapshot(_user_id):
        return SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )

    async def save_snapshot(task_id, user_id, **_overrides):
        calls.append(("snapshot", task_id, user_id))
        return SimpleNamespace(
            chunking_strategy="recursive",
            enable_image=True,
            enable_table=True,
            enable_equation=True,
            enable_video=False,
        )

    async def register_upload(**kwargs):
        assert calls and calls[0][0] == "snapshot"
        calls.append(("upload", kwargs["task_id"], kwargs["uploaded_by"]))
        return {"id": 1}

    queue = asyncio.Queue()

    async def queue_for(task_info):
        queue.put_nowait(task_info)
        return queue, queue.qsize()

    monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", no_reindex)
    monkeypatch.setattr(knowledge, "_resolve_upload_vlm_snapshot", vlm_snapshot)
    monkeypatch.setattr(knowledge, "_resolve_chunking_strategy", lambda _value: "recursive")
    monkeypatch.setattr(knowledge, "_compute_file_hash", lambda _path: "hash-a")
    monkeypatch.setattr(knowledge, "_is_file_being_processed", lambda *_args: None)
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", save_snapshot)
    monkeypatch.setattr(knowledge, "_register_upload_with_stale_recovery", register_upload)
    monkeypatch.setattr(knowledge, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(shared, "_enqueue_upload_task", queue_for)

    endpoint = getattr(knowledge.upload_file, "__wrapped__", knowledge.upload_file)
    result = await endpoint(
        request=None,
        file=UploadFile(filename="report.txt", file=BytesIO(b"content")),
        kb="demo",
        current_user={"id": 7},
    )

    assert [call[0] for call in calls] == ["snapshot", "upload"]
    assert queue.get_nowait()["task_id"] == result["task_id"]


@pytest.mark.asyncio
async def test_single_upload_removes_snapshot_when_metadata_registration_fails(
    monkeypatch, tmp_path
):
    from fastapi import HTTPException, UploadFile
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    deleted = []

    async def no_reindex(_kb):
        return None

    async def vlm_snapshot(_user_id):
        return SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )

    async def save_snapshot(*_args, **_kwargs):
        return SimpleNamespace(
            chunking_strategy="recursive",
            enable_image=True,
            enable_table=True,
            enable_equation=True,
            enable_video=False,
        )

    async def registration_failed(**_kwargs):
        return None

    async def delete_snapshot(task_id):
        deleted.append(task_id)

    monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", no_reindex)
    monkeypatch.setattr(knowledge, "_resolve_upload_vlm_snapshot", vlm_snapshot)
    monkeypatch.setattr(knowledge, "_resolve_chunking_strategy", lambda _value: "recursive")
    monkeypatch.setattr(knowledge, "_compute_file_hash", lambda _path: "hash-a")
    monkeypatch.setattr(knowledge, "_is_file_being_processed", lambda *_args: None)
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", save_snapshot)
    monkeypatch.setattr(knowledge, "_register_upload_with_stale_recovery", registration_failed)
    monkeypatch.setattr(knowledge, "_delete_upload_settings_snapshot", delete_snapshot)

    endpoint = getattr(knowledge.upload_file, "__wrapped__", knowledge.upload_file)
    with pytest.raises(HTTPException) as exc:
        await endpoint(
            request=None,
            file=UploadFile(filename="report.txt", file=BytesIO(b"content")),
            kb="demo",
            current_user={"id": 7},
        )

    assert exc.value.status_code == 409
    assert deleted and deleted[0]


@pytest.mark.asyncio
async def test_startup_restores_durable_queued_upload(monkeypatch, tmp_path):
    from raganything.services import kb_service

    file_path = tmp_path / "queued.pdf"
    file_path.write_bytes(b"queued")
    queued = []

    class Connection:
        async def fetch(self, _sql):
            return [{
                "task_id": "task-restored",
                "file_path": str(file_path),
                "filename": "queued.pdf",
                "kb_name": "demo",
                "uploaded_by": 7,
                "snapshot_task_id": "task-restored",
            }]

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def enqueue(task_info):
        queued.append(task_info)
        kb_service._queued_task_ids.add(task_info["task_id"])
        return asyncio.Queue(), 0

    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())
    monkeypatch.setattr(kb_service, "_enqueue_upload_task", enqueue)
    kb_service._queued_task_ids.clear()

    assert await kb_service.resume_queued_upload_tasks() == 1
    assert queued == [{
        "task_id": "task-restored",
        "file_path": str(file_path),
        "filename": "queued.pdf",
        "kb_name": "demo",
        "chunking_strategy": "",
        "user_id": 7,
    }]


@pytest.mark.asyncio
async def test_startup_fails_queued_upload_without_snapshot(monkeypatch, tmp_path):
    from raganything.services import kb_service

    file_path = tmp_path / "queued.pdf"
    file_path.write_bytes(b"queued")
    failures = []

    class Connection:
        async def fetch(self, _sql):
            return [{
                "task_id": "task-orphan",
                "file_path": str(file_path),
                "filename": "queued.pdf",
                "kb_name": "demo",
                "uploaded_by": 7,
                "snapshot_task_id": None,
            }]

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def update(*args, **kwargs):
        failures.append((args, kwargs))
        return {"status": "failed"}

    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update)
    kb_service._queued_task_ids.clear()

    assert await kb_service.resume_queued_upload_tasks() == 0
    assert failures[0][0][:2] == ("task-orphan", "failed")
    assert failures[0][1]["error_message"] == "settings_snapshot_missing"


@pytest.mark.asyncio
async def test_processing_snapshot_is_persisted_in_document_metadata(monkeypatch):
    from raganything.services import kb_service

    saved = []

    class Store:
        async def upsert(self, payload):
            saved.append(payload)

        async def index_done_callback(self):
            saved.append("committed")

    async def statuses(_kb):
        return {
            "doc-1": {
                "file_path": "abcd1234_report.pdf",
                "track_id": "task-1",
                "metadata": {"existing": True},
                "updated_at": "2026-07-30T10:00:00+00:00",
            }
        }

    async def store(_kb):
        return Store()

    monkeypatch.setattr(kb_service, "_load_doc_status_json", statuses)
    monkeypatch.setattr(kb_service, "_get_pg_doc_status_storage", store)
    snapshot = {
        "revision": 4,
        "fingerprint": "settings-fp",
        "profile_ids": {
            "llm": {"id": "llm-a", "fingerprint": "llm-fp"},
            "vlm": {"id": "vlm-a", "fingerprint": "vlm-fp"},
        },
        "settings": {
            "models": {"llm_profile_id": "llm-a", "vlm_profile_id": "vlm-a"},
            "ingestion": {"chunking_strategy": "recursive"},
            "retrieval": {"preset": "balanced"},
            "runtime": {"llm_timeout": 180, "personal_concurrency": 2},
        },
    }

    assert await kb_service.persist_document_processing_snapshot(
        "demo", "report.pdf", "task-1", snapshot
    ) == "doc-1"
    metadata = saved[0]["doc-1"]["metadata"]
    assert metadata["existing"] is True
    assert metadata["processing_settings_snapshot"] == snapshot
    assert saved[1] == "committed"


@pytest.mark.asyncio
async def test_create_upload_settings_snapshot_persists_resolved_with_permitted_sections(
    monkeypatch,
):
    from raganything.routers import knowledge
    from raganything.services import user_settings

    seen = {}
    persisted = []
    resolved_stub = SimpleNamespace(
        revision=3,
        fingerprint="fp-1",
        ingestion=SimpleNamespace(
            chunking_strategy="sentence",
            enable_video=False,
        ),
    )

    async def fake_available_sections_for_user(user_id):
        seen["user_id"] = user_id
        return ("models", "ingestion")

    async def fake_resolve(user_id, *, request_overrides=None, permitted_sections=None, **kwargs):
        seen["resolve"] = (user_id, request_overrides, permitted_sections)
        return resolved_stub

    async def fake_create_snapshot(task_id, user_id, resolved):
        persisted.append((task_id, user_id, resolved))

    monkeypatch.setattr(user_settings, "available_sections_for_user", fake_available_sections_for_user)
    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", fake_resolve)
    monkeypatch.setattr(user_settings, "create_task_settings_snapshot", fake_create_snapshot)

    ingestion = await knowledge._create_upload_settings_snapshot(
        "task-42",
        7,
        chunking_strategy="sentence",
        enable_image="true",
        enable_table="false",
        enable_equation="true",
        enable_video="false",
    )

    assert seen["user_id"] == 7
    assert seen["resolve"][0] == 7
    assert seen["resolve"][1] == {
        "ingestion": {
            "chunking_strategy": "sentence",
            "enable_image": True,
            "enable_table": False,
            "enable_equation": True,
            "enable_video": False,
        }
    }
    assert seen["resolve"][2] == ("models", "ingestion")
    assert persisted == [("task-42", 7, resolved_stub)]
    assert ingestion is resolved_stub.ingestion
