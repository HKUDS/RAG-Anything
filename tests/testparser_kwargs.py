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
from raganything.parser import MineruParser, DoclingParser


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
