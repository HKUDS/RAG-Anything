#!/usr/bin/env python3
"""
Tests for MinerU failure diagnosis (issue #304).

When MinerU crashes inside its own subprocess, RAG-Anything can only see the
stderr lines it printed. For known dependency incompatibilities we translate
those opaque tracebacks into actionable remediation advice.

Usage:
    pytest tests/test_mineru_error_hints.py
"""

from unittest.mock import MagicMock, patch

import pytest

from raganything.parser import (
    MineruExecutionError,
    MineruParser,
    _diagnose_mineru_failure,
)


# The stderr lines exactly as reported in issue #304 (xlsx -> PDF -> MinerU).
PAGECHARS_ERROR_LINES = [
    "2026-07-02 08:25:13.423 | ERROR | __main__:_process_task:1154 - "
    "Async task failed: 10306380-016b-434d-ab67-c25c588184d4",
    "TypeError: 'PageChars' object is not iterable",
    "Error: 1 task(s) failed while processing documents:",
    "- task#1 (excel_table): Task 10306380-016b-434d-ab67-c25c588184d4 failed "
    'for task#1 [excel_table]: {"status": "failed", "backend": "pipeline", '
    '"error": "\'PageChars\' object is not iterable"}',
]


def test_pagechars_failure_is_recognized():
    hint = _diagnose_mineru_failure(PAGECHARS_ERROR_LINES)

    assert hint is not None
    assert 'pip install -U "mineru[core]>=3.4.1"' in hint
    assert "pdftext" in hint


def test_diagnosis_accepts_a_plain_string():
    hint = _diagnose_mineru_failure("TypeError: 'PageChars' object is not iterable")

    assert hint is not None
    assert "mineru[core]>=3.4.1" in hint


@pytest.mark.parametrize(
    "error_msg",
    [
        [],
        ["Error: some unrelated mineru failure"],
        "RuntimeError: CUDA out of memory",
    ],
)
def test_unknown_failures_produce_no_hint(error_msg):
    assert _diagnose_mineru_failure(error_msg) is None


def test_execution_error_message_includes_hint():
    exc = MineruExecutionError(1, PAGECHARS_ERROR_LINES)

    assert exc.hint is not None
    message = str(exc)
    # Original diagnostic output is preserved ...
    assert "Mineru command failed with return code 1" in message
    assert "'PageChars' object is not iterable" in message
    # ... and the remediation advice is appended.
    assert 'pip install -U "mineru[core]>=3.4.1"' in message


def test_execution_error_without_known_signature_has_no_hint():
    exc = MineruExecutionError(1, ["Error: unrelated failure"])

    assert exc.hint is None
    assert (
        str(exc) == "Mineru command failed with return code 1: "
        "['Error: unrelated failure']"
    )


def test_execution_error_keeps_positional_signature():
    """Backwards compatibility: `hint` is optional and inferred when omitted."""
    exc = MineruExecutionError(2, ["boom"])

    assert exc.return_code == 2
    assert exc.error_msg == ["boom"]


def test_explicit_hint_overrides_diagnosis():
    exc = MineruExecutionError(1, PAGECHARS_ERROR_LINES, hint="custom advice")

    assert exc.hint == "custom advice"
    assert "custom advice" in str(exc)


def _fake_mineru_process(stderr_lines, return_code=1):
    """A Popen double that streams `stderr_lines` then exits with `return_code`."""
    process = MagicMock()
    process.poll.return_value = return_code  # already exited; drain path is used
    process.wait.return_value = return_code
    process.stdout.readline.side_effect = [""] * 10
    process.stderr.readline.side_effect = [line + "\n" for line in stderr_lines] + [
        ""
    ] * 10
    return process


@patch("subprocess.Popen")
@patch("pathlib.Path.mkdir")
def test_hint_survives_the_real_stderr_capture_path(mock_mkdir, mock_popen):
    """End-to-end guard for issue #304.

    `_run_mineru_command` only keeps stderr lines containing "error", so this
    asserts the PageChars traceback line actually survives that filter and
    reaches the diagnosis rather than being dropped as noise.
    """
    mock_popen.return_value = _fake_mineru_process(PAGECHARS_ERROR_LINES)

    with pytest.raises(MineruExecutionError) as excinfo:
        MineruParser()._run_mineru_command("book.pdf", "out")

    exc = excinfo.value
    assert exc.return_code == 1
    assert "'PageChars' object is not iterable" in "\n".join(exc.error_msg)
    assert exc.hint is not None
    assert 'pip install -U "mineru[core]>=3.4.1"' in str(exc)
    assert 'parser="docling"' in str(exc)


@patch("subprocess.Popen")
@patch("pathlib.Path.mkdir")
def test_unrelated_stderr_still_raises_without_a_hint(mock_mkdir, mock_popen):
    mock_popen.return_value = _fake_mineru_process(
        ["Error: model weights could not be downloaded"]
    )

    with pytest.raises(MineruExecutionError) as excinfo:
        MineruParser()._run_mineru_command("book.pdf", "out")

    assert excinfo.value.hint is None
