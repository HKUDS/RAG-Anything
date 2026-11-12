"""Tests ensuring doc_status records written by RAG-Anything are strictly compatible
with LightRAG's DocProcessingStatus dataclass and get_docs_paginated (#109).

Prevents HTTP 500 crashes in LightRAG Server and WebUI caused by unexpected keyword
arguments like 'content', 'multimodal_content', or 'scheme_name' in doc_status payloads.
"""

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest
from lightrag.base import DocProcessingStatus
from lightrag.kg.json_doc_status_impl import JsonDocStatusStorage

from raganything.base import DocStatus
from raganything.processor import ProcessorMixin


@pytest.fixture(autouse=True)
def _mock_shared_storage(monkeypatch):
    """Isolate shared storage helpers like set_all_update_flags for tests."""

    async def _noop(*args, **kwargs):
        pass

    import lightrag.kg.json_doc_status_impl as jimpl

    monkeypatch.setattr(jimpl, "set_all_update_flags", _noop)


class DummyDocStatusProcessor(ProcessorMixin):
    def __init__(self, doc_status_storage, multimodal_cache):
        self.lightrag = SimpleNamespace(doc_status=doc_status_storage)
        self.multimodal_status_cache = multimodal_cache
        self.logger = SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            debug=lambda *args, **kwargs: None,
        )
        self.config = SimpleNamespace(
            parser_output_dir="/tmp/output",
            parse_method="auto",
            display_content_stats=False,
            use_full_path=False,
            content_format="default",
            parser="mineru",
        )


@pytest.fixture
def doc_status_storage(tmp_path):
    storage = JsonDocStatusStorage(
        "test_ns", "test_ws", {"working_dir": str(tmp_path)}, None
    )
    storage._storage_lock = asyncio.Lock()
    storage._data = {}
    storage.storage_updated = SimpleNamespace(value=False)
    return storage


class InMemoryStorage:
    def __init__(self):
        self.records = {}

    async def get_by_id(self, key):
        return self.records.get(key)

    async def upsert(self, data):
        self.records.update(data)

    async def index_done_callback(self):
        pass


@pytest.mark.asyncio
async def test_ensure_doc_status_record_is_deserializable_by_doc_processing_status(
    doc_status_storage,
):
    """Verify _ensure_doc_status_record creates records that deserialize cleanly into DocProcessingStatus."""
    multimodal_cache = InMemoryStorage()
    processor = DummyDocStatusProcessor(doc_status_storage, multimodal_cache)

    record = await processor._ensure_doc_status_record(
        doc_id="doc-123",
        file_path="sample.pdf",
        scheme_name="custom_scheme",
        status=DocStatus.READY,
    )

    # 1. Direct unpacking check into LightRAG's DocProcessingStatus dataclass
    clean_data = dict(record)
    clean_data.pop("content", None)  # lightrag removes content if present
    status_obj = DocProcessingStatus(**clean_data)
    assert status_obj.status == DocStatus.READY
    assert status_obj.file_path == "sample.pdf"
    assert status_obj.metadata.get("scheme_name") == "custom_scheme"

    # 2. Paginated retrieval through LightRAG's real JsonDocStatusStorage without TypeError
    paginated_docs, count = await doc_status_storage.get_docs_paginated()
    assert count == 1
    retrieved_id, retrieved_status = paginated_docs[0]
    assert retrieved_id == "doc-123"
    assert isinstance(retrieved_status, DocProcessingStatus)
    assert retrieved_status.metadata.get("scheme_name") == "custom_scheme"


@pytest.mark.asyncio
async def test_completed_multimodal_status_remains_readable_by_server(
    doc_status_storage,
):
    """Completion must be visible without breaking paginated server retrieval."""
    multimodal_cache = InMemoryStorage()
    processor = DummyDocStatusProcessor(doc_status_storage, multimodal_cache)

    # Pre-populate doc status
    doc_status_storage._data["doc-456"] = {
        "status": DocStatus.PROCESSED,
        "content_summary": "summary",
        "content_length": 50,
        "file_path": "doc.pdf",
        "created_at": "2026-11-06T12:00:00Z",
        "updated_at": "2026-11-06T12:00:00Z",
    }

    await processor._mark_multimodal_processing_complete("doc-456")

    record = await doc_status_storage.get_by_id("doc-456")
    assert await processor._get_multimodal_processed_flag("doc-456", record)

    # Storage must remain readable by get_docs_paginated
    paginated_docs, count = await doc_status_storage.get_docs_paginated()
    assert count == 1
    assert paginated_docs[0][0] == "doc-456"


@pytest.mark.asyncio
async def test_process_document_complete_lightrag_api_leaves_storage_compatible(
    doc_status_storage, monkeypatch
):
    """Verify process_document_complete_lightrag_api creates records compatible with get_docs_paginated."""
    multimodal_cache = InMemoryStorage()
    processor = DummyDocStatusProcessor(doc_status_storage, multimodal_cache)
    processor.callback_manager = None
    processor.lightrag.ainsert = lambda **kwargs: asyncio.sleep(0)

    # Mock pipeline status lock & shared storage
    shared_data = {"pipeline_status": {"history_messages": [], "scan_disabled": False}}
    fake_kg_shared = types.ModuleType("lightrag.kg.shared_storage")
    fake_kg_shared.get_namespace_data = lambda ns: asyncio.sleep(
        0, result=shared_data[ns]
    )
    fake_kg_shared.get_pipeline_status_lock = lambda: asyncio.Lock()
    monkeypatch.setitem(sys.modules, "lightrag.kg.shared_storage", fake_kg_shared)

    async def fake_ensure_initialized():
        return {"success": True}

    async def fake_parse_doc(file_path, *args, **kwargs):
        return [{"type": "text", "text": "sample text", "page_idx": 0}], "doc-api-test"

    processor._ensure_lightrag_initialized = fake_ensure_initialized
    processor.parse_document = fake_parse_doc

    # Run complete workflow
    res = await processor.process_document_complete_lightrag_api(
        file_path="paper.pdf",
        scheme_name="api_scheme",
    )
    assert res is True

    # Critical check: get_docs_paginated must succeed without raising TypeError
    # on doc-pre-paper.pdf or any other created record!
    paginated_docs, count = await doc_status_storage.get_docs_paginated()
    assert count >= 1
    for doc_id, doc_status in paginated_docs:
        assert isinstance(doc_status, DocProcessingStatus)
        # Ensure no non-schema fields leaked
        assert not hasattr(doc_status, "multimodal_content")
        assert not hasattr(doc_status, "content")
