#!/usr/bin/env python3
"""
MinerU 4.x support boundary and full MinerU error output.

MinerU 4.0 replaced the ``mineru -p <input> -o <output>`` command line that
MineruParser drives with subcommands, but ``mineru --version`` still works, so
the old installation check passed and every parse then failed with
``Mineru command failed with return code 2: ['╭─ Error ───...╮']``: only the
top border of MinerU's error box, never the "No such option: -p" inside it.

These tests run a fake ``mineru`` executable on PATH through the real
subprocess code paths.

Usage:
    pytest tests/test_mineru_version_support.py
"""

import asyncio
import os
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement

import raganything.parser as parser_module
import raganything.raganything as rag_module
from raganything import RAGAnything, RAGAnythingConfig
from raganything.batch_parser import BatchParser
from raganything.parser import (
    MineruExecutionError,
    MineruParser,
    _format_mineru_output,
    _mineru_output_tail,
    _parse_mineru_version,
)

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_INSTALL = 'pip install -U "mineru[core]>=3.4.1,<4"'
PYTHON_LIMIT = "MinerU 3.x supports Python 3.10 to 3.13 only"

# `mineru -p ...` against MinerU 4.0.12, stderr captured verbatim (exit code 2).
MINERU4_USAGE_ERROR = (
    "Usage: mineru [OPTIONS] COMMAND [ARGS]...\n"
    "Try 'mineru --help' for help.\n"
    "╭─ Error ──────────────────────────────────────────────────────────────────────╮\n"
    "│ No such option: -p                                                           │\n"
    "╰──────────────────────────────────────────────────────────────────────────────╯\n"
)

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="the fake mineru executable is a POSIX shell script"
)


@pytest.fixture(autouse=True)
def _python_with_mineru3(monkeypatch):
    """Behave as on a Python MinerU 3.x supports, with no MinerU distribution
    of its own, unless a test says otherwise."""
    monkeypatch.setattr(parser_module, "_mineru_python_unsupported", lambda: False)
    monkeypatch.setattr(parser_module, "_installed_mineru_version", lambda: None)


def _python_without_mineru3(monkeypatch):
    """Behave as on Python 3.14+, where no MinerU 3.x release installs."""
    monkeypatch.setattr(parser_module, "_mineru_python_unsupported", lambda: True)


def _empty_path(monkeypatch, tmp_path):
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))


def _make_rag(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_module.atexit, "register", lambda *args: None)

    def llm_model_func(prompt, **kwargs):
        raise AssertionError("the LLM must not be called")

    def embedding_func(texts):
        raise AssertionError("embeddings must not be computed")

    return RAGAnything(
        config=RAGAnythingConfig(working_dir=str(tmp_path / "rag"), parser="mineru"),
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )


