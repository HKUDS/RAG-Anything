import asyncio
import importlib
import io
import sys

import pytest


def _load_process_worker():
    module = sys.modules.get("process_worker")
    if module is not None:
        return module

    original_stdout = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    try:
        return importlib.import_module("process_worker")
    finally:
        sys.stdout = original_stdout


@pytest.mark.asyncio
async def test_worker_lease_loss_records_retryable_failure_before_cancellation(capsys):
    worker = _load_process_worker()
    processing_task = worker.asyncio.create_task(worker.asyncio.Event().wait())
    failure_state = {"error": None}
    secondary = []

    async def lost_lease(*_args):
        return False

    await worker._maintain_quota_lease(
        "lease-a", "owner-a", processing_task, failure_state, secondary,
        lost_lease, interval_seconds=0,
    )

    with pytest.raises(worker.asyncio.CancelledError):
        await processing_task

    lease_error = failure_state["error"]
    assert isinstance(lease_error, worker.QuotaLeaseLost)
    assert secondary == []
    assert worker._quota_failure_for_cancel(lease_error) is lease_error
    assert worker._quota_failure_for_cancel(None) is None

    worker._emit_worker_error(
        stage="quota", error=lease_error, retryable=True,
        secondary=secondary,
    )
    line = capsys.readouterr().out
    assert '"stage": "quota"' in line
    assert '"root_type": "QuotaLeaseLost"' in line
    assert '"failure_code": "quota_lease_lost"' in line
    assert '"retryable": true' in line


@pytest.mark.asyncio
async def test_worker_heartbeat_exception_records_retryable_quota_error():
    worker = _load_process_worker()
    processing_task = worker.asyncio.create_task(worker.asyncio.Event().wait())
    failure_state = {"error": None}
    secondary = []

    async def unavailable_heartbeat(*_args):
        raise RuntimeError("database unavailable")

    await worker._maintain_quota_lease(
        "lease-a", "owner-a", processing_task, failure_state, secondary,
        unavailable_heartbeat, interval_seconds=0,
    )

    with pytest.raises(worker.asyncio.CancelledError):
        await processing_task

    error = failure_state["error"]
    assert isinstance(error, worker.QuotaHeartbeatUnavailable)

    assert error.failure_code == "quota_heartbeat_unavailable"
    assert worker._quota_failure_for_cancel(error) is error
    assert secondary == ["quota_heartbeat: RuntimeError: database unavailable"]


def test_worker_external_cancellation_is_not_misclassified_as_quota_failure():
    worker = _load_process_worker()

    assert worker._quota_failure_for_cancel(asyncio.CancelledError()) is None


def test_worker_classifies_wrapped_v2_video_failure_as_retryable():
    worker = _load_process_worker()

    wrapped = RuntimeError("background processing failed: video_frame_encode_failed")

    assert worker._video_failure_code(wrapped) == "video_frame_encode_failed"
    assert worker._is_retryable_video_error(wrapped) is True


@pytest.mark.parametrize(
    "wrapped",
    [
        RuntimeError("Hnsw insert temporary context: out of memory"),
        RuntimeError("background graph write failed"),
    ],
)
def test_worker_classifies_chained_hnsw_memory_failure_as_terminal(capsys, wrapped):
    worker = _load_process_worker()
    if "background" in str(wrapped):
        cause = RuntimeError("out of memory")
        cause.sqlstate = "53200"
        wrapped.__cause__ = cause

    assert worker._is_hnsw_memory_error(wrapped) is True

    worker._emit_worker_error(
        stage="graph_index",
        error=worker.GraphIndexHnswMemoryExhausted(),
        retryable=False,
        secondary=[],
    )

    line = capsys.readouterr().out
    assert '"stage": "graph_index"' in line
    assert '"failure_code": "graph_index_hnsw_memory_exhausted"' in line
    assert '"retryable": false' in line


