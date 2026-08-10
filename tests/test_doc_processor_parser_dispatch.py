"""Focused tests for per-file-type parser dispatch in the document processor.

Covers ``_file_type_for_path`` extension mapping, ``_effective_parser_name``
precedence (user per-type override > PDF_PARSER > global parser; video/generic
never overridden), the video short-circuit under a global ``opendataloader``
parser, the ``process_document_complete_lightrag_api`` config write, and the
DoclingParser HTML delegation fix.
"""

import os
import tempfile
from pathlib import Path

import pytest

from raganything.processor import ProcessorMixin


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def make_config(**overrides):
    defaults = {
        "parser": "docling",
        "pdf_parser": "",
        "parsers_by_type": {},
        "parser_output_dir": tempfile.gettempdir(),
        "parse_method": "auto",
        "display_content_stats": False,
        "ocr_quality_check_enabled": True,
        "use_full_path": False,
    }
    defaults.update(overrides)
    return type("Config", (), defaults)()


def make_processor(config=None):
    processor = type("DummyProcessor", (ProcessorMixin,), {})()
    processor.logger = FakeLogger()
    processor.config = config if config is not None else make_config()
    return processor


class TestFileTypeForPath:
    @pytest.mark.parametrize(
        ("file_path", "expected"),
        [
            ("sample.pdf", "pdf"),
            ("sample.PDF", "pdf"),
            ("sample.doc", "office"),
            ("sample.docx", "office"),
            ("sample.ppt", "office"),
            ("sample.pptx", "office"),
            ("sample.xls", "office"),
            ("sample.xlsx", "office"),
            ("sample.html", "office"),
            ("sample.htm", "office"),
            ("sample.xhtml", "office"),
            ("sample.jpg", "image"),
            ("sample.jpeg", "image"),
            ("sample.png", "image"),
            ("sample.bmp", "image"),
            ("sample.tiff", "image"),
            ("sample.tif", "image"),
            ("sample.gif", "image"),
            ("sample.webp", "image"),
            ("sample.mp4", "video"),
            ("sample.avi", "video"),
            ("sample.mov", "video"),
            ("sample.mkv", "video"),
            ("sample.webm", "video"),
            ("sample.txt", "generic"),
            ("sample.md", "generic"),
            ("sample.unknown", "generic"),
            ("no_extension", "generic"),
        ],
    )
    def test_maps_extension_to_type(self, file_path, expected):
        assert make_processor()._file_type_for_path(file_path) == expected


class TestEffectiveParserName:
    def test_user_override_wins_over_pdf_parser_and_global(self):
        processor = make_processor(
            make_config(
                parser="docling",
                pdf_parser="opendataloader",
                parsers_by_type={"pdf": "mineru"},
            )
        )
        assert processor._effective_parser_name("doc.pdf") == "mineru"
        assert processor._effective_parser_name("doc.docx") == "docling"
        assert processor._effective_parser_name("img.png") == "docling"

    def test_pdf_parser_applies_when_no_user_override(self):
        processor = make_processor(
            make_config(
                parser="docling", pdf_parser="opendataloader", parsers_by_type={}
            )
        )
        assert processor._effective_parser_name("doc.pdf") == "opendataloader"
        assert processor._effective_parser_name("doc.docx") == "docling"

    def test_global_parser_is_the_final_default(self):
        processor = make_processor(
            make_config(parser="mineru", pdf_parser="", parsers_by_type={})
        )
        assert processor._effective_parser_name("doc.pdf") == "mineru"
        assert processor._effective_parser_name("doc.docx") == "mineru"
        assert processor._effective_parser_name("img.png") == "mineru"
        assert processor._effective_parser_name("clip.mp4") == "mineru"
        assert processor._effective_parser_name("notes.txt") == "mineru"

    def test_office_override_does_not_affect_pdf(self):
        processor = make_processor(
            make_config(
                parser="docling",
                pdf_parser="opendataloader",
                parsers_by_type={"office": "mineru"},
            )
        )
        assert processor._effective_parser_name("doc.docx") == "mineru"
        assert processor._effective_parser_name("doc.pdf") == "opendataloader"

    def test_video_and_generic_never_use_per_type_override(self):
        processor = make_processor(
            make_config(
                parser="docling",
                parsers_by_type={
                    "video": "opendataloader",
                    "generic": "opendataloader",
                    "office": "mineru",
                },
            )
        )
        assert processor._effective_parser_name("clip.mp4") == "docling"
        assert processor._effective_parser_name("notes.txt") == "docling"
        assert processor._effective_parser_name("notes.md") == "docling"

    def test_empty_per_type_override_falls_back_to_pdf_parser(self):
        processor = make_processor(
            make_config(
                parser="docling",
                pdf_parser="opendataloader",
                parsers_by_type={"pdf": ""},
            )
        )
        assert processor._effective_parser_name("doc.pdf") == "opendataloader"


@pytest.mark.asyncio
async def test_video_short_circuits_before_odl_guard():
    """A video never instantiates a parser nor trips the ODL guard."""
    processor = make_processor(
        make_config(parser="opendataloader", pdf_parser="", parsers_by_type={})
    )
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        handle.write(b"dummy video bytes")
        video_path = handle.name
    try:
        content_list, doc_id = await processor.parse_document(video_path)
        assert content_list == [{"type": "video", "video_path": str(Path(video_path))}]
        assert doc_id
        # The parser was never instantiated for the video path
        assert not hasattr(processor, "doc_parser")
    finally:
        os.unlink(video_path)


class FakeDocStatusStorage:
    def __init__(self):
        self.records = {}
        self.index_done_calls = 0

    async def get_by_id(self, key):
        return self.records.get(key)

    async def upsert(self, data):
        self.records.update(data)

    async def index_done_callback(self):
        self.index_done_calls += 1


@pytest.mark.asyncio
async def test_lightrag_api_writes_parsers_by_type_into_config():
    class DummyProcessor(ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.logger = FakeLogger()
    processor.config = make_config(parser="docling", parsers_by_type={})
    processor.lightrag = type(
        "FakeLightRAG",
        (),
        {"doc_status": FakeDocStatusStorage()},
    )()

    async def fake_ensure_lightrag_initialized():
        return {"success": False, "error": "missing llm_model_func"}

    processor._ensure_lightrag_initialized = fake_ensure_lightrag_initialized

    result = await processor.process_document_complete_lightrag_api(
        "sample.pdf",
        parser="mineru",
        parsers_by_type={"office": "paddleocr"},
    )

    assert result is False
    assert processor.config.parser == "mineru"
    assert processor.config.parsers_by_type == {"office": "paddleocr"}


def test_docling_parse_office_delegates_html_to_parse_html(tmp_path):
    from raganything.parser.office_parser import DoclingParser

    parser = DoclingParser()
    calls = []

    def fake_parse_html(html_path=None, output_dir=None, lang=None, **kwargs):
        calls.append((str(html_path), output_dir, lang))
        return [{"type": "text", "text": "html content"}]

    parser.parse_html = fake_parse_html

    html_file = tmp_path / "sample.html"
    html_file.write_text("<html><body>hello</body></html>", encoding="utf-8")

    result = parser.parse_office_doc(doc_path=html_file, output_dir=str(tmp_path))

    assert result == [{"type": "text", "text": "html content"}]
    assert len(calls) == 1
    assert Path(calls[0][0]) == html_file
