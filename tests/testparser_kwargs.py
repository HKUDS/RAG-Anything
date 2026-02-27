#!/usr/bin/env python3
"""
Parser Validation Test Script for RAG-Anything (Pytest)

This script validates the environment variable propagation and
argument validation logic for both MineruParser and DoclingParser.
It ensures that environment variables are correctly passed to subprocesses
and that invalid inputs are handled properly (fail-fast).

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


@patch("subprocess.run")
def test_docling_env_propagation(mock_run, docling_parser, dummy_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="")

    custom_env = {"DOCLING_VAR": "docling_value"}

    # Test env propagation
    docling_parser._run_docling_command(dummy_path, "out", "stem", env=custom_env)

    args, kwargs = mock_run.call_args
    assert "env" in kwargs
    assert kwargs["env"]["DOCLING_VAR"] == "docling_value"
    assert kwargs["env"]["PATH"] == os.environ["PATH"]


def test_mineru_unknown_kwargs(mineru_parser, dummy_path):
    # Mineru should fail fast on unknown kwargs
    with pytest.raises(TypeError) as excinfo:
        mineru_parser._run_mineru_command(dummy_path, "out", unknown_arg="fail")
    assert "unexpected keyword argument(s): unknown_arg" in str(excinfo.value)


@patch("subprocess.run")
def test_docling_unknown_kwargs(mock_run, docling_parser, dummy_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    # Docling should NOT fail on unknown kwargs as per user request
    docling_parser._run_docling_command(dummy_path, "out", "stem", unknown_arg="allow")
    # No exception means success


def test_invalid_env_type(mineru_parser, docling_parser, dummy_path):
    # Test non-dict env
    with pytest.raises(TypeError, match="env must be a dictionary"):
        mineru_parser._run_mineru_command(dummy_path, "out", env=["not", "a", "dict"])

    with pytest.raises(TypeError, match="env must be a dictionary"):
        docling_parser._run_docling_command(dummy_path, "out", "stem", env="string")


def test_invalid_env_contents(mineru_parser, docling_parser, dummy_path):
    # Test non-string keys/values
    with pytest.raises(TypeError, match="env keys and values must be strings"):
        mineru_parser._run_mineru_command(dummy_path, "out", env={1: "string_val"})

    with pytest.raises(TypeError, match="env keys and values must be strings"):
        docling_parser._run_docling_command(dummy_path, "out", "stem", env={"key": 123})
