#!/usr/bin/env python3
"""
Parser Validation Test Script for RAG-Anything (Pytest)

This script validates the environment variable propagation and
argument validation logic for both MineruParser and DoclingParser.

For MineruParser, env={...} is still propagated to the subprocess and is
asserted as such. For DoclingParser the implementation now uses the Docling
Python API rather than the `docling` CLI; the legacy env kwarg is therefore
accepted for backward compatibility but ignored, and the tests below
exercise the Python-API path through DocumentConverter mocks instead of
subprocess mocks.

Requirements:
- RAG-Anything package
- pytest

Usage:
    pytest tests/testparser_kwargs.py
"""

import pytest
from contextlib import nullcontext
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import os
from raganything.parser import MineruParser, DoclingParser
from raganything.parser.office_parser import OcrOutOfMemoryError


@pytest.fixture
def mineru_parser():
    return MineruParser()


@pytest.fixture
def docling_parser():
    return DoclingParser()


@pytest.fixture
def dummy_path():
    return "dummy.pdf"


def _mock_docling_converter() -> MagicMock:
    """Build a DocumentConverter mock with the minimum API surface used by
    `DoclingParser._run_docling_python`."""
    fake_doc = MagicMock()
    fake_doc.export_to_dict.return_value = {"body": {}}
    fake_doc.export_to_markdown.return_value = ""
    converter = MagicMock()
    converter.convert.return_value = MagicMock(document=fake_doc)
    return converter


@patch("subprocess.Popen")
@patch("pathlib.Path.exists")
@patch("pathlib.Path.mkdir")
def test_mineru_env_propagation(
    mock_mkdir, mock_exists, mock_popen, mineru_parser, dummy_path
):
    mock_exists.return_value = True
    mock_process = MagicMock()
    mock_process.poll.return_value = 0
    mock_process.wait.return_value = 0
    mock_process.stdout.readline.return_value = ""
    mock_process.stderr.readline.return_value = ""
    mock_popen.return_value = mock_process

    custom_env = {"MY_VAR": "test_value"}

    # Test env propagation
    try:
        mineru_parser._run_mineru_command(dummy_path, "out", env=custom_env)
    except Exception:
        pass

    args, kwargs = mock_popen.call_args
    assert "env" in kwargs
    assert kwargs["env"]["MY_VAR"] == "test_value"
    assert kwargs["env"]["PATH"] == os.environ["PATH"]


@patch.object(DoclingParser, "_get_converter")
def test_docling_env_accepted_but_ignored(
    mock_get_converter, docling_parser, dummy_path, tmp_path
):
    """Docling now ignores `env={...}`: the call must succeed without raising
    and the underlying DocumentConverter must still be invoked."""
    mock_get_converter.return_value = _mock_docling_converter()

    custom_env = {"DOCLING_VAR": "docling_value"}
    docling_parser._run_docling_python(
        input_path=dummy_path,
        output_dir=tmp_path,
        file_stem="stem",
        env=custom_env,
    )

    # The Python-API path was used (no subprocess), env was silently dropped.
    mock_get_converter.assert_called_once()
    converter = mock_get_converter.return_value
    converter.convert.assert_called_once_with(str(dummy_path))


def test_mineru_unknown_kwargs(mineru_parser, dummy_path):
    # Mineru should fail fast on unknown kwargs
    with pytest.raises(TypeError) as excinfo:
        mineru_parser._run_mineru_command(dummy_path, "out", unknown_arg="fail")
    assert "unexpected keyword argument(s): unknown_arg" in str(excinfo.value)


@patch.object(DoclingParser, "_get_converter")
def test_docling_unknown_kwargs(
    mock_get_converter, docling_parser, dummy_path, tmp_path
):
    """Docling should accept unknown kwargs without raising — they are
    forwarded to `_get_converter` and silently ignored if unrecognized."""
    mock_get_converter.return_value = _mock_docling_converter()

    docling_parser._run_docling_python(
        input_path=dummy_path,
        output_dir=tmp_path,
        file_stem="stem",
        unknown_arg="allow",
    )
    mock_get_converter.assert_called_once()


def test_invalid_env_type(mineru_parser, docling_parser, dummy_path, tmp_path):
    # Test non-dict env
    with pytest.raises(TypeError, match="env must be a dictionary"):
        mineru_parser._run_mineru_command(dummy_path, "out", env=["not", "a", "dict"])

    # Validation happens before any converter call, so no mocking needed.
    with pytest.raises(TypeError, match="env must be a dictionary"):
        docling_parser._run_docling_python(
            input_path=dummy_path,
            output_dir=tmp_path,
            file_stem="stem",
            env="string",
        )


def test_invalid_env_contents(mineru_parser, docling_parser, dummy_path, tmp_path):
    # Test non-string keys/values
    with pytest.raises(TypeError, match="env keys and values must be strings"):
        mineru_parser._run_mineru_command(dummy_path, "out", env={1: "string_val"})

    with pytest.raises(TypeError, match="env keys and values must be strings"):
        docling_parser._run_docling_python(
            input_path=dummy_path,
            output_dir=tmp_path,
            file_stem="stem",
            env={"key": 123},
        )


