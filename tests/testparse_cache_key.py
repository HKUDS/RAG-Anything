"""Regression tests for parse-cache file identity."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

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
