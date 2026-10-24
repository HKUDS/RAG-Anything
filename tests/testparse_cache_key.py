"""Regression tests for parse-cache file identity."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from lightrag.utils import compute_mdhash_id

from raganything.processor import ProcessorMixin


class _Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _MemoryCache:
    def __init__(self):
        self.entries = {}

    async def get_by_id(self, key):
        return self.entries.get(key)

    async def upsert(self, entries):
        self.entries.update(entries)

    async def index_done_callback(self):
        pass


class _TextParser:
    def __init__(self):
        self.calls = 0

    def parse_document(self, file_path, **kwargs):
        self.calls += 1
        return [{"type": "text", "text": Path(file_path).read_text(encoding="utf-8")}]


class _Processor(ProcessorMixin):
    pass


def _make_processor(tmp_path):
    processor = _Processor()
    processor.config = SimpleNamespace(
        parser="test",
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
    )
    processor.logger = _Logger()
    processor.parse_cache = _MemoryCache()
    processor.doc_parser = _TextParser()
    return processor


@pytest.mark.asyncio
async def test_parse_cache_reuses_unchanged_file(tmp_path):
    processor = _make_processor(tmp_path)
    document = tmp_path / "document.txt"
    document.write_text("alpha", encoding="utf-8")

    first_result = await processor.parse_document(str(document))
    second_result = await processor.parse_document(str(document))

    assert processor.doc_parser.calls == 1
    assert second_result == first_result


@pytest.mark.asyncio
async def test_parse_cache_invalidates_when_content_changes_with_preserved_mtime(
    tmp_path,
):
    processor = _make_processor(tmp_path)
    document = tmp_path / "document.txt"
    document.write_text("alpha", encoding="utf-8")
    original_stat = document.stat()

    first_content, first_doc_id = await processor.parse_document(str(document))

    document.write_text("bravo", encoding="utf-8")
    os.utime(
        document,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    second_content, second_doc_id = await processor.parse_document(str(document))

    assert processor.doc_parser.calls == 2
    assert first_content != second_content
    assert first_doc_id != second_doc_id
    assert second_content == [{"type": "text", "text": "bravo"}]


@pytest.mark.asyncio
async def test_replaced_image_does_not_reuse_processed_document(tmp_path):
    processor = _make_processor(tmp_path)
    calls = []

    class ImageParser:
        def parse_image(self, image_path, **kwargs):
            calls.append(image_path)
            return [{"type": "image", "img_path": str(image_path)}]

    processor.doc_parser = ImageParser()
    document = tmp_path / "diagram.png"
    Image.new("RGB", (2, 2), "red").save(document)
    original_stat = document.stat()
    first_content, first_id = await processor.parse_document(str(document))

    Image.new("RGB", (2, 2), "blue").save(document)
    os.utime(document, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second_content, second_id = await processor.parse_document(str(document))
    assert first_content == second_content  # Same parser output path, different pixels.
    assert len(calls) == 2  # The parse cache correctly detects changed source bytes.

    async def get_status(doc_id):
        return {"multimodal_processed": True} if doc_id == first_id else None

    processor.lightrag = SimpleNamespace(
        doc_status=SimpleNamespace(get_by_id=get_status)
    )
    processor._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    processor._process_multimodal_content_batch_type_aware = AsyncMock()
    processor._mark_multimodal_processing_complete = AsyncMock()
    await processor._process_multimodal_content(
        second_content, str(document), second_id
    )
    processor._process_multimodal_content_batch_type_aware.assert_awaited_once()
    assert second_id != first_id
    assert await processor.parse_document(str(document)) == (second_content, second_id)
    assert len(calls) == 2


@pytest.mark.parametrize("image_path", ["missing.png", "https://example.com/image.png"])
def test_unavailable_image_keeps_path_identity(tmp_path, image_path):
    processor = _make_processor(tmp_path)
    assert processor._generate_content_based_doc_id(
        [{"type": "image", "img_path": image_path}]
    ) == compute_mdhash_id(f"image:{image_path}", prefix="doc-")