@pytest.mark.asyncio
async def test_processing_snapshot_reads_fresh_pg_status_after_worker_commit(monkeypatch):
    from raganything.services import kb_service

    recorded = {}

    class Store:
        async def upsert(self, values):
            recorded.update(values)

        async def index_done_callback(self):
            recorded["flushed"] = True

    snapshot = {
        "revision": 1,
        "fingerprint": "fingerprint",
        "profile_ids": {"llm": {"id": "qwen"}},
        "settings": {"ingestion": {"chunking_strategy": "recursive"}},
    }
    fresh = {
        "doc-1": {
            "file_path": "sample.pdf",
            "track_id": "insert_20260731_worker_run",
            "metadata": {},
            "updated_at": "2026-07-31T00:00:00Z",
        }
    }

    async def stale_cache(_kb):
        return {}

    async def fresh_pg(_kb):
        return fresh

    async def store(_kb):
        return Store()

    monkeypatch.setattr(kb_service, "_load_doc_status_json", stale_cache)
    monkeypatch.setattr(kb_service, "_load_fresh_pg_doc_status_records", fresh_pg)
    monkeypatch.setattr(kb_service, "_get_pg_doc_status_storage", store)

    doc_id = await kb_service.persist_document_processing_snapshot(
        "test", "sample.pdf", "task-1", snapshot
    )

    assert doc_id == "doc-1"
    assert recorded["doc-1"]["metadata"]["processing_settings_snapshot"]["fingerprint"] == "fingerprint"
    assert recorded["flushed"] is True


@pytest.mark.asyncio
async def test_worker_waits_for_background_tasks_before_finalizing(monkeypatch):
    worker = _load_process_worker()
    events = []

    async def wait_for_background_tasks():
        events.append("background-complete")

    class FakeRAG:
        async def finalize_storages(self, **kwargs):
            events.append(("storage-finalized", kwargs))

    monkeypatch.setattr(worker, "_drain_background_tasks_or_raise", wait_for_background_tasks)

    await worker._flush_background_tasks_and_finalize(FakeRAG(), "sample.pdf")

    assert events == [
        "background-complete",
        ("storage-finalized", {"worker_vdb_persistence": True}),
    ]


@pytest.mark.asyncio
async def test_worker_persistence_failure_propagates_before_graph_done(monkeypatch, capsys):
    worker = _load_process_worker()

    async def wait_for_background_tasks():
        return None

    class FakeRAG:
        async def finalize_storages(self, **kwargs):
            assert kwargs == {"worker_vdb_persistence": True}
            raise RuntimeError("nanovectordb_persist_failed:chunks_vdb")

    monkeypatch.setattr(worker, "_drain_background_tasks_or_raise", wait_for_background_tasks)

    with pytest.raises(RuntimeError, match="nanovectordb_persist_failed:chunks_vdb"):
        await worker._flush_background_tasks_and_finalize(FakeRAG(), "sample.pdf")

    assert "phase=graph-building status=done" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_worker_background_failure_prevents_finalize(monkeypatch):
    worker = _load_process_worker()

    async def failed_task():
        raise RuntimeError("multimodal failed")

    task = worker.asyncio.create_task(failed_task())
    monkeypatch.setattr(worker, "get_pending_background_tasks", lambda: {task})

    with pytest.raises(RuntimeError, match="background processing failed"):
        await worker._drain_background_tasks_or_raise()


@pytest.mark.asyncio
async def test_worker_detects_failure_that_completed_before_drain():
    worker = _load_process_worker()
    from raganything.processor import (
        consume_background_task_errors,
        get_pending_background_tasks,
        register_background_task,
    )

    consume_background_task_errors()

    async def failed_task():
        raise RuntimeError("multimodal failed before drain")

    task = worker.asyncio.create_task(failed_task())
    register_background_task(task)
    with pytest.raises(RuntimeError, match="multimodal failed before drain"):
        await task
    await worker.asyncio.sleep(0)
    assert task not in get_pending_background_tasks()

    with pytest.raises(RuntimeError, match="background processing failed"):
        await worker._drain_background_tasks_or_raise()


