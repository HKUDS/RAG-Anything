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
        async def finalize_storages(self):
            events.append("storage-finalized")

    monkeypatch.setattr(worker, "_drain_background_tasks_or_raise", wait_for_background_tasks)

    await worker._flush_background_tasks_and_finalize(FakeRAG(), "sample.pdf")

    assert events == ["background-complete", "storage-finalized"]


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
    monkeypatch.setattr(worker, "openai_complete_if_cache", complete)

    blocks = await worker._vlm_ocr_document("long.pdf")

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
        await worker._vlm_ocr_document("long.pdf")


@pytest.mark.asyncio
async def test_worker_vision_callback_uses_supplied_image_mime(monkeypatch, tmp_path):
    from raganything.services import kb_service

    worker = _load_process_worker()
    captured = {}

    class CapturingRAG:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def fake_completion(*_args, **kwargs):
        captured["messages"] = kwargs["messages"]
        return "caption"

    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)
    monkeypatch.setattr(worker, "RAGAnything", CapturingRAG)
    monkeypatch.setattr(worker, "openai_complete_if_cache", fake_completion)
    monkeypatch.setattr(worker, "make_cached_embed_func", lambda func, *_args: func)

    rag = await worker.create_rag(working_dir=str(tmp_path))
    response = await rag.kwargs["vision_model_func"](
        "describe",
        image_data="AA==",
        image_mime_type="image/png",
    )

    assert response == "caption"
    image_url = captured["messages"][-1]["content"][1]["image_url"]["url"]
    assert image_url == "data:image/png;base64,AA=="


@pytest.mark.asyncio
async def test_kb_service_vision_callback_uses_supplied_image_mime(monkeypatch, tmp_path):
    from raganything.services import kb_service

    captured = {}

    class CapturingRAG:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def fake_completion(*_args, **kwargs):
        captured["messages"] = kwargs["messages"]
        return "caption"

    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)
    monkeypatch.setattr(kb_service, "RAGAnything", CapturingRAG)
    monkeypatch.setattr(kb_service, "openai_complete_if_cache", fake_completion)
    monkeypatch.setattr(kb_service, "make_cached_embed_func", lambda func, *_args: func)

    rag = await kb_service.create_rag(working_dir=str(tmp_path))
    assert callable(rag._raw_embedding_provider)
    assert callable(rag._raw_embedding_preflight_provider)
    response = await rag.kwargs["vision_model_func"](
        "describe",
        image_data="AA==",
        image_mime_type="image/webp",
    )

    assert response == "caption"
    image_url = captured["messages"][-1]["content"][1]["image_url"]["url"]
    assert image_url == "data:image/webp;base64,AA=="
