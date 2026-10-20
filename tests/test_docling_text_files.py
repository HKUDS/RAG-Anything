"""Docling batches discover .txt/.md files, so DoclingParser must parse them.

Like the other built-in parsers, it reads them directly through
``Parser.parse_text_file``; no Docling conversion is involved.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from raganything.batch_parser import BatchParser
from raganything.parser import DoclingParser
from raganything.processor import ProcessorMixin


def _write_text_files(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "notes.md").write_text("# Notes\n\nMarkdown body.\n", encoding="utf-8")
    (directory / "plain.txt").write_text("Plain text body.\n", encoding="utf-8")
    return directory / "notes.md", directory / "plain.txt"


def test_parse_document_reads_text_formats(tmp_path):
    markdown, plain = _write_text_files(tmp_path / "docs")
    parser = DoclingParser()

    md_items = parser.parse_document(markdown, output_dir=str(tmp_path / "out"))
    txt_items = parser.parse_document(plain, output_dir=str(tmp_path / "out"))

    assert md_items == parser.parse_text_file(markdown)
    assert "Markdown body." in " ".join(item.get("text", "") for item in md_items)
    assert txt_items == [{"type": "text", "text": "Plain text body.", "page_idx": 0}]


def test_docling_batch_parses_discovered_text_files(tmp_path):
    markdown, plain = _write_text_files(tmp_path / "docs")
    batch = BatchParser(
        parser_type="docling",
        max_workers=1,
        show_progress=False,
        skip_installation_check=True,
    )

    result = batch.process_batch([str(tmp_path / "docs")], str(tmp_path / "out"))

    assert sorted(result.successful_files) == sorted([str(markdown), str(plain)])
    assert result.failed_files == []
    assert result.errors == {}


class _Processor(ProcessorMixin):
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


@pytest.mark.asyncio
async def test_rag_parse_document_reads_text_files_with_docling(tmp_path):
    markdown, plain = _write_text_files(tmp_path / "docs")
    processor = _Processor()
    processor.config = SimpleNamespace(
        parser="docling",
        parser_output_dir=str(tmp_path / "out"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
    )
    processor.logger = logging.getLogger(__name__)
    processor.parse_cache = _MemoryCache()
    processor.doc_parser = DoclingParser()

    for path in (markdown, plain):
        content_list, doc_id = await processor.parse_document(str(path))
        assert content_list == processor.doc_parser.parse_text_file(path)
        assert doc_id.startswith("doc-")
