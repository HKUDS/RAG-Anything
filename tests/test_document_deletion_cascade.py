"""Tests for cascading document deletion in RAG-Anything (#127, #332).

Ensures that calling adelete_by_doc_id:
- delegates core deletion to LightRAG.adelete_by_doc_id first
- retains multimodal_status_cache, media directories, and doc-pre placeholders
  whenever core deletion raises or returns a non-success status (e.g. fail, busy, not_allowed)
- refuses false-positive partial deletion when LightRAG lacks adelete_by_doc_id
- resolves actual parsed output directories across nested source paths (with default
  use_full_path=False), per-call output_dir overrides, Office intermediate PDF dirs,
  and persisted parse_cache / doc_status metadata
- invalidates stale parse_cache entries when media files on disk are deleted
"""

from types import SimpleNamespace
import os

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

    async def get_docs_paginated(self, page=1, page_size=200):
        records = list(self.records.items())
        selected = records[(page - 1) * page_size : page * page_size]
        return [
            (key, SimpleNamespace(metadata=value.get("metadata", {})))
            for key, value in selected
        ], len(records)


class FakeDeletionResult:
    def __init__(
        self,
        status="success",
        doc_id="doc-1",
        message="Deleted",
        status_code=200,
        file_path="sample.pdf",
    ):
        self.status = status
        self.doc_id = doc_id
        self.message = message
        self.status_code = status_code
        self.file_path = file_path


class FakeLightRAG:
    def __init__(self, doc_status_records=None, full_docs_records=None):
        self.doc_status = InMemoryStorage(doc_status_records)
        self.full_docs = InMemoryStorage(full_docs_records)
        self.adelete_called_with = None
        self.call_order = []

    async def adelete_by_doc_id(self, doc_id, delete_llm_cache=False):
        self.adelete_called_with = (doc_id, delete_llm_cache)
        self.call_order.append("lightrag.adelete_by_doc_id")
        if (
            doc_id not in self.doc_status.records
            and doc_id not in self.full_docs.records
        ):
            return FakeDeletionResult(
                status="not_found",
                doc_id=doc_id,
                message=f"Document {doc_id} not found",
                status_code=404,
            )
        await self.doc_status.delete([doc_id])
        await self.full_docs.delete([doc_id])
        return FakeDeletionResult(doc_id=doc_id)


class DummyProcessor(ProcessorMixin):
    def __init__(self, lightrag, multimodal_cache, tmp_path, parse_cache=None):
        self.lightrag = lightrag
        self.multimodal_status_cache = multimodal_cache
        self.parse_cache = parse_cache if parse_cache is not None else InMemoryStorage()
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
@pytest.mark.parametrize("core_result", [None, {}, {"message": "no status"}, True])
async def test_unconfirmed_core_result_preserves_all_project_data(
    tmp_path, core_result
):
    doc_id = "doc-unconfirmed"
    file_path = str(tmp_path / "source.pdf")
    output_dir = tmp_path / "output"
    media_dir = Parser._unique_output_dir(output_dir, file_path)
    media_dir.mkdir(parents=True)
    (media_dir / "image.png").write_bytes(b"media")
    placeholder = "doc-pre-source.pdf"
    lr = FakeLightRAG(
        doc_status_records={doc_id: {"file_path": file_path}, placeholder: {}},
        full_docs_records={doc_id: {"content": "content"}},
    )

    async def unconfirmed(*args, **kwargs):
        return core_result

    lr.adelete_by_doc_id = unconfirmed
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lr, cache, tmp_path)
    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == "failed"
    assert media_dir.exists()
    assert doc_id in cache.records
    assert doc_id in lr.doc_status.records
    assert placeholder in lr.doc_status.records


