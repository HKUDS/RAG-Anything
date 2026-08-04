import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import UploadFile


@pytest.mark.asyncio
async def test_doc_status_merges_chunking_strategy_metadata():
    from raganything.processor.doc_processor import DocProcessorMixin

    class DocStatusStorage:
        def __init__(self):
            self.records = {}

        async def get_by_id(self, doc_id):
            return self.records.get(doc_id)

        async def upsert(self, records):
            self.records.update(records)

        async def index_done_callback(self):
            return None

    class Processor(DocProcessorMixin):
        def _get_file_reference(self, file_path):
            return file_path

    processor = Processor()
    processor.lightrag = SimpleNamespace(doc_status=DocStatusStorage())

    await processor._upsert_doc_status(
        "doc-1",
        "lesson.pdf",
        metadata={"multimodal_processed": True},
    )
    await processor._upsert_doc_status(
        "doc-1",
        "lesson.pdf",
        chunking_strategy="semantic",
    )

    metadata = processor.lightrag.doc_status.records["doc-1"]["metadata"]
    assert metadata == {
        "multimodal_processed": True,
        "chunking_strategy": "semantic",
    }


@pytest.mark.asyncio
async def test_batch_upload_resolves_default_strategy_before_queueing(monkeypatch, tmp_path):
    import raganything.routers.shared as shared
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(knowledge, "CHUNKING_STRATEGY", "sentence")
    monkeypatch.setattr(knowledge, "_compute_file_hash", lambda _path: "hash-1")
    monkeypatch.setattr(knowledge, "_is_file_being_processed", lambda *_args: None)
    monkeypatch.setattr(knowledge, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(knowledge, "pg_register_upload", AsyncMock(return_value={"id": 1}))
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", AsyncMock())
    monkeypatch.setattr(knowledge, "_resolve_upload_vlm_snapshot", AsyncMock(return_value=SimpleNamespace(
        profile=SimpleNamespace(id="vlm-test"), fingerprint="vlm-fingerprint"
    )))

    queue = asyncio.Queue()

    async def fake_ensure_queue_draining(_kb_name):
        return queue, queue.qsize()

    async def fake_enqueue(task_info):
        queue.put_nowait(task_info)
        return queue, queue.qsize() - 1

    monkeypatch.setattr(shared, "_enqueue_upload_task", fake_enqueue)

    endpoint = getattr(knowledge.upload_files, "__wrapped__", knowledge.upload_files)
    result = await endpoint(
        request=None,
        files=[UploadFile(filename="lesson.txt", file=BytesIO(b"content"))],
        kb="demo-kb",
        chunking_strategy="",
        current_user={"id": 7},
    )

    assert result["chunking_strategy"] == "sentence"
    assert queue.get_nowait()["chunking_strategy"] == "sentence"


@pytest.mark.asyncio
async def test_document_list_returns_strategy_and_null_for_legacy(monkeypatch):
    from raganything.routers import knowledge

    async def fake_cleanup():
        return None

    async def fake_doc_status(_kb_name):
        return {
            "doc-new": {
                "file_path": "new.pdf",
                "status": "processed",
                "metadata": {"chunking_strategy": "structure"},
            },
            "doc-legacy": {
                "file_path": "legacy.pdf",
                "status": "processed",
            },
        }

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", fake_cleanup)
    monkeypatch.setattr(knowledge, "_load_doc_status_summaries", fake_doc_status)

    async def tag_health(_kb, doc_ids):
        return {
            doc_id: {"tag_status": "unmanaged", "tag_raw_status": "missing"}
            for doc_id in doc_ids
        }

    monkeypatch.setattr(knowledge, "_document_tag_health_contract", tag_health)
    monkeypatch.setattr(knowledge, "processing_tasks", {})

    result = await knowledge.list_documents(kb="demo-kb", current_user={"id": 7})
    strategies = {item["file"]: item["chunking_strategy"] for item in result["documents"]}

    assert strategies == {"new.pdf": "structure", "legacy.pdf": None}


@pytest.mark.asyncio
async def test_retry_reuses_document_chunking_strategy(monkeypatch, tmp_path):
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "broken.pdf").write_bytes(b"content")

    async def fake_doc_status(_kb_name):
        return {
            "doc-failed": {
                "file_path": "broken.pdf",
                "status": "failed",
                "metadata": {"chunking_strategy": "semantic"},
            }
        }

    deleted = []

    class DocStatusStorage:
        async def delete(self, ids):
            deleted.extend(ids)

        async def index_done_callback(self):
            return None

    async def fake_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(doc_status=DocStatusStorage()))

    queue = asyncio.Queue()

    async def fake_ensure_queue_draining(_kb_name):
        return queue, queue.qsize()

    monkeypatch.setattr(knowledge, "_load_doc_status_json", fake_doc_status)
    monkeypatch.setattr(knowledge, "get_kb", fake_kb)
    async def fake_enqueue(task_info):
        queue.put_nowait(task_info)
        return queue, queue.qsize() - 1

    monkeypatch.setattr("raganything.routers.shared._enqueue_upload_task", fake_enqueue)
    monkeypatch.setattr(knowledge, "upsert_task_state", AsyncMock())
    monkeypatch.setattr(knowledge, "pg_update_upload_status", AsyncMock(return_value=True))
    monkeypatch.setattr(knowledge, "_compute_file_hash", lambda _path: "hash-1")
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", AsyncMock())
    monkeypatch.setattr(
        knowledge,
        "_resolve_upload_vlm_snapshot",
        AsyncMock(return_value=SimpleNamespace(
            profile=SimpleNamespace(id="vlm-a"), fingerprint="vlm-fingerprint"
        )),
    )

    result = await knowledge.retry_document(
        "doc-failed", kb="demo-kb", current_user={"id": 7}
    )

    assert deleted == ["doc-failed"]
    assert result["chunking_strategy"] == "semantic"
    assert queue.get_nowait()["chunking_strategy"] == "semantic"


