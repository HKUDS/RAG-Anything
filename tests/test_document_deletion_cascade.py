"""Tests for cascading document deletion in RAG-Anything (#127, #332).

Ensures that calling adelete_by_doc_id cleans up:
- multimodal_status_cache entries
- parsed media files and isolated output directories on disk
- pre-registration placeholders (doc-pre-<filename>)
- core LightRAG vector/graph elements via adelete_by_doc_id
"""

from types import SimpleNamespace

import pytest

from raganything.base import DocStatus
from raganything.parser import Parser
from raganything.processor import ProcessorMixin


class InMemoryStorage:
    def __init__(self, records=None):
        self.records = dict(records or {})
        self.deleted_keys = []

    async def get_by_id(self, key):
        return self.records.get(key)

    async def delete(self, keys):
        for k in keys:
            self.deleted_keys.append(k)
            self.records.pop(k, None)

    async def upsert(self, data):
        self.records.update(data)

    async def index_done_callback(self):
        pass


class FakeDeletionResult:
    def __init__(self, status="success", doc_id="doc-1", message="Deleted"):
        self.status = status
        self.doc_id = doc_id
        self.message = message
        self.status_code = 200
        self.file_path = "sample.pdf"


class FakeLightRAG:
    def __init__(self, doc_status_records=None, full_docs_records=None):
        self.doc_status = InMemoryStorage(doc_status_records)
        self.full_docs = InMemoryStorage(full_docs_records)
        self.adelete_called_with = None

    async def adelete_by_doc_id(self, doc_id, delete_llm_cache=False):
        self.adelete_called_with = (doc_id, delete_llm_cache)
        await self.doc_status.delete([doc_id])
        await self.full_docs.delete([doc_id])
        return FakeDeletionResult(doc_id=doc_id)


class DummyProcessor(ProcessorMixin):
    def __init__(self, lightrag, multimodal_cache, tmp_path):
        self.lightrag = lightrag
        self.multimodal_status_cache = multimodal_cache
        self.logger = SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            debug=lambda *args, **kwargs: None,
        )
        self.config = SimpleNamespace(
            parser_output_dir=str(tmp_path / "output"),
            parse_method="auto",
            display_content_stats=False,
            use_full_path=False,
            content_format="default",
            parser="mineru",
        )

    async def _ensure_lightrag_initialized(self):
        return {"success": True}


@pytest.mark.asyncio
async def test_adelete_by_doc_id_not_found(tmp_path):
    """Deleting a non-existent document returns status='not_found' gracefully."""
    lightrag = FakeLightRAG()
    cache = InMemoryStorage()
    processor = DummyProcessor(lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id("non-existent-doc")
    assert result["status"] == "not_found"
    assert result["doc_id"] == "non-existent-doc"
    assert result["multimodal_status_deleted"] is False
    assert result["media_files_deleted"] is False


@pytest.mark.asyncio
async def test_adelete_by_doc_id_cleans_multimodal_cache(tmp_path):
    """Multimodal cache entries must be deleted when the document is removed."""
    doc_id = "doc-test-123"
    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": "paper.pdf"}
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id)
    assert result["status"] == "success"
    assert result["multimodal_status_deleted"] is True
    assert doc_id not in cache.records
    assert doc_id in cache.deleted_keys


@pytest.mark.asyncio
async def test_adelete_by_doc_id_media_files_removal(tmp_path):
    """Media output directory on disk is removed when delete_media_files=True, preserved otherwise."""
    doc_id = "doc-media-test"
    file_path = "document.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create the unique output directory as created by Parser
    unique_dir = Parser._unique_output_dir(output_dir, file_path)
    unique_dir.mkdir(parents=True, exist_ok=True)
    sample_img = unique_dir / "image_1.png"
    sample_img.write_text("fake image data")

    assert unique_dir.exists()
    assert sample_img.exists()

    # 1. When delete_media_files=False: directory must be preserved
    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": file_path}
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    res_keep = await processor.adelete_by_doc_id(doc_id, delete_media_files=False)
    assert res_keep["status"] == "success"
    assert res_keep["media_files_deleted"] is False
    assert unique_dir.exists()

    # 2. When delete_media_files=True: directory must be deleted
    lightrag.doc_status.records[doc_id] = {
        "status": DocStatus.PROCESSED,
        "file_path": file_path,
    }
    res_delete = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert res_delete["status"] == "success"
    assert res_delete["media_files_deleted"] is True
    assert not unique_dir.exists()


@pytest.mark.asyncio
async def test_adelete_by_doc_id_cleans_doc_pre_id(tmp_path):
    """Pre-registration doc_status record (doc-pre-<filename>) is deleted alongside the doc."""
    doc_id = "doc-content-hash-123"
    file_name = "test_article.pdf"
    doc_pre_id = f"doc-pre-{file_name}"

    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": file_name},
            doc_pre_id: {"status": DocStatus.HANDLING, "file_path": file_name},
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id)
    assert result["status"] == "success"
    assert doc_pre_id in lightrag.doc_status.deleted_keys
    assert doc_pre_id not in lightrag.doc_status.records


@pytest.mark.asyncio
async def test_adelete_by_doc_id_delegates_to_lightrag(tmp_path):
    """LightRAG's adelete_by_doc_id is called with doc_id and delete_llm_cache flags."""
    doc_id = "doc-lr-delegate"
    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": "report.pdf"}
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id, delete_llm_cache=True)
    assert result["status"] == "success"
    assert lightrag.adelete_called_with == (doc_id, True)


@pytest.mark.asyncio
async def test_adelete_by_doc_id_fallback_when_lightrag_lacks_method(tmp_path):
    """When LightRAG lacks adelete_by_doc_id, falls back to direct storage deletion."""
    doc_id = "doc-fallback"
    # Barebones LightRAG without adelete_by_doc_id method
    bare_lightrag = SimpleNamespace(
        doc_status=InMemoryStorage(
            {doc_id: {"status": DocStatus.PROCESSED, "file_path": "simple.pdf"}}
        ),
        full_docs=InMemoryStorage({doc_id: {"content": "sample text"}}),
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(bare_lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id)
    assert result["status"] == "success"
    assert doc_id not in bare_lightrag.doc_status.records
    assert doc_id not in bare_lightrag.full_docs.records
    assert result["multimodal_status_deleted"] is True