@pytest.mark.asyncio
async def test_basename_only_record_never_deletes_another_documents_output(tmp_path):
    doc_id = "doc-without-location"
    other_source = tmp_path / "other" / "report.pdf"
    output_dir = tmp_path / "output"
    other_dir = Parser._unique_output_dir(output_dir, other_source)
    other_dir.mkdir(parents=True)
    (other_dir / "image.png").write_bytes(b"other document")
    parse_cache = InMemoryStorage(
        {
            "other-cache-key": {
                "doc_id": "doc-other",
                "file_path": str(other_source),
                "output_dir": str(output_dir),
                "parsed_output_dirs": [str(other_dir)],
            }
        }
    )
    lr = FakeLightRAG(doc_status_records={doc_id: {"file_path": "report.pdf"}})
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lr, cache, tmp_path, parse_cache=parse_cache)
    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == "success"
    assert result["media_files_deleted"] is False
    assert other_dir.exists()
    assert "other-cache-key" in parse_cache.records


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.parametrize("suffix", [".pdf", ".docx"])
async def test_failed_media_removal_is_not_reported_as_deleted(tmp_path, suffix):
    if os.geteuid() == 0:
        pytest.skip("root can remove files from read-only directories")
    doc_id = "doc-readonly"
    file_path = str(tmp_path / ("source" + suffix))
    lr = FakeLightRAG(doc_status_records={doc_id: {"file_path": file_path}})
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lr, cache, tmp_path)
    base, dirs = processor._compute_parsed_output_dirs(file_path)
    for directory in dirs:
        directory.mkdir(parents=True)
        (directory / "image.png").write_bytes(b"media")
    processor._record_parsed_output_location(doc_id, file_path, base)
    denied = dirs[-1]
    denied.chmod(0o500)
    try:
        result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
        assert result["status"] == "success"
        assert result["media_files_deleted"] is False
        assert (denied / "image.png").exists()
    finally:
        denied.chmod(0o700)


@pytest.mark.asyncio
async def test_output_used_by_another_indexed_document_is_preserved(tmp_path):
    source = str(tmp_path / "report.pdf")
    output = tmp_path / "output"
    directory = Parser._unique_output_dir(output, source)
    directory.mkdir(parents=True)
    (directory / "image.png").write_bytes(b"shared media")
    metadata = {
        "raganything_output_base": str(output),
        "raganything_parsed_output_dirs": [str(directory)],
    }
    lr = FakeLightRAG(
        doc_status_records={
            "old": {"file_path": "report.pdf", "metadata": metadata},
            "new": {"file_path": "report.pdf", "metadata": metadata},
        }
    )
    cache = InMemoryStorage({"old": {"multimodal_processed": True}})
    processor = DummyProcessor(lr, cache, tmp_path)
    result = await processor.adelete_by_doc_id("old", delete_media_files=True)
    assert result["status"] == "success"
    assert result["media_files_deleted"] is False
    assert directory.exists()
    assert "new" in lr.doc_status.records


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
    assert result["lightrag_result"] is None


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
    file_path = str(tmp_path / "document.pdf")
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
async def test_adelete_by_doc_id_retains_media_cache_and_placeholders_when_core_deletion_raises(
    tmp_path,
):
    """If LightRAG.adelete_by_doc_id raises, media, cache, and doc-pre records must be retained."""
    doc_id = "doc-raise-test"
    file_name = "important.pdf"
    doc_pre_id = f"doc-pre-{file_name}"
    output_dir = tmp_path / "output"
    unique_dir = Parser._unique_output_dir(output_dir, file_name)
    unique_dir.mkdir(parents=True, exist_ok=True)
    (unique_dir / "extracted_table.png").write_text("image bytes")

    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": file_name},
            doc_pre_id: {"status": DocStatus.HANDLING, "file_path": file_name},
        },
        full_docs_records={doc_id: {"content": "full text"}},
    )

    should_fail = True
    original_adelete = lightrag.adelete_by_doc_id

    async def flaky_adelete(target_doc_id, delete_llm_cache=False):
        if should_fail:
            raise RuntimeError("Graph database connection lost before deleting graph")
        return await original_adelete(target_doc_id, delete_llm_cache=delete_llm_cache)

    lightrag.adelete_by_doc_id = flaky_adelete
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)
    processor._record_parsed_output_location(doc_id, file_name, output_dir)

    # 1. Core deletion raises -> nothing in RAG-Anything should be lost
    failed_result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert failed_result["status"] == "failed"
    assert "Successfully processed deletion" not in failed_result["message"]
    assert "Graph database connection lost" in failed_result["message"]
    assert failed_result["multimodal_status_deleted"] is False
    assert failed_result["media_files_deleted"] is False
    assert unique_dir.exists()
    assert doc_id in cache.records
    assert doc_pre_id in lightrag.doc_status.records
    assert doc_id in lightrag.doc_status.records

    # 2. Retry after transient failure recovers -> everything is now cleaned up
    should_fail = False
    retry_result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert retry_result["status"] == "success"
    assert retry_result["multimodal_status_deleted"] is True
    assert retry_result["media_files_deleted"] is True
    assert not unique_dir.exists()
    assert doc_id not in cache.records
    assert doc_pre_id not in lightrag.doc_status.records
    assert doc_id not in lightrag.doc_status.records


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lr_status", "lr_code", "lr_message"),
    [
        ("fail", 500, "Failed to delete entities from graph storage"),
        ("failed", 500, "Vector storage deletion error"),
        ("not_allowed", 409, "Cannot delete document while pipeline is busy"),
        ("busy", 409, "Pipeline is currently processing documents"),
    ],
)
async def test_adelete_by_doc_id_retains_state_on_unsuccessful_or_busy_lightrag_status(
    tmp_path, lr_status, lr_code, lr_message
):
    """Non-success statuses from LightRAG.adelete_by_doc_id must retain media, cache, and placeholders."""
    doc_id = f"doc-{lr_status}"
    file_name = "busy_doc.pdf"
    doc_pre_id = f"doc-pre-{file_name}"
    output_dir = tmp_path / "output"
    unique_dir = Parser._unique_output_dir(output_dir, file_name)
    unique_dir.mkdir(parents=True, exist_ok=True)
    (unique_dir / "fig.png").write_text("figure")

    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": file_name},
            doc_pre_id: {"status": DocStatus.HANDLING, "file_path": file_name},
        }
    )

    async def unsuccessful_adelete(target_doc_id, delete_llm_cache=False):
        return FakeDeletionResult(
            status=lr_status,
            doc_id=target_doc_id,
            message=lr_message,
            status_code=lr_code,
        )

    lightrag.adelete_by_doc_id = unsuccessful_adelete
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == lr_status
    assert result["message"] == lr_message
    assert result["multimodal_status_deleted"] is False
    assert result["media_files_deleted"] is False
    assert unique_dir.exists()
    assert doc_id in cache.records
    assert doc_pre_id in lightrag.doc_status.records


