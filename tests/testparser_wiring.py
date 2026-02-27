import pytest

from raganything.batch_parser import BatchParser


def test_batch_parser_uses_paddleocr_parser():
    batch_parser = BatchParser(
        parser_type="paddleocr",
        show_progress=False,
        skip_installation_check=True,
    )
    assert batch_parser.parser.__class__.__name__ == "PaddleOCRParser"


def test_raganything_initializes_selected_parser(monkeypatch, tmp_path):
    pytest.importorskip("lightrag")

    import raganything.raganything as rag_module
    from raganything.config import RAGAnythingConfig

    class StubParser:
        def check_installation(self):
            return True

    captured = {}

    def fake_get_parser(parser_name):
        captured["parser_name"] = parser_name
        return StubParser()

    monkeypatch.setattr(rag_module, "get_parser", fake_get_parser)
    monkeypatch.setattr(rag_module.atexit, "register", lambda *args, **kwargs: None)

    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag_workdir"),
        parser="paddleocr",
    )
    rag = rag_module.RAGAnything(config=config)

    assert captured["parser_name"] == "paddleocr"
    assert isinstance(rag.doc_parser, StubParser)


@pytest.mark.asyncio
async def test_processor_parse_document_uses_selected_parser(monkeypatch, tmp_path):
    import raganything.processor as processor_module

    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

    class FakeParser:
        def parse_pdf(self, **kwargs):
            return [{"type": "text", "text": "parsed by fake parser", "page_idx": 0}]

        def parse_image(self, **kwargs):
            return [{"type": "text", "text": "image parsed", "page_idx": 0}]

        def parse_office_doc(self, **kwargs):
            return [{"type": "text", "text": "office parsed", "page_idx": 0}]

        def parse_document(self, **kwargs):
            return [{"type": "text", "text": "generic parsed", "page_idx": 0}]

    selected = {"calls": 0}

    def fake_get_parser(parser_name):
        selected["parser_name"] = parser_name
        selected["calls"] += 1
        return FakeParser()

    monkeypatch.setattr(processor_module, "get_parser", fake_get_parser)

    class DummyProcessor(processor_module.ProcessorMixin):
        pass

    dummy = DummyProcessor()
    dummy.config = type(
        "Config",
        (),
        {
            "parser": "paddleocr",
            "parser_output_dir": str(tmp_path / "output"),
            "parse_method": "auto",
            "display_content_stats": False,
            "use_full_path": False,
        },
    )()
    dummy.logger = FakeLogger()
    dummy.parse_cache = None

    async def fake_store_cached_result(*args, **kwargs):
        return None

    monkeypatch.setattr(
        DummyProcessor,
        "_store_cached_result",
        fake_store_cached_result,
        raising=False,
    )
    monkeypatch.setattr(
        DummyProcessor,
        "_generate_content_based_doc_id",
        lambda self, content_list: "doc-fixed",
        raising=False,
    )

    fake_pdf = tmp_path / "sample.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    content_list, doc_id = await dummy.parse_document(str(fake_pdf))
    content_list_2, doc_id_2 = await dummy.parse_document(str(fake_pdf))

    assert selected["parser_name"] == "paddleocr"
    assert selected["calls"] == 1
    assert doc_id == "doc-fixed"
    assert doc_id_2 == "doc-fixed"
    assert content_list == [
        {"type": "text", "text": "parsed by fake parser", "page_idx": 0}
    ]
    assert content_list_2 == [
        {"type": "text", "text": "parsed by fake parser", "page_idx": 0}
    ]