def _fake_mineru(monkeypatch, tmp_path, body):
    """Put a ``mineru`` shell script running ``body`` first on PATH."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    script = bin_dir / "mineru"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def _fake_mineru_version(monkeypatch, tmp_path, version_output):
    _fake_mineru(
        monkeypatch,
        tmp_path,
        f"cat <<'EOF'\n{version_output}\nEOF\n",
    )


def _fake_mineru_failure(monkeypatch, tmp_path, stderr, return_code=2):
    _fake_mineru(
        monkeypatch,
        tmp_path,
        f"cat >&2 <<'EOF'\n{stderr}EOF\nexit {return_code}\n",
    )


# --------------------------------------------------------------------------
# Version parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output, expected",
    [
        ("mineru, version 3.4.5", ("3.4.5", 3)),
        ("MinerU version: 4.0.12\nPython version: 3.12.13", ("4.0.12", 4)),
        ("MinerU 版本: 4.0.12\nPython 版本: 3.12.13", ("4.0.12", 4)),
        ("Python version: 3.12.13\nMinerU version: 4.0.12", ("4.0.12", 4)),
        ("4.1.0", ("4.1.0", 4)),
        ("v3.4.1", ("3.4.1", 3)),
    ],
)
def test_mineru_version_is_read_from_the_line_naming_mineru(output, expected):
    assert _parse_mineru_version(output) == expected


@pytest.mark.parametrize(
    "output",
    [
        "",
        "mineru, version unknown",
        "development build",
        # A version that is not MinerU's must not be mistaken for it.
        "Python version: 4.1.0",
        "mineru installed under /opt/python3.12/site-packages",
    ],
)
def test_unrecognisable_version_output_is_not_parsed(output):
    assert _parse_mineru_version(output) is None


# --------------------------------------------------------------------------
# Dependency metadata
# --------------------------------------------------------------------------


def _mineru_requirements():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    from_pyproject = [
        Requirement(dep)
        for dep in pyproject["project"]["dependencies"]
        if Requirement(dep).name == "mineru"
    ]
    from_requirements = [
        Requirement(line)
        for line in (REPO_ROOT / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and Requirement(line).name == "mineru"
    ]
    return from_pyproject, from_requirements


def test_pyproject_and_requirements_declare_the_same_mineru_requirement():
    from_pyproject, from_requirements = _mineru_requirements()

    assert len(from_pyproject) == 1 and len(from_requirements) == 1
    assert str(from_pyproject[0]) == str(from_requirements[0])
    requirement = from_pyproject[0]
    assert requirement.extras == {"core"}
    # The install command the error messages print is the same requirement.
    printed = Requirement(parser_module._MINERU_REQUIREMENT)
    assert (printed.name, printed.extras) == (requirement.name, requirement.extras)
    assert printed.specifier == requirement.specifier
    assert f'"{parser_module._MINERU_REQUIREMENT}"' in SUPPORTED_INSTALL
    assert requirement.specifier.contains("3.4.1")
    assert requirement.specifier.contains("3.4.5")
    assert not requirement.specifier.contains("3.4.0")
    assert not requirement.specifier.contains("4.0.0")


@pytest.mark.parametrize(
    "python_version, installs_mineru",
    [("3.10", True), ("3.13", True), ("3.14", False), ("3.15", False)],
)
def test_mineru_is_only_required_on_pythons_mineru_3_supports(
    python_version, installs_mineru
):
    """Every MinerU 3.x release requires Python <3.14. Without a marker, pip on
    3.14 skips this release and falls back to raganything 1.4.3 + MinerU 4.x."""
    for requirement in _mineru_requirements()[0] + _mineru_requirements()[1]:
        assert requirement.marker is not None
        environment = {"python_version": python_version}
        assert requirement.marker.evaluate(environment) is installs_mineru


def test_python_limit_matches_the_dependency_marker():
    assert parser_module._MINERU_LAST_SUPPORTED_PYTHON == (3, 13)


@pytest.mark.parametrize("readme", ["README.md", "README_zh.md"])
def test_readme_mineru_links_point_at_mineru_3_docs(readme):
    """MinerU's default branch documents MinerU 4.x (and tells readers to
    install mineru>=4.0,<5), so setup links must name a MinerU 3.x tag."""
    text = (REPO_ROOT / readme).read_text("utf-8")
    links = re.findall(r"https://github\.com/opendatalab/MinerU/blob/([^/\s)]+)/", text)

    assert links, "expected a MinerU documentation link"
    assert all(ref.startswith("mineru-3.") for ref in links), links


# --------------------------------------------------------------------------
# check_installation
# --------------------------------------------------------------------------


@posix_only
@pytest.mark.parametrize(
    "version_output",
    [
        "MinerU version: 4.0.12\nPython version: 3.12.13",
        "MinerU 版本: 4.0.12\nPython 版本: 3.12.13",
    ],
)
def test_check_installation_rejects_mineru_4(monkeypatch, tmp_path, version_output):
    _fake_mineru_version(monkeypatch, tmp_path, version_output)
    parser = MineruParser()

    assert parser.check_installation() is False
    reason = parser.installation_error
    assert "MinerU 4.0.12" in reason
    assert "does not support MinerU 4.0 or later" in reason
    assert SUPPORTED_INSTALL in reason


@posix_only
def test_mineru_4_reason_names_the_executable(monkeypatch, tmp_path):
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )
    parser = MineruParser()

    assert parser.check_installation() is False
    assert f"MinerU 4.0.12 ({tmp_path / 'fake-bin' / 'mineru'})" in (
        parser.installation_error
    )


@posix_only
def test_mineru_4_from_another_environment_points_to_path_not_pip(
    monkeypatch, tmp_path
):
    """This Python has MinerU 3.x, but PATH finds another env's MinerU 4.x
    (unactivated venv, Jupyter kernel): installing 3.x again would not help."""
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )
    monkeypatch.setattr(parser_module, "_installed_mineru_version", lambda: "3.4.5")
    parser = MineruParser()

    assert parser.check_installation() is False
    reason = parser.installation_error
    assert "MinerU 4.0.12" in reason
    assert "belongs to another environment" in reason
    assert "has MinerU 3.4.5 installed" in reason
    assert parser_module.sys.executable in reason
    assert parser_module.sysconfig.get_path("scripts") in reason
    assert SUPPORTED_INSTALL not in reason


@posix_only
def test_mineru_4_installed_for_this_python_still_suggests_mineru_3(
    monkeypatch, tmp_path
):
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )
    monkeypatch.setattr(parser_module, "_installed_mineru_version", lambda: "4.0.12")
    parser = MineruParser()

    assert parser.check_installation() is False
    assert "another environment" not in parser.installation_error
    assert SUPPORTED_INSTALL in parser.installation_error


@posix_only
def test_check_installation_logs_the_mineru_4_reason_at_debug_only(
    monkeypatch, tmp_path, caplog
):
    """Callers report installation_error themselves; a WARNING here showed the
    same text twice (CLI --check, RAGAnything and BatchParser logs)."""
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )

    with caplog.at_level("DEBUG", logger="raganything.parser"):
        assert MineruParser().check_installation() is False

    reason_records = [r for r in caplog.records if "MinerU 4.0.12" in r.getMessage()]
    assert reason_records
    assert all(r.levelname == "DEBUG" for r in reason_records)


# `mineru --version` in python:3.12-slim with MinerU 3.4.5 installed but no
# libGL (opencv-python is imported at startup).
MINERU_MISSING_LIBGL = (
    "Traceback (most recent call last):\n"
    '  File "/usr/local/bin/mineru", line 5, in <module>\n'
    "    from mineru.cli.client import main\n"
    "  ...\n"
    "    from .cv2 import *\n"
    "ImportError: libGL.so.1: cannot open shared object file: No such file or directory\n"
)


@posix_only
def test_failing_mineru_version_reports_mineru_last_line(monkeypatch, tmp_path):
    _fake_mineru_failure(monkeypatch, tmp_path, MINERU_MISSING_LIBGL, return_code=1)
    parser = MineruParser()

    assert parser.check_installation() is False
    reason = parser.installation_error
    assert reason.startswith(
        "`mineru --version` failed with exit code 1: ImportError: libGL.so.1: "
        "cannot open shared object file"
    )
    assert "apt-get install libgl1 libglib2.0-0" in reason
    assert "Traceback" not in reason


@posix_only
def test_failing_mineru_version_without_output(monkeypatch, tmp_path):
    _fake_mineru(monkeypatch, tmp_path, "exit 3\n")
    parser = MineruParser()

    assert parser.check_installation() is False
    assert parser.installation_error == (
        "`mineru --version` failed with exit code 3. "
        "Run `mineru --version` to see MinerU's full error."
    )


@posix_only
def test_initialization_reports_a_failing_mineru_version(monkeypatch, tmp_path):
    _fake_mineru_failure(monkeypatch, tmp_path, MINERU_MISSING_LIBGL, return_code=1)
    rag = _make_rag(monkeypatch, tmp_path)

    result = asyncio.run(rag._ensure_lightrag_initialized())

    assert result["success"] is False
    assert "ImportError: libGL.so.1" in result["error"]
    assert "pip install' or 'uv pip install'" not in result["error"]


@posix_only
def test_check_parser_installation_warns_with_the_reason_once(
    monkeypatch, tmp_path, caplog
):
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )
    rag = _make_rag(monkeypatch, tmp_path)
    # RAGAnything logs through LightRAG's logger, which does not propagate to
    # caplog's root handler.
    rag_warnings = []
    monkeypatch.setattr(rag.logger, "warning", rag_warnings.append)

    with caplog.at_level("WARNING"):
        assert rag.check_parser_installation() is False

    assert len(rag_warnings) == 1
    assert rag_warnings[0].startswith("Parser 'mineru' is not properly installed. ")
    assert "MinerU 4.0.12" in rag_warnings[0]
    assert not [r for r in caplog.records if "MinerU 4.0.12" in r.getMessage()]


@posix_only
def test_parser_cli_check_prints_the_reason_once(monkeypatch, tmp_path, capsys, caplog):
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )
    monkeypatch.setattr(
        parser_module.sys, "argv", ["raganything.parser", "x.pdf", "--check"]
    )

    with caplog.at_level("WARNING"):
        assert parser_module.main() == 1

    out = capsys.readouterr().out
    assert "Mineru installation check failed" in out
    assert out.count("MinerU 4.0.12") == 1
    assert SUPPORTED_INSTALL in out
    assert not [r for r in caplog.records if "MinerU 4.0.12" in r.getMessage()]


@posix_only
def test_check_installation_accepts_mineru_3(monkeypatch, tmp_path):
    _fake_mineru_version(monkeypatch, tmp_path, "mineru, version 3.4.5")
    parser = MineruParser()

    assert parser.check_installation() is True
    assert parser.installation_error is None


@posix_only
@pytest.mark.parametrize(
    "version_output",
    ["", "mineru, version unknown", "custom build", "Python version: 4.1.0"],
)
def test_check_installation_accepts_unrecognisable_version_output(
    monkeypatch, tmp_path, version_output
):
    """Exotic installs whose version cannot be read keep passing, as before."""
    _fake_mineru_version(monkeypatch, tmp_path, version_output)

    assert MineruParser().check_installation() is True


@posix_only
def test_check_installation_clears_a_previous_failure_reason(monkeypatch, tmp_path):
    parser = MineruParser()
    parser.installation_error = "stale"
    _fake_mineru_version(monkeypatch, tmp_path, "mineru, version 3.4.5")

    assert parser.check_installation() is True
    assert parser.installation_error is None


@posix_only
def test_check_installation_without_mineru_still_fails_quietly(monkeypatch, tmp_path):
    _empty_path(monkeypatch, tmp_path)
    parser = MineruParser()

    assert parser.check_installation() is False
    assert parser.installation_error is None


@posix_only
def test_missing_mineru_on_python_3_14_explains_the_python_limit(monkeypatch, tmp_path):
    _python_without_mineru3(monkeypatch)
    _empty_path(monkeypatch, tmp_path)
    parser = MineruParser()

    assert parser.check_installation() is False
    reason = parser.installation_error
    assert "`mineru` command was not found" in reason
    assert PYTHON_LIMIT in reason
    assert 'parser="docling"' in reason
    # pip cannot install MinerU 3.x there, so do not tell the user to.
    assert SUPPORTED_INSTALL not in reason


@posix_only
def test_mineru_4_on_python_3_14_points_to_python_3_13_or_docling(
    monkeypatch, tmp_path
):
    _python_without_mineru3(monkeypatch)
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.14.4"
    )
    parser = MineruParser()

    assert parser.check_installation() is False
    reason = parser.installation_error
    assert "MinerU 4.0.12" in reason
    assert PYTHON_LIMIT in reason
    assert 'parser="docling"' in reason
    assert SUPPORTED_INSTALL not in reason


@posix_only
def test_initialization_on_python_3_14_without_mineru_explains_the_limit(
    monkeypatch, tmp_path
):
    _python_without_mineru3(monkeypatch)
    _empty_path(monkeypatch, tmp_path)
    rag = _make_rag(monkeypatch, tmp_path)

    result = asyncio.run(rag._ensure_lightrag_initialized())

    assert result["success"] is False
    assert "Parser 'mineru' is not properly installed" in result["error"]
    assert PYTHON_LIMIT in result["error"]
    assert "pip install' or 'uv pip install'" not in result["error"]


@posix_only
def test_run_mineru_command_not_found_on_python_3_14_explains_the_limit(
    monkeypatch, tmp_path
):
    _python_without_mineru3(monkeypatch)
    _empty_path(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        MineruParser._run_mineru_command(tmp_path / "doc.pdf", tmp_path / "out")

    assert "mineru command not found" in str(excinfo.value)
    assert PYTHON_LIMIT in str(excinfo.value)


@posix_only
def test_initialization_fails_with_the_mineru_4_reason(monkeypatch, tmp_path):
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )
    rag = _make_rag(monkeypatch, tmp_path)

    result = asyncio.run(rag._ensure_lightrag_initialized())

    assert result["success"] is False
    assert "Parser 'mineru' is not properly installed" in result["error"]
    assert "MinerU 4.0.12" in result["error"]
    assert SUPPORTED_INSTALL in result["error"]
    assert rag._parser_installation_checked is False
    assert rag.lightrag is None

    with pytest.raises(RuntimeError) as excinfo:
        rag.verify_parser_installation_once()
    assert "MinerU 4.0.12" in str(excinfo.value)
    assert SUPPORTED_INSTALL in str(excinfo.value)


@posix_only
def test_batch_parser_warning_names_the_mineru_4_reason(monkeypatch, tmp_path, caplog):
    _fake_mineru_version(
        monkeypatch, tmp_path, "MinerU version: 4.0.12\nPython version: 3.12.13"
    )

    with caplog.at_level("WARNING", logger="raganything.batch_parser"):
        BatchParser(parser_type="mineru", show_progress=False)

    warning = next(
        record.getMessage()
        for record in caplog.records
        if record.name == "raganything.batch_parser"
    )
    assert "Mineru parser installation check failed" in warning
    assert "MinerU 4.0.12" in warning
    assert SUPPORTED_INSTALL in warning


# --------------------------------------------------------------------------
# MinerU command failures
# --------------------------------------------------------------------------


@posix_only
def test_cli_failure_shows_mineru_error_text(monkeypatch, tmp_path):
    _fake_mineru_failure(monkeypatch, tmp_path, MINERU4_USAGE_ERROR)

    with pytest.raises(MineruExecutionError) as excinfo:
        MineruParser._run_mineru_command(tmp_path / "doc.pdf", tmp_path / "out")

    exc = excinfo.value
    message = str(exc)
    assert exc.return_code == 2
    # The real error is now part of the exception message ...
    assert "No such option: -p" in message
    assert "Try 'mineru --help' for help." in message
    # Existing attribute keeps its meaning: stderr lines mentioning "error".
    assert len(exc.error_msg) == 1 and "Error" in exc.error_msg[0]
    assert "No such option: -p" in exc.output
    # ... without the box-drawing borders around it.
    assert "│" not in exc.output and "╰" not in exc.output
    # ... and is recognised as a MinerU 4.x CLI.
    assert exc.hint is not None
    assert "4.x is not supported" in exc.hint
    assert SUPPORTED_INSTALL in message


@posix_only
def test_cli_failure_output_is_bounded_to_the_tail(monkeypatch, tmp_path):
    _fake_mineru(
        monkeypatch,
        tmp_path,
        'i=0\nwhile [ "$i" -lt 500 ]; do echo "progress line $i" >&2; i=$((i+1)); done\n'
        'echo "RuntimeError: final failure" >&2\n'
        "exit 1\n",
    )

    with pytest.raises(MineruExecutionError) as excinfo:
        MineruParser._run_mineru_command(tmp_path / "doc.pdf", tmp_path / "out")

    output_lines = excinfo.value.output.splitlines()
    assert output_lines[0] == "Last 40 line(s) of MinerU stderr:"
    assert len(output_lines) == 41
    assert output_lines[-1] == "RuntimeError: final failure"
    assert output_lines[1] == "progress line 461"
    assert "progress line 0\n" not in str(excinfo.value)


@posix_only
def test_cli_failure_falls_back_to_stdout(monkeypatch, tmp_path):
    _fake_mineru(
        monkeypatch, tmp_path, 'echo "could not open input"\necho "giving up"\nexit 3\n'
    )

    with pytest.raises(MineruExecutionError) as excinfo:
        MineruParser._run_mineru_command(tmp_path / "doc.pdf", tmp_path / "out")

    exc = excinfo.value
    assert exc.return_code == 3
    assert exc.error_msg == []
    assert exc.output == (
        "Last 2 line(s) of MinerU stdout:\ncould not open input\ngiving up"
    )


@posix_only
def test_successful_run_does_not_raise(monkeypatch, tmp_path):
    _fake_mineru(monkeypatch, tmp_path, 'echo "loading models" >&2\nexit 0\n')

    MineruParser._run_mineru_command(tmp_path / "doc.pdf", tmp_path / "out")


def test_output_tail_strips_ansi_and_box_borders():
    lines = [
        "\x1b[31mValueError: boom\x1b[0m",
        "╭─ Error ───╮",
        "│ details │",
        "╰──────────╯",
        "   ",
    ]

    assert _mineru_output_tail(lines) == ["ValueError: boom", "Error", "details"]


def test_output_tail_is_bounded_in_characters():
    lines = [f"{i:03d} " + "x" * 296 for i in range(40)]

    tail = _mineru_output_tail(lines)

    assert sum(len(line) + 1 for line in tail) <= 4000
    assert tail[-1] == lines[-1]
    assert len(tail) == 13


def test_output_tail_keeps_the_end_of_one_huge_line():
    tail = _mineru_output_tail(["a" * 10000 + "END"])

    assert len(tail) == 1
    assert len(tail[0]) == 4000
    assert tail[0].endswith("END")


def test_no_output_section_when_mineru_printed_nothing():
    assert _format_mineru_output([], []) is None
    assert _format_mineru_output(["╰──╯", ""], ["  "]) is None


def test_execution_error_message_includes_output_and_inferred_hint():
    exc = MineruExecutionError(
        2,
        ["╭─ Error ─╮"],
        output="Last 2 line(s) of MinerU stderr:\nError\nNo such option: -p",
    )

    message = str(exc)
    assert message.startswith(
        "Mineru command failed with return code 2: ['╭─ Error ─╮']\n\n"
        "Last 2 line(s) of MinerU stderr:\nError\nNo such option: -p"
    )
    assert exc.hint is not None and SUPPORTED_INSTALL in exc.hint
    assert message.endswith(exc.hint)
