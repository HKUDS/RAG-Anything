"""HTML is accepted only by parsers with a native parse_html (Docling).

parse_document routes HTML to parse_html. MinerU and PaddleOCR could only
read HTML by converting it to PDF with LibreOffice, which fetches remote URLs
and embeds local files referenced by the page, so every path into them must
refuse HTML before any conversion runs.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import raganything.parser as parser_module
from raganything.batch_parser import BatchParser
from raganything.parser import MineruParser, PaddleOCRParser, Parser
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

# The error names the settings that select Docling (config/env; the CLI test
# checks --parser): a per-call parser= argument does not switch parsers.
_DOCLING_HINT = r"RAGAnythingConfig\(parser='docling'\) or the PARSER=docling"


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
@pytest.mark.parametrize("ext", [".html", ".htm", ".xhtml", ".HTML"])
async def test_html_rejected_without_parse_html(tmp_path, ext):
    parser = _OfficeOnlyParser()
    processor = _make_processor(tmp_path, parser)
    doc = tmp_path / f"page{ext}"
    doc.write_text("<html><body>hello</body></html>")

    with pytest.raises(ValueError, match=_DOCLING_HINT):
        await processor.parse_document(str(doc))

    assert parser.calls == []


@pytest.fixture
def no_libreoffice(monkeypatch):
    """Fail the test if anything tries to launch LibreOffice (or any process)."""
    launched = []

    def fake_run(cmd, **kwargs):
        launched.append(cmd)
        raise AssertionError(f"subprocess launched for HTML: {cmd}")

    monkeypatch.setattr(parser_module.subprocess, "run", fake_run)
    monkeypatch.setattr(parser_module.subprocess, "Popen", fake_run)
    return launched


def _fail_parse_pdf(self, *args, **kwargs):
    raise AssertionError("HTML must not reach parse_pdf")


@pytest.mark.parametrize("parser_cls", [MineruParser, PaddleOCRParser])
@pytest.mark.parametrize("entry_point", ["parse_document", "parse_office_doc"])
@pytest.mark.parametrize("ext", [".html", ".htm", ".xhtml", ".XHTML"])
def test_direct_parser_paths_reject_html(
    tmp_path, monkeypatch, no_libreoffice, parser_cls, entry_point, ext
):
    monkeypatch.setattr(parser_cls, "parse_pdf", _fail_parse_pdf)
    doc = tmp_path / f"page{ext}"
    doc.write_text('<img src="http://127.0.0.1:9/canary.png">')

    with pytest.raises(ValueError, match=_DOCLING_HINT):
        getattr(parser_cls(), entry_point)(doc, output_dir=str(tmp_path / "out"))

    assert no_libreoffice == []
    assert not (tmp_path / "out").exists()


def test_convert_office_to_pdf_rejects_html(tmp_path, no_libreoffice):
    doc = tmp_path / "page.htm"
    doc.write_text("<p>hello</p>")

    with pytest.raises(ValueError, match=_DOCLING_HINT):
        Parser.convert_office_to_pdf(doc, str(tmp_path / "out"))

    assert no_libreoffice == []


def test_parser_cli_rejects_html_for_mineru(
    tmp_path, monkeypatch, capsys, no_libreoffice
):
    doc = tmp_path / "page.html"
    doc.write_text("<p>hello</p>")
    monkeypatch.setattr(
        "sys.argv", ["raganything.parser", str(doc), "--parser", "mineru"]
    )

    assert parser_module.main() == 1
    # The hint names the CLI flag as well as the config and env spellings.
    out = capsys.readouterr().out
    assert "--parser docling" in out
    assert "RAGAnythingConfig(parser='docling')" in out
    assert "PARSER=docling" in out
    assert no_libreoffice == []


@pytest.mark.parametrize(
    "parser_type, html_advertised",
    [("mineru", False), ("paddleocr", False), ("docling", True)],
)
def test_batch_discovery_advertises_html_only_for_docling(parser_type, html_advertised):
    batch_parser = BatchParser(
        parser_type=parser_type, show_progress=False, skip_installation_check=True
    )

    extensions = set(batch_parser.get_supported_extensions())
    html = {".html", ".htm", ".xhtml"}

    if html_advertised:
        # Docling discovers exactly the suffixes the other parsers reject.
        assert set(batch_parser.parser.HTML_FORMATS) == html
        assert parser_module.HTML_FILE_EXTENSIONS == html
        assert html <= extensions
    else:
        assert not extensions & html
    # Discovery follows the native HTML entry point, nothing else.
    assert hasattr(batch_parser.parser, "parse_html") is html_advertised