@pytest.mark.asyncio
async def test_adelete_by_doc_id_fails_without_false_positive_when_lightrag_lacks_method(
    tmp_path,
):
    """When LightRAG lacks adelete_by_doc_id, do not partially delete doc_status/full_docs or claim success."""
    doc_id = "doc-no-adelete"
    file_name = "simple.pdf"
    output_dir = tmp_path / "output"
    unique_dir = Parser._unique_output_dir(output_dir, file_name)
    unique_dir.mkdir(parents=True, exist_ok=True)
    (unique_dir / "page.png").write_text("img")

    bare_lightrag = SimpleNamespace(
        doc_status=InMemoryStorage(
            {doc_id: {"status": DocStatus.PROCESSED, "file_path": file_name}}
        ),
        full_docs=InMemoryStorage({doc_id: {"content": "sample text"}}),
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(bare_lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == "failed"
    assert result["multimodal_status_deleted"] is False
    assert result["media_files_deleted"] is False
    assert doc_id in bare_lightrag.doc_status.records
    assert doc_id in bare_lightrag.full_docs.records
    assert doc_id in cache.records
    assert unique_dir.exists()


@pytest.mark.asyncio
async def test_adelete_by_doc_id_resolves_nested_source_path_and_custom_output_dir(
    tmp_path,
):
    """With default use_full_path=False (basename-only in doc_status) and a per-call output_dir override,
    adelete_by_doc_id deletes the actual parsed output directory for the nested source path.
    """
    nested_dir = tmp_path / "nested" / "subdir"
    nested_dir.mkdir(parents=True, exist_ok=True)
    source_file = nested_dir / "paper.pdf"
    source_file.write_bytes(b"%PDF-1.4 sample nested pdf")

    custom_output_dir = tmp_path / "custom_parsed_output"
    actual_unique_dir = Parser._unique_output_dir(custom_output_dir, source_file)

    doc_id = "doc-nested-custom-out"
    lightrag = FakeLightRAG(
        doc_status_records={
            # Default use_full_path=False stores only basename "paper.pdf" in doc_status
            doc_id: {"status": DocStatus.PROCESSED, "file_path": "paper.pdf"}
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    class StubParser:
        def parse_pdf(self, pdf_path, output_dir=None, method="auto", **kwargs):
            target_dir = Parser._unique_output_dir(output_dir, pdf_path)
            target_dir.mkdir(parents=True, exist_ok=True)
            img_file = target_dir / "fig1.png"
            img_file.write_text("extracted image")
            return [
                {"type": "text", "text": "Nested paper text", "page_idx": 0},
                {"type": "image", "img_path": str(img_file), "page_idx": 0},
            ]

    processor.doc_parser = StubParser()

    _content_list, parsed_doc_id = await processor.parse_document(
        file_path=str(source_file),
        output_dir=str(custom_output_dir),
    )
    assert actual_unique_dir.exists()

    # Bind the custom doc_id as process_document_complete does
    processor._record_parsed_output_location(
        doc_id,
        str(source_file),
        str(custom_output_dir),
        fallback_doc_id=parsed_doc_id,
    )

    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == "success"
    assert result["media_files_deleted"] is True
    assert not actual_unique_dir.exists()


@pytest.mark.asyncio
async def test_adelete_by_doc_id_preserves_same_basename_file_in_other_directory(
    tmp_path,
):
    """When two documents in different directories share the same basename under use_full_path=False,
    deleting one document must only remove its own parsed output directory."""
    dir_a = tmp_path / "dept_a"
    dir_b = tmp_path / "dept_b"
    dir_a.mkdir(parents=True, exist_ok=True)
    dir_b.mkdir(parents=True, exist_ok=True)
    file_a = dir_a / "report.pdf"
    file_b = dir_b / "report.pdf"
    file_a.write_bytes(b" PDF A ")
    file_b.write_bytes(b" PDF B ")

    output_base = tmp_path / "output"
    unique_dir_a = Parser._unique_output_dir(output_base, file_a)
    unique_dir_b = Parser._unique_output_dir(output_base, file_b)
    unique_dir_a.mkdir(parents=True, exist_ok=True)
    unique_dir_b.mkdir(parents=True, exist_ok=True)
    (unique_dir_a / "a.png").write_text("A")
    (unique_dir_b / "b.png").write_text("B")

    doc_a = "doc-dept-a"
    doc_b = "doc-dept-b"
    lightrag = FakeLightRAG(
        doc_status_records={
            doc_a: {"status": DocStatus.PROCESSED, "file_path": "report.pdf"},
            doc_b: {"status": DocStatus.PROCESSED, "file_path": "report.pdf"},
        }
    )
    cache = InMemoryStorage(
        {
            doc_a: {"multimodal_processed": True},
            doc_b: {"multimodal_processed": True},
        }
    )
    processor = DummyProcessor(lightrag, cache, tmp_path)
    processor._record_parsed_output_location(doc_a, file_a, output_base)
    processor._record_parsed_output_location(doc_b, file_b, output_base)

    res_a = await processor.adelete_by_doc_id(doc_a, delete_media_files=True)
    assert res_a["status"] == "success"
    assert res_a["media_files_deleted"] is True
    assert not unique_dir_a.exists()
    assert unique_dir_b.exists()


@pytest.mark.asyncio
async def test_adelete_by_doc_id_resolves_from_persisted_parse_cache_and_invalidates_cache(
    tmp_path,
):
    """After a processor restart (no in-memory _parsed_output_locations), adelete_by_doc_id
    resolves custom output_dir and nested source path from persisted parse_cache and invalidates
    the stale parse_cache entry so subsequent re-ingestion re-parses the document."""
    nested_dir = tmp_path / "archive" / "2026"
    nested_dir.mkdir(parents=True, exist_ok=True)
    source_file = nested_dir / "slides.pdf"
    source_file.write_bytes(b"%PDF-1.4 slides")

    custom_output = tmp_path / "custom_slides_out"
    shared_parse_cache = InMemoryStorage()

    parse_calls = 0

    class CountingStubParser:
        def parse_pdf(self, pdf_path, output_dir=None, method="auto", **kwargs):
            nonlocal parse_calls
            parse_calls += 1
            target_dir = Parser._unique_output_dir(output_dir, pdf_path)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "slide1.png").write_text("slide image")
            return [{"type": "text", "text": "Slide deck content", "page_idx": 0}]

    # First processor instance parses and populates shared_parse_cache
    lightrag = FakeLightRAG()
    cache = InMemoryStorage()
    processor_1 = DummyProcessor(
        lightrag, cache, tmp_path, parse_cache=shared_parse_cache
    )
    processor_1.doc_parser = CountingStubParser()

    _, doc_id = await processor_1.parse_document(
        file_path=str(source_file),
        output_dir=str(custom_output),
    )
    actual_unique_dir = Parser._unique_output_dir(custom_output, source_file)
    assert actual_unique_dir.exists()
    assert parse_calls == 1
    assert len(shared_parse_cache.records) == 1

    # Simulate doc_status having only basename "slides.pdf" and a fresh processor instance
    lightrag.doc_status.records[doc_id] = {
        "status": DocStatus.PROCESSED,
        "file_path": "slides.pdf",
    }
    cache.records[doc_id] = {"multimodal_processed": True}

    processor_2 = DummyProcessor(
        lightrag, cache, tmp_path, parse_cache=shared_parse_cache
    )
    processor_2.doc_parser = CountingStubParser()

    del_result = await processor_2.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert del_result["status"] == "success"
    assert del_result["media_files_deleted"] is True
    assert not actual_unique_dir.exists()
    assert len(shared_parse_cache.records) == 0

    # Re-parsing after media deletion must invoke the parser again to recreate the directory
    await processor_2.parse_document(
        file_path=str(source_file),
        output_dir=str(custom_output),
    )
    assert parse_calls == 2
    assert actual_unique_dir.exists()


@pytest.mark.asyncio
async def test_adelete_by_doc_id_cleans_office_document_both_output_dirs(tmp_path):
    """Office documents create both a conversion dir (<stem>_<doc_hash>) and a PDF parse dir
    (<stem>_<converted_pdf_hash>); both must be removed when delete_media_files=True."""
    nested_dir = tmp_path / "office_docs"
    nested_dir.mkdir(parents=True, exist_ok=True)
    docx_file = nested_dir / "quarterly_review.docx"
    docx_file.write_bytes(b"fake docx content")

    custom_out = tmp_path / "office_output"
    primary_dir = Parser._unique_output_dir(custom_out, docx_file)
    converted_pdf = primary_dir / "quarterly_review.pdf"
    secondary_dir = Parser._unique_output_dir(custom_out, converted_pdf)

    primary_dir.mkdir(parents=True, exist_ok=True)
    converted_pdf.write_bytes(b"%PDF-1.4 converted")
    secondary_dir.mkdir(parents=True, exist_ok=True)
    (secondary_dir / "chart.png").write_text("chart image")

    doc_id = "doc-office-1"
    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {
                "status": DocStatus.PROCESSED,
                "file_path": "quarterly_review.docx",
            }
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)
    processor._record_parsed_output_location(doc_id, docx_file, custom_out)

    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == "success"
    assert result["media_files_deleted"] is True
    assert not primary_dir.exists()
    assert not secondary_dir.exists()


@pytest.mark.asyncio
async def test_adelete_by_doc_id_cleans_orphaned_multimodal_cache_only_record(tmp_path):
    """When a document only exists as an orphaned record in multimodal_status_cache
    (absent from LightRAG doc_status/full_docs), adelete_by_doc_id cleans it up."""
    doc_id = "doc-orphaned-mm"
    lightrag = FakeLightRAG()
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    result = await processor.adelete_by_doc_id(doc_id)
    assert result["status"] == "success"
    assert result["multimodal_status_deleted"] is True
    assert doc_id not in cache.records


@pytest.mark.asyncio
async def test_adelete_by_doc_id_handles_lightrag_initialization_failure(tmp_path):
    """If _ensure_lightrag_initialized fails, adelete_by_doc_id returns status='failed' immediately."""
    doc_id = "doc-init-fail"
    lightrag = FakeLightRAG(
        doc_status_records={
            doc_id: {"status": DocStatus.PROCESSED, "file_path": "doc.pdf"}
        }
    )
    cache = InMemoryStorage({doc_id: {"multimodal_processed": True}})
    processor = DummyProcessor(lightrag, cache, tmp_path)

    async def fail_init():
        return {"success": False, "error": "Failed to initialize storage backends"}

    processor._ensure_lightrag_initialized = fail_init

    result = await processor.adelete_by_doc_id(doc_id, delete_media_files=True)
    assert result["status"] == "failed"
    assert "Failed to initialize storage backends" in result["message"]
    assert result["multimodal_status_deleted"] is False
    assert result["media_files_deleted"] is False
    assert doc_id in cache.records
    assert doc_id in lightrag.doc_status.records
