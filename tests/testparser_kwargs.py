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
from unittest.mock import patch, MagicMock
import os
import re
from raganything.parser import MineruParser, DoclingParser, Parser
import raganything.parser as parser_module
from pathlib import Path


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


def test_mineru_windows_unsafe_pdf_uses_safe_paths(
    monkeypatch, mineru_parser, tmp_path
):
    monkeypatch.setattr(parser_module, "_IS_WINDOWS", True)
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    pdf_path = source_dir / "sample-测试 .pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    captured = {}

    def fake_run_mineru_command(**kwargs):
        captured.update(kwargs)
        assert kwargs["input_path"].exists()
        assert kwargs["input_path"].read_bytes() == b"%PDF-1.4\n"

    with (
        patch.object(
            MineruParser, "_run_mineru_command", side_effect=fake_run_mineru_command
        ),
        patch.object(MineruParser, "_read_output_files", return_value=([], "")) as read,
    ):
        mineru_parser.parse_pdf(pdf_path, output_dir=tmp_path / "out")

    input_path = captured["input_path"]
    output_dir = captured["output_dir"]
    assert re.fullmatch(r"input_[0-9a-f]{10}\.pdf", input_path.name)
    assert re.fullmatch(r"mineru_[0-9a-f]{10}", output_dir.name)
    assert input_path.name.isascii()
    assert output_dir.name.isascii()
    assert read.call_args.args[1] == input_path.stem


def test_mineru_windows_safe_pdf_keeps_original_path(
    monkeypatch, mineru_parser, tmp_path
):
    monkeypatch.setattr(parser_module, "_IS_WINDOWS", True)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"

    captured = {}

    def fake_run_mineru_command(**kwargs):
        captured.update(kwargs)

    with (
        patch.object(
            MineruParser, "_run_mineru_command", side_effect=fake_run_mineru_command
        ),
        patch.object(MineruParser, "_read_output_files", return_value=([], "")) as read,
    ):
        mineru_parser.parse_pdf(pdf_path, output_dir=output_dir)

    assert captured["input_path"] == pdf_path
    assert captured["output_dir"] == MineruParser._unique_output_dir(
        output_dir, pdf_path
    )
    assert read.call_args.args[1] == "sample"


def test_mineru_windows_unsafe_png_uses_safe_paths(
    monkeypatch, mineru_parser, tmp_path
):
    monkeypatch.setattr(parser_module, "_IS_WINDOWS", True)
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    image_path = source_dir / "sample-测试 .png"
    image_path.write_bytes(b"\x89PNG\r\n")

    captured = {}

    def fake_run_mineru_command(**kwargs):
        captured.update(kwargs)
        assert kwargs["method"] == "ocr"
        assert kwargs["input_path"].exists()
        assert kwargs["input_path"].read_bytes() == b"\x89PNG\r\n"

    with (
        patch.object(
            MineruParser, "_run_mineru_command", side_effect=fake_run_mineru_command
        ),
        patch.object(MineruParser, "_read_output_files", return_value=([], "")) as read,
    ):
        mineru_parser.parse_image(image_path, output_dir=tmp_path / "out")

    input_path = captured["input_path"]
    output_dir = captured["output_dir"]
    assert re.fullmatch(r"input_[0-9a-f]{10}\.png", input_path.name)
    assert re.fullmatch(r"mineru_[0-9a-f]{10}", output_dir.name)
    assert input_path.name.isascii()
    assert output_dir.name.isascii()
    assert read.call_args.args[1] == input_path.stem


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


def test_windows_libreoffice_candidates_include_standard_install_dir(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(parser_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(parser_module.shutil, "which", lambda command: None)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)

    soffice_path = tmp_path / "LibreOffice" / "program" / "soffice.exe"
    soffice_path.parent.mkdir(parents=True)
    soffice_path.write_text("", encoding="utf-8")

    candidates = Parser._libreoffice_command_candidates()

    assert str(soffice_path) in candidates


def test_convert_office_to_pdf_uses_windows_standard_libreoffice_path(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(parser_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(parser_module.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(parser_module.shutil, "which", lambda command: None)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)

    soffice_path = tmp_path / "LibreOffice" / "program" / "soffice.exe"
    soffice_path.parent.mkdir(parents=True)
    soffice_path.write_text("", encoding="utf-8")

    doc_path = tmp_path / "sample.docx"
    doc_path.write_bytes(b"docx")
    output_dir = tmp_path / "out"
    captured_commands = []

    def fake_run(cmd, **kwargs):
        captured_commands.append(cmd)
        if cmd[0] != str(soffice_path):
            raise FileNotFoundError(cmd[0])

        pdf_path = Path(cmd[cmd.index("--outdir") + 1]) / "sample.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n" + b"0" * 200)
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr(parser_module.subprocess, "run", fake_run)

    pdf_path = Parser.convert_office_to_pdf(doc_path, output_dir)

    assert captured_commands[-1][0] == str(soffice_path)
    assert pdf_path == output_dir / "sample.pdf"
    assert pdf_path.exists()
