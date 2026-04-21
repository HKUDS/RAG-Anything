#!/usr/bin/env python3
"""
Parser Validation Tests for RAG-Anything

Validates:
• Environment variable propagation
• Argument validation behaviour
• Fail-fast logic consistency
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from raganything.parser import MineruParser, DoclingParser


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def dummy_path():
    return "dummy.pdf"


@pytest.fixture(scope="module")
def mineru():
    return MineruParser()


@pytest.fixture(scope="module")
def docling():
    return DoclingParser()


@pytest.fixture
def mock_process():
    """Reusable fake subprocess process."""
    process = MagicMock()
    process.poll.return_value = 0
    process.wait.return_value = 0
    process.stdout.readline.return_value = ""
    process.stderr.readline.return_value = ""
    return process


# ---------------------------------------------------------------------
# Environment propagation
# ---------------------------------------------------------------------

@patch("subprocess.Popen")
@patch("pathlib.Path.exists", return_value=True)
@patch("pathlib.Path.mkdir")
def test_mineru_env_propagation(
    _mkdir, _exists, mock_popen, mineru, dummy_path, mock_process
):
    """Mineru should merge custom env with system env."""
    mock_popen.return_value = mock_process

    custom_env = {"MY_VAR": "test_value"}

    mineru._run_mineru_command(dummy_path, "out", env=custom_env)

    _, kwargs = mock_popen.call_args
    env = kwargs["env"]

    assert env["MY_VAR"] == "test_value"
    assert env["PATH"] == os.environ["PATH"]


@patch("subprocess.run")
def test_docling_env_propagation(mock_run, docling, dummy_path):
    """Docling should merge custom env with system env."""
    mock_run.return_value = MagicMock(returncode=0, stdout="")

    custom_env = {"DOCLING_VAR": "docling_value"}
    docling._run_docling_command(dummy_path, "out", "stem", env=custom_env)

    _, kwargs = mock_run.call_args
    env = kwargs["env"]

    assert env["DOCLING_VAR"] == "docling_value"
    assert env["PATH"] == os.environ["PATH"]


# ---------------------------------------------------------------------
# Unknown kwargs behaviour
# ---------------------------------------------------------------------

def test_mineru_rejects_unknown_kwargs(mineru, dummy_path):
    """Mineru must fail fast on unexpected kwargs."""
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        mineru._run_mineru_command(dummy_path, "out", unknown_arg="boom")


@patch("subprocess.run")
def test_docling_allows_unknown_kwargs(mock_run, docling, dummy_path):
    """Docling should ignore unknown kwargs (user requested behaviour)."""
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    docling._run_docling_command(dummy_path, "out", "stem", unknown_arg="allowed")


# ---------------------------------------------------------------------
# Env validation (parametrized)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_env", [
    ["not", "dict"],
    "string",
    123,
])
def test_invalid_env_type(mineru, docling, dummy_path, bad_env):
    """env must be dict."""
    with pytest.raises(TypeError, match="env must be a dictionary"):
        mineru._run_mineru_command(dummy_path, "out", env=bad_env)

    with pytest.raises(TypeError, match="env must be a dictionary"):
        docling._run_docling_command(dummy_path, "out", "stem", env=bad_env)


@pytest.mark.parametrize("bad_env", [
    {1: "value"},
    {"key": 123},
    {object(): "x"},
])
def test_invalid_env_contents(mineru, docling, dummy_path, bad_env):
    """env keys and values must be strings."""
    with pytest.raises(TypeError, match="env keys and values must be strings"):
        mineru._run_mineru_command(dummy_path, "out", env=bad_env)

    with pytest.raises(TypeError, match="env keys and values must be strings"):
        docling._run_docling_command(dummy_path, "out", "stem", env=bad_env)