@pytest.mark.asyncio
async def test_cancelled_registered_background_task_is_not_reported_as_failure():
    worker = _load_process_worker()
    from raganything.processor import (
        consume_background_task_errors,
        register_background_task,
    )

    consume_background_task_errors()
    task = worker.asyncio.create_task(worker.asyncio.Event().wait())
    register_background_task(task)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await worker.asyncio.sleep(0)

    assert consume_background_task_errors() == []


@pytest.mark.asyncio
async def test_worker_background_timeout_cancels_and_raises(monkeypatch):
    worker = _load_process_worker()

    async def never_finishes():
        await worker.asyncio.Event().wait()

    task = worker.asyncio.create_task(never_finishes())
    monkeypatch.setattr(worker, "get_pending_background_tasks", lambda: {task})
    monkeypatch.setattr(worker, "_BG_TASK_MAX_WAIT", 0)

    with pytest.raises(TimeoutError, match="background processing exceeded"):
        await worker._drain_background_tasks_or_raise()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_worker_llm_preflight_requires_a_non_empty_response(monkeypatch):
    worker = _load_process_worker()
    monkeypatch.setenv("MODEL_PREFLIGHT_ENABLED", "true")

    class FakeRAG:
        async def _raw_llm_preflight_provider(self, *_args, **_kwargs):
            return "OK"

    await worker._preflight_llm_service(FakeRAG())


@pytest.mark.asyncio
async def test_vlm_ocr_processes_every_pdf_page_without_silent_cap(monkeypatch):
    worker = _load_process_worker()
    calls = []

    class FakeBitmap:
        @staticmethod
        def to_pil():
            from PIL import Image
            return Image.new("RGB", (1, 1), "white")

    class FakePage:
        @staticmethod
        def render(scale):
            assert scale == 2
            return FakeBitmap()

    class FakePdf:
        def __init__(self, _path):
            self.pages = [FakePage() for _ in range(31)]

        def __len__(self):
            return len(self.pages)

        def __getitem__(self, index):
            return self.pages[index]

    async def complete(*_args, **_kwargs):
        calls.append(1)
        return f"page {len(calls)}"

    monkeypatch.delenv("VLM_OCR_MAX_PAGES", raising=False)
    monkeypatch.setattr(worker.pdfium, "PdfDocument", FakePdf)
    blocks = await worker._vlm_ocr_document("long.pdf", complete)

    assert len(calls) == 31
    assert [block["page_idx"] for block in blocks] == list(range(31))


@pytest.mark.asyncio
async def test_vlm_ocr_rejects_configured_partial_page_limit(monkeypatch):
    worker = _load_process_worker()

    class FakePdf:
        def __init__(self, _path):
            self.pages = [object() for _ in range(31)]

        def __len__(self):
            return len(self.pages)

    monkeypatch.setenv("VLM_OCR_MAX_PAGES", "30")
    monkeypatch.setattr(worker.pdfium, "PdfDocument", FakePdf)

    with pytest.raises(RuntimeError, match="refusing partial document processing"):
        await worker._vlm_ocr_document("long.pdf", None)


@pytest.mark.asyncio
async def test_kb_service_vision_callback_uses_supplied_image_mime(monkeypatch, tmp_path):
    from raganything.services import kb_service
    from raganything.services import vision_models

    captured = {}

    class CapturingRAG:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def fake_vision(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "caption"

    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)
    monkeypatch.setattr(kb_service, "RAGAnything", CapturingRAG)
    monkeypatch.setattr(kb_service, "make_cached_embed_func", lambda func, *_args: func)
    monkeypatch.setattr(
        vision_models,
        "build_contextual_vlm_callable",
        lambda _profile_id: fake_vision,
    )

    rag = await kb_service.create_rag(working_dir=str(tmp_path))
    assert callable(rag._raw_embedding_provider)
    assert callable(rag._raw_embedding_preflight_provider)
    response = await rag.kwargs["vision_model_func"](
        "describe",
        image_data="AA==",
        image_mime_type="image/webp",
    )

    assert response == "caption"
    assert captured["image_data"] == "AA=="
    assert captured["image_mime_type"] == "image/webp"