@pytest.mark.asyncio
async def test_url_upload_uses_requested_strategy_and_target_kb(monkeypatch, tmp_path):
    from raganything.routers import knowledge

    monkeypatch.chdir(tmp_path)
    events = []

    class Response:
        status_code = 200
        content = b"document"
        headers = {"content-type": "text/plain"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url):
            return Response()

    class LightRAG:
        def __init__(self):
            self.chunking_func = object()

    process_document_complete = AsyncMock()
    finalize_storages = AsyncMock()
    instance = SimpleNamespace(
        lightrag=LightRAG(),
        process_document_complete=process_document_complete,
        finalize_storages=finalize_storages,
    )

    async def fake_event(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(knowledge.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "add_event", fake_event)
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", AsyncMock())

    async def settle_upload(*_args, **_kwargs):
        return []

    monkeypatch.setattr(knowledge, "_settle_in_process_upload", settle_upload)
    monkeypatch.setattr(knowledge, "_get_snapshot_task_kb", AsyncMock(return_value=instance))

    async def run_with_quota(_task_id, operation):
        return await operation()

    monkeypatch.setattr(
        "raganything.services.user_settings.run_ingestion_with_quota",
        run_with_quota,
    )

    result = await knowledge.upload_from_url(
        url="https://example.test/lesson",
        kb="target-kb",
        chunking_strategy="recursive",
        current_user={"id": 7},
    )

    knowledge._get_snapshot_task_kb.assert_awaited_once()
    assert knowledge._get_snapshot_task_kb.await_args.args[1] == "target-kb"
    assert result["chunking_strategy"] == "recursive"
    assert process_document_complete.await_args.kwargs["chunking_strategy"] == "recursive"
    assert [event[0][0] for event in events] == [
        "url_download_start",
        "url_download_complete",
        "url_process_complete",
    ]