@patch.object(DoclingParser, "_get_converter")
def test_docling_converter_cache_reused(
    mock_get_converter, docling_parser, dummy_path, tmp_path
):
    """Two parses with the same kwargs must reuse the cached converter."""
    mock_get_converter.return_value = _mock_docling_converter()

    docling_parser._run_docling_python(
        input_path=dummy_path,
        output_dir=tmp_path,
        file_stem="stem1",
    )
    docling_parser._run_docling_python(
        input_path=dummy_path,
        output_dir=tmp_path,
        file_stem="stem2",
    )

    # _get_converter was called twice (once per parse), but a real, unmocked
    # implementation would build the underlying DocumentConverter only once
    # thanks to `_converter_cache`. The cache itself is exercised in
    # `test_docling_converter_cache_unit` below.
    assert mock_get_converter.call_count == 2


def test_docling_converter_cache_unit(docling_parser):
    """Direct unit test for the cache: same kwargs return the same converter
    instance, different kwargs build a new one."""
    sentinel_a = object()
    sentinel_b = object()

    def fake_build(**kwargs):
        # Mimic the real `_get_converter` cache_key:
        key = (
            str(kwargs.get("table_mode", "fast")).lower(),
            bool(kwargs.get("tables", True)),
            bool(kwargs.get("allow_ocr", True)),
            kwargs.get("artifacts_path"),
        )
        cached = docling_parser._converter_cache.get(key)
        if cached is not None:
            return cached
        new = sentinel_a if key[0] == "fast" else sentinel_b
        docling_parser._converter_cache[key] = new
        return new

    with patch.object(DoclingParser, "_get_converter", side_effect=fake_build):
        a1 = docling_parser._get_converter()
        a2 = docling_parser._get_converter()
        b = docling_parser._get_converter(table_mode="accurate")

    assert a1 is a2 is sentinel_a
    assert b is sentinel_b
    assert a1 is not b


def _pdf_page_spec(page_number=1):
    return {
        "page_number": page_number,
        "width_points": 595.22,
        "height_points": 842.0,
    }


def test_docling_uses_provenance_for_page_index():
    assert DoclingParser._page_index_from_block(
        {"prov": [{"page_no": 152}]}, fallback=0
    ) == 151
    assert DoclingParser._page_index_from_block({}, fallback=7) == 7


def test_bounded_page_ocr_retries_only_the_failed_page(monkeypatch, tmp_path):
    parser = DoclingParser()
    calls = []

    class Converter:
        def convert(self, _path, *, page_range, raises_on_error):
            calls.append((page_range, raises_on_error))
            if len(calls) == 1:
                raise RuntimeError("RapidOCR ONNX RuntimeException: bad allocation")
            return SimpleNamespace(
                status="success",
                pages=[SimpleNamespace(page_no=page_range[0])],
                errors=[],
                document=SimpleNamespace(export_to_dict=lambda: {"body": {"children": []}}),
            )

    monkeypatch.setattr(parser, "_get_converter", lambda **_kwargs: Converter())
    monkeypatch.setattr(parser, "_release_docling_converters", lambda: None)
    monkeypatch.setattr(
        parser,
        "read_from_block_recursive",
        lambda *_args: [{"type": "text", "text": "ok", "page_idx": 0}],
    )
    monkeypatch.setattr(
        "raganything.parser.office_parser._rapidocr_render_scale",
        lambda _scale: nullcontext(),
    )

    content, record, error = parser._parse_pdf_page_bounded(
        tmp_path / "source.pdf", tmp_path, _pdf_page_spec(3), lang=None,
    )

    assert error is None
    assert content == [{"type": "text", "text": "ok", "page_idx": 0}]
    assert calls == [((3, 3), True), ((3, 3), True)]
    assert [attempt["status"] for attempt in record["attempts"]] == ["oom", "success"]
    assert record["attempts"][1]["profile"]["ocr_render_scale"] < record["attempts"][0]["profile"]["ocr_render_scale"]


def test_parse_pdf_raises_ocr_error_with_exact_failed_page_manifest(monkeypatch, tmp_path):
    parser = DoclingParser()
    specs = [_pdf_page_spec(1), _pdf_page_spec(2), _pdf_page_spec(3)]
    monkeypatch.setattr(parser, "_read_pdf_page_specs", lambda _path: specs)
    monkeypatch.setattr(parser, "_release_docling_converters", lambda: None)

    def parse_page(_path, _output, page_spec, **_kwargs):
        page_no = page_spec["page_number"]
        record = {**page_spec, "attempts": [{"attempt": 1}], "status": "success"}
        if page_no == 2:
            record["status"] = "failed"
            return None, record, RuntimeError("RapidOCR bad allocation")
        return [{"type": "text", "text": f"page {page_no}", "page_idx": page_no - 1}], record, None

    monkeypatch.setattr(parser, "_parse_pdf_page_bounded", parse_page)

    source = tmp_path / "source.pdf"
    source.write_bytes(b"placeholder")
    with pytest.raises(OcrOutOfMemoryError) as raised:
        parser.parse_pdf(source, output_dir=str(tmp_path / "out"))

    assert raised.value.page_coverage["source_total_pages"] == 3
    assert raised.value.page_coverage["successful_pages"] == [1, 3]
    assert raised.value.page_coverage["failed_pages"] == [2]


