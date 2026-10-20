"""HTML files route to parse_html when the parser provides it.

DoclingParser.parse_office_doc rejects HTML, so parse_document must call
the dedicated parse_html entry point; parsers without it (MinerU) keep the
Office/LibreOffice fallback.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from raganything.processor import ProcessorMixin


class _Logger:
    def debug(self, *a, **k):
        pass

    info = warning = error = debug


class _MemoryCache:
    def __init__(self):
        self.entries = {}

    async def get_by_id(self, key):
        return self.entries.get(key)

    async def upsert(self, entries):
        self.entries.update(entries)

    async def index_done_callback(self):
        pass


_BLOCK = [{"type": "text", "text": "hello", "page_idx": 0}]


class _HtmlParser:
    def __init__(self):
        self.calls = []

    def parse_html(self, html_path, output_dir=None, **kwargs):
        self.calls.append(("parse_html", Path(html_path)))
        self.forwarded = (output_dir, kwargs)
        return list(_BLOCK)

    def parse_office_doc(self, doc_path, output_dir=None, **kwargs):
        raise AssertionError("parse_office_doc must not be used for HTML")


class _OfficeOnlyParser:
    def __init__(self):
        self.calls = []

    def parse_office_doc(self, doc_path, output_dir=None, **kwargs):
        self.calls.append(("parse_office_doc", Path(doc_path)))
        return list(_BLOCK)


class _Processor(ProcessorMixin):
    pass


def _make_processor(tmp_path, parser):
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
    processor.doc_parser = parser
    return processor


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", [".html", ".htm", ".xhtml"])
async def test_html_uses_parse_html_when_available(tmp_path, ext):
    parser = _HtmlParser()
    processor = _make_processor(tmp_path, parser)
    doc = tmp_path / f"page{ext}"
    doc.write_text("<html><body>hello</body></html>")

    content_list, _ = await processor.parse_document(str(doc), lang="en")

    assert parser.calls == [("parse_html", doc)]
    assert content_list[0]["text"] == "hello"
    # The output directory and caller options reach the HTML parser too.
    output_dir, kwargs = parser.forwarded
    assert output_dir == str(tmp_path / "output")
    assert kwargs.get("lang") == "en"


@pytest.mark.asyncio
async def test_html_falls_back_to_office_without_parse_html(tmp_path):
    parser = _OfficeOnlyParser()
    processor = _make_processor(tmp_path, parser)
    doc = tmp_path / "page.html"
    doc.write_text("<html><body>hello</body></html>")

    await processor.parse_document(str(doc))

    assert parser.calls == [("parse_office_doc", doc)]
