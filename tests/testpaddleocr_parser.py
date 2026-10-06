import importlib
import sys

import pytest

from raganything.parser import PaddleOCRParser, SUPPORTED_PARSERS, get_parser


def test_supported_parsers_include_paddleocr():
    assert "paddleocr" in SUPPORTED_PARSERS


def test_get_parser_returns_paddleocr_parser():
    parser = get_parser("paddleocr")
    assert isinstance(parser, PaddleOCRParser)


def test_get_parser_rejects_unknown_parser():
    with pytest.raises(ValueError, match="Unsupported parser type"):
        get_parser("unknown-parser")


def test_parser_module_import_does_not_import_paddleocr():
    sys.modules.pop("paddleocr", None)
    sys.modules.pop("raganything.parser", None)
    importlib.import_module("raganything.parser")
    assert "paddleocr" not in sys.modules


def test_check_installation_false_when_dependency_missing(monkeypatch):
    parser = PaddleOCRParser()

    def missing_dependency():
        raise ImportError("missing paddleocr")

    monkeypatch.setattr(parser, "_require_paddleocr", missing_dependency)
    assert parser.check_installation() is False


def test_check_installation_true_when_pdf_renderer_missing(monkeypatch):
    parser = PaddleOCRParser()

    monkeypatch.setattr(parser, "_require_paddleocr", lambda: object())

    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pypdfium2":
            raise ImportError("missing pypdfium2")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert parser.check_installation() is True


def test_parse_pdf_raises_import_error_when_pdf_renderer_missing(monkeypatch, tmp_path):
    parser = PaddleOCRParser()
    fake_pdf = tmp_path / "sample.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(parser, "_require_paddleocr", lambda: object())

    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pypdfium2":
            raise ImportError("missing pypdfium2")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match="pypdfium2"):
        parser.parse_pdf(fake_pdf)


def test_parse_image_raises_import_error_with_install_hint(monkeypatch, tmp_path):
    parser = PaddleOCRParser()
    fake_image = tmp_path / "sample.png"
    fake_image.write_bytes(b"not-a-real-image")

    def missing_dependency():
        raise ImportError("missing paddleocr")

    monkeypatch.setattr(parser, "_require_paddleocr", missing_dependency)

    with pytest.raises(ImportError, match="paddleocr"):
        parser.parse_image(fake_image)


def test_parse_image_returns_content_list_schema(monkeypatch, tmp_path):
    parser = PaddleOCRParser()
    fake_image = tmp_path / "sample.png"
    fake_image.write_bytes(b"image-bytes")

    class FakeOCR:
        def ocr(self, input_data, cls=True):
            return [
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("First line", 0.99)],
                    [[[0, 2], [1, 2], [1, 3], [0, 3]], ("Second line", 0.95)],
                ]
            ]

    monkeypatch.setattr(parser, "_get_ocr", lambda lang=None: FakeOCR())

    content_list = parser.parse_image(fake_image, page_idx=7)

    assert content_list == [
        {"type": "text", "text": "First line", "page_idx": 7},
        {"type": "text", "text": "Second line", "page_idx": 7},
    ]


def test_parse_image_preserves_repeated_ocr_lines(monkeypatch, tmp_path):
    parser = PaddleOCRParser()
    fake_image = tmp_path / "sample.png"
    fake_image.write_bytes(b"image-bytes")

    class FakeOCR:
        def ocr(self, input_data, cls=True):
            return [
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("Same", 0.99)],
                    [[[0, 2], [1, 2], [1, 3], [0, 3]], ("Same", 0.95)],
                ]
            ]

    monkeypatch.setattr(parser, "_get_ocr", lambda lang=None: FakeOCR())

    content_list = parser.parse_image(fake_image, page_idx=1)

    assert content_list == [
        {"type": "text", "text": "Same", "page_idx": 1},
        {"type": "text", "text": "Same", "page_idx": 1},
    ]


@pytest.mark.parametrize("texts", [["Invoice total: $42", "Invoice total: $42"], []])
@pytest.mark.parametrize("wrapped", [False, True])
def test_parse_image_excludes_paddleocr_result_metadata(
    monkeypatch, tmp_path, texts, wrapped
):
    parser = PaddleOCRParser()
    image_path = tmp_path / "invoice.png"
    image_path.write_bytes(b"image-bytes")

    class FakeOCR:
        def ocr(self, input_data, cls=True):
            result = {
                "input_path": input_data,
                "page_index": None,
                "model_settings": {"use_doc_preprocessor": True},
                "doc_preprocessor_res": {"input_path": input_data, "angle": 0},
                "text_det_params": {"limit_type": "min"},
                "text_type": "general",
                "rec_texts": texts,
                "rec_scores": [0.99] * len(texts),
            }
            return [{"res": result} if wrapped else result]

    monkeypatch.setattr(parser, "_get_ocr", lambda lang=None: FakeOCR())

    assert parser.parse_image(image_path, page_idx=3) == [
        {"type": "text", "text": text, "page_idx": 3} for text in texts
    ]


@pytest.mark.parametrize(
    "result, expected",
    [
        (" First line ", ["First line"]),
        (["First line", "Second line"], ["First line", "Second line"]),
        ({"text": "First line", "input_path": "page.png"}, ["First line"]),
        ({"texts": ["First line", ""], "text_type": "general"}, ["First line"]),
        ({"texts": [], "text_type": "general"}, []),
    ],
)
def test_extract_text_lines_preserves_supported_text_results(result, expected):
    assert PaddleOCRParser()._extract_text_lines(result) == expected


def test_extract_text_lines_excludes_metadata_from_to_dict_results():
    class Result:
        def to_dict(self):
            return {"rec_texts": ["Recognized text"], "input_path": "page.png"}

    assert PaddleOCRParser()._extract_text_lines([Result()]) == ["Recognized text"]


def test_parse_pdf_assigns_page_index(monkeypatch, tmp_path):
    parser = PaddleOCRParser()
    fake_pdf = tmp_path / "sample.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        parser,
        "_extract_pdf_page_inputs",
        lambda pdf_path: [(0, "page0"), (1, "page1")],
    )
    monkeypatch.setattr(
        parser,
        "_ocr_rendered_page",
        lambda rendered_page, lang=None, cls_enabled=True: [f"{rendered_page}-text"],
    )

    content_list = parser.parse_pdf(fake_pdf)

    assert content_list == [
        {"type": "text", "text": "page0-text", "page_idx": 0},
        {"type": "text", "text": "page1-text", "page_idx": 1},
    ]
