from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from raganything.base import DocStatus
from raganything.processor.chunk_processor import ChunkProcessorMixin
from raganything.processor.multimodal_processor import MultimodalProcessorMixin
from raganything.raganything import RAGAnything
from raganything.routers import knowledge


@pytest.mark.asyncio
async def test_multimodal_description_tasks_are_materialized_in_batches(monkeypatch):
    import asyncio

    active = 0
    peak = 0

    class DocStatus:
        async def get_by_id(self, _doc_id):
            return {"chunks_count": 0}

    class Processor:
        async def generate_description_only(self, **_kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return "description", {
                "entity_name": "image",
                "entity_type": "image",
                "summary": "summary",
            }

    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = MagicMock()
    processor.modal_processors = {"image": Processor()}
    processor.lightrag = SimpleNamespace(
        doc_status=DocStatus(),
        llm_model_max_async=8,
    )

    async def no_op(*_args, **_kwargs):
        return None

    async def no_removed(*_args, **_kwargs):
        return 0

    async def status_no_op(*_args, **_kwargs):
        return True

    processor._convert_to_lightrag_chunks_type_aware = lambda *_args: {
        "chunk": {"content": "description"}
    }
    processor._store_chunks_to_lightrag_storage_type_aware = no_op
    processor._store_multimodal_main_entities = no_op
    processor._batch_extract_entities_lightrag_style_type_aware = no_op
    processor._batch_add_belongs_to_relations_type_aware = no_op
    processor._batch_merge_lightrag_style_type_aware = no_op
    processor._filter_low_degree_entities = no_removed
    processor._update_doc_status_with_chunks_type_aware = status_no_op

    monkeypatch.setenv("MULTIMODAL_MAX_CONCURRENT", "8")
    monkeypatch.setenv("MULTIMODAL_TASK_BATCH_SIZE", "2")
    items = [{"type": "image", "img_path": f"image-{i}.png"} for i in range(5)]

    await processor._process_multimodal_content_batch_type_aware(
        items, "manual.pdf", "doc-1"
    )

    assert peak <= 2


@pytest.mark.asyncio
async def test_individual_multimodal_fallback_rejects_unpersisted_chunk():
    class DocStatus:
        async def get_by_id(self, _doc_id):
            return {"chunks_count": 0}

    class FailedProcessor:
        async def process_multimodal_content(self, **_kwargs):
            return "fallback", {"entity_name": "image"}, []

    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = MagicMock()
    processor.modal_processors = {"image": FailedProcessor()}
    processor.lightrag = SimpleNamespace(doc_status=DocStatus())
    processor._get_file_reference = lambda file_path: file_path

    completed = await processor._process_multimodal_content_individual(
        [{"type": "image", "img_path": "image.png"}], "manual.pdf", "doc-1"
    )

    assert completed is False
    assert processor.logger.error.called


class _DocStatusStore:
    def __init__(self, status):
        self.status = status
        self.upserts = []
        self.index_done = False

    async def get_by_id(self, _doc_id):
        return dict(self.status)

    async def upsert(self, payload):
        self.upserts.append(payload)

    async def index_done_callback(self):
        self.index_done = True


class _ChunkProcessor(ChunkProcessorMixin):
    def __init__(self, store):
        self.lightrag = SimpleNamespace(doc_status=store)
        self.logger = MagicMock()
        self.source_updates = []

    def _register_chunk_sources(self, doc_id, file_path, chunk_ids):
        self.source_updates.append((doc_id, file_path, chunk_ids))


class _MultimodalBackgroundProcessor(MultimodalProcessorMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.status_updates = []

    async def _process_multimodal_content(self, *_args, **_kwargs):
        raise RuntimeError("vision request failed")

    async def _upsert_doc_status(self, doc_id, file_ref, **kwargs):
        self.status_updates.append((doc_id, file_ref, kwargs))


@pytest.mark.asyncio
async def test_background_multimodal_failure_preserves_original_error():
    processor = _MultimodalBackgroundProcessor()

    with pytest.raises(RuntimeError, match="vision request failed"):
        await processor._process_multimodal_content_background(
            [{"type": "image", "img_path": "image.png"}],
            "manual.pdf",
            "doc-1",
        )

    assert processor.status_updates == [
        (
            "doc-1",
            "manual.pdf",
            {
                "status": DocStatus.FAILED,
                "error_msg": "vision request failed",
                "metadata": {
                    "content_ready": False,
                    "multimodal_processed": False,
                    "failure_stage": "multimodal",
                    "cleanup_pending": True,
                    "residual_data": True,
                    "last_error": "vision request failed",
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_multimodal_chunk_metadata_is_persisted_in_doc_status():
    store = _DocStatusStore(
        {
            "file_path": "document.pdf",
            "chunks_list": ["text-chunk"],
            "chunks_count": 1,
            "metadata": {"existing": "value"},
        }
    )
    processor = _ChunkProcessor(store)

    await processor._update_doc_status_with_chunks_type_aware(
        "doc-1",
        ["modal-chunk"],
        {
            "modal-chunk": {
                "is_multimodal": True,
                "original_type": "image",
                "modal_entity_name": "figure (image)",
                "page_idx": 2,
                "media_path": "C:/media/figure.png",
            }
        },
    )

    saved = store.upserts[0]["doc-1"]
    assert saved["chunks_list"] == ["text-chunk", "modal-chunk"]
    assert saved["metadata"]["existing"] == "value"
    assert saved["metadata"]["multimodal_chunks"]["modal-chunk"] == {
        "is_multimodal": True,
        "original_type": "image",
        "modal_entity_name": "figure (image)",
        "page_idx": 2,
        "media_path": "C:/media/figure.png",
    }
    assert store.index_done is True


@pytest.mark.asyncio
async def test_chunks_endpoint_restores_pg_metadata_and_id(monkeypatch):
    async def fake_doc_status(_kb):
        return {
            "doc-1": {
                "chunks_list": ["modal-chunk"],
                "metadata": {
                    "multimodal_chunks": {
                        "modal-chunk": {
                            "is_multimodal": True,
                            "original_type": "image",
                            "modal_entity_name": "figure (image)",
                            "page_idx": 2,
                            "media_path": "C:/missing/figure.png",
                        }
                    }
                },
            }
        }

    class _TextChunks:
        async def get_by_ids(self, _chunk_ids):
            return [
                {
                    "id": "modal-chunk",
                    "content": "Image Content Analysis:\\nImage Path: C:/missing/figure.png",
                    "tokens": 12,
                    "chunk_order_index": 4,
                    "file_path": "document.pdf",
                }
            ]

    async def fake_kb(_kb):
        return SimpleNamespace(lightrag=SimpleNamespace(text_chunks=_TextChunks()))

    monkeypatch.setattr(knowledge, "_load_doc_status_json", fake_doc_status)
    async def allow_kb(*_args, **_kwargs):
        return "demo-kb"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
    monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", no_op)
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", no_op)
    monkeypatch.setattr(knowledge, "get_kb", fake_kb)

    result = await knowledge.get_document_chunks(
        "doc-1", kb="test-kb", current_user={"id": 1}
    )

    chunk = result["chunks"][0]
    assert chunk["chunk_id"] == "modal-chunk"
    assert chunk["is_multimodal"] is True
    assert chunk["original_type"] == "image"
    assert chunk["media_path"] == "C:/missing/figure.png"
    assert chunk["media_available"] is False


def test_pgkv_unsupported_application_namespace_is_disabled():
    from lightrag.kg.postgres_impl import PGKVStorage

    rag = object.__new__(RAGAnything)
    rag.lightrag = SimpleNamespace(key_string_value_json_storage_cls=PGKVStorage)

    assert rag._optional_kv_namespace_supported("parse_cache") is False


def test_pgkv_partial_unsupported_application_namespace_is_disabled():
    from functools import partial
    from lightrag.kg.postgres_impl import PGKVStorage

    rag = object.__new__(RAGAnything)
    # LightRAG binds global_config with functools.partial during construction.
    rag.lightrag = SimpleNamespace(
        key_string_value_json_storage_cls=partial(PGKVStorage, global_config={})
    )

    assert rag._optional_kv_namespace_supported("parse_cache") is False
    assert rag._optional_kv_namespace_supported("multimodal_status") is False


def test_pgkv_lazy_factory_unsupported_application_namespace_is_disabled():
    from functools import partial

    def lazy_storage_factory(*_args, **_kwargs):
        raise AssertionError("The capability check must not construct storage")

    rag = object.__new__(RAGAnything)
    # LightRAG wraps a lazy import factory, not PGKVStorage itself, at runtime.
    rag.lightrag = SimpleNamespace(
        key_string_value_json_storage_cls=partial(
            lazy_storage_factory, global_config={}
        ),
        kv_storage="PGKVStorage",
    )

    assert rag._optional_kv_namespace_supported("parse_cache") is False
    assert rag._optional_kv_namespace_supported("multimodal_status") is False


def test_multimodal_completion_metadata_overrides_stale_legacy_false():
    from raganything.utils import is_multimodal_processed

    assert is_multimodal_processed(
        {"multimodal_processed": False, "metadata": {"multimodal_processed": True}}
    )
    assert is_multimodal_processed({"multimodal_processed": True})
    assert is_multimodal_processed({"metadata": {"multimodal_processed": False}}) is False


@pytest.mark.asyncio
async def test_reprocess_count_skips_metadata_completed_documents(monkeypatch):
    async def fake_doc_status(_kb_name):
        return {
            "completed": {
                "status": "processed",
                "multimodal_processed": False,
                "metadata": {"multimodal_processed": True},
            },
            "pending": {"status": "processed", "metadata": {}},
        }

    class BackgroundTasks:
        def __init__(self):
            self.calls = []

        def add_task(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    monkeypatch.setattr(knowledge, "_load_doc_status_json", fake_doc_status)
    async def allow_kb(*_args, **_kwargs):
        return "demo-kb"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
    monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", no_op)
    monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", no_op)
    tasks = BackgroundTasks()

    endpoint = getattr(knowledge.reprocess_multimodal, "__wrapped__", knowledge.reprocess_multimodal)
    result = await endpoint(
        "demo-kb", tasks, _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "queued"
    assert result["total"] == 1
    assert len(tasks.calls) == 1