def test_pdf_coverage_requires_every_page_to_succeed():
    from raganything.processor.doc_processor import DocProcessorMixin

    complete = {
        "source_total_pages": 3,
        "successful_pages": [1, 2, 3],
        "failed_pages": [],
        "skipped_pages": [],
    }
    assert DocProcessorMixin._validate_pdf_page_coverage(complete) == complete

    with pytest.raises(ValueError, match="incomplete"):
        DocProcessorMixin._validate_pdf_page_coverage({
            **complete,
            "successful_pages": [1, 3],
            "failed_pages": [2],
        })


def test_real_long_scanned_pdf_has_complete_coverage_and_bounded_memory(tmp_path):
    """Opt-in real-stack regression; never targets an upload by default."""
    fixture_value = os.getenv("OCR_LONG_PDF_FIXTURE", "").strip()
    if not fixture_value:
        pytest.skip("set OCR_LONG_PDF_FIXTURE to run the real long-PDF OCR regression")

    from pathlib import Path
    from pypdf import PdfReader

    fixture = Path(fixture_value)
    assert fixture.is_file(), f"OCR_LONG_PDF_FIXTURE does not exist: {fixture}"
    assert len(PdfReader(str(fixture)).pages) >= 150

    def peak_private_commit(coverage):
        values = []
        for page in coverage.get("pages") or []:
            for attempt in page.get("attempts") or []:
                for key in ("memory_before", "memory_after"):
                    value = attempt.get(key, {}).get("private_commit_bytes")
                    if isinstance(value, int):
                        values.append(value)
        return max(values, default=0)

    parser = DoclingParser()
    first_content = parser.parse_pdf(fixture, output_dir=str(tmp_path / "first"))
    first_coverage = first_content.page_coverage
    second_content = parser.parse_pdf(fixture, output_dir=str(tmp_path / "second"))
    second_coverage = second_content.page_coverage

    for coverage in (first_coverage, second_coverage):
        total = coverage["source_total_pages"]
        assert coverage["failed_pages"] == []
        assert coverage["skipped_pages"] == []
        assert coverage["successful_pages"] == list(range(1, total + 1))

    max_private = int(os.getenv("OCR_LONG_PDF_MAX_PRIVATE_COMMIT_BYTES", str(2 * 1024 ** 3)))
    assert max(peak_private_commit(first_coverage), peak_private_commit(second_coverage)) <= max_private

    first_final = peak_private_commit({"pages": first_coverage.get("pages", [])[-1:]})
    second_final = peak_private_commit({"pages": second_coverage.get("pages", [])[-1:]})
    max_growth = int(os.getenv("OCR_LONG_PDF_MAX_GROWTH_BYTES", str(256 * 1024 ** 2)))
    assert second_final - first_final <= max_growth


def test_partial_page_manifest_is_never_good():
    from raganything.utils._quality import validate_and_suggest

    result = validate_and_suggest(
        [{"type": "text", "text": "高质量中文文本" * 100, "page_idx": 0}],
        source_total_pages=152,
        page_coverage={
            "source_total_pages": 152,
            "failed_pages": [120, 121],
            "skipped_pages": [],
        },
    )

    assert result["quality_score"] == 0.0
    assert result["quality_label"] == "incomplete"
    assert result["needs_retry"] is False


def test_worker_reports_ocr_oom_as_a_non_retryable_structured_error(capsys):
    import process_worker

    error = OcrOutOfMemoryError({
        "source_total_pages": 2,
        "successful_pages": [1],
        "failed_pages": [2],
        "skipped_pages": [],
    })
    assert process_worker._is_ocr_memory_error(error)
    assert not process_worker._is_retryable_external_error(error)

    process_worker._emit_worker_error(stage="ocr", error=error, retryable=False)
    payload = json.loads(capsys.readouterr().out.split("WORKER_ERROR_JSON ", 1)[1])
    assert payload["stage"] == "ocr"
    assert payload["root_type"] == "OcrOutOfMemoryError"
    assert payload["failure_code"] == "ocr_oom"
    assert payload["retryable"] is False
    assert payload["page_coverage"]["failed_pages"] == [2]


@pytest.mark.asyncio
async def test_ocr_worker_gate_defaults_to_one_slot(monkeypatch):
    from raganything.services import kb_service

    monkeypatch.delenv("DOCUMENT_OCR_MAX_CONCURRENCY", raising=False)
    kb_service._ocr_worker_slots.clear()
    first = kb_service._get_ocr_worker_slot()
    second = kb_service._get_ocr_worker_slot()

    assert first is second
    assert first._value == 1
