#!/usr/bin/env python3
"""Validate the repository's compact project summary."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote

DEFAULT_MAX_LINES = 350
DEFAULT_MAX_BYTES = 30 * 1024
DEFAULT_MAX_RECORDS = 15

REQUIRED_SECTIONS = {
    "metadata": ("元信息",),
    "project scope": ("项目定位",),
    "current state": ("当前能力", "状态"),
    "architecture": ("架构", "数据流"),
    "directory guide": ("目录", "导航"),
    "business rules": ("业务规则",),
    "stack and runtime": ("技术栈", "配置", "运行"),
    "development constraints": ("开发约束", "验证"),
    "known risks": ("风险", "问题"),
    "update matrix": ("总结更新",),
    "recent tasks": ("近期任务",),
    "milestones": ("历史", "里程碑"),
    "references": ("资料", "索引"),
}
REQUIRED_METADATA = ("最后核验日期", "核验分支", "基准提交", "工作区状态")
REQUIRED_STATES = ("稳定现状", "进行中", "计划", "已废弃")
RECORD_HEADER = (
    "日期",
    "任务/change",
    "类型",
    "结果",
    "影响范围",
    "验证",
    "经验/风险",
)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(?:<(?P<angled>[^>]+)>|(?P<plain>[^\s)]+))"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
KNOWN_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"
)
CONFIG_ASSIGNMENT_RE = re.compile(
    r"(?P<name>[A-Z][A-Z0-9_]*)\s*(?P<separator>=|:)\s*(?P<value>[^|#]+)"
)
SECRET_NAME_MARKERS = (
    "API_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "ACCESS_KEY",
    "PRIVATE_KEY",
)
CREDENTIAL_URL_RE = re.compile(r"https?://[^\s/:]+:[^\s/@]+@", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    line: int | None = None
    fatal: bool = False


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_table_row(line: str) -> list[str]:
    return [
        cell.replace(r"\|", "|").strip()
        for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))
    ]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _looks_like_placeholder(value: str) -> bool:
    cleaned = value.strip().strip("`\"'").strip().lower()
    if not cleaned:
        return True
    if (cleaned.startswith("<") and cleaned.endswith(">")) or cleaned.startswith("${"):
        return True
    exact_placeholders = {
        "none",
        "null",
        "unset",
        "redacted",
        "changeme",
        "change-me",
        "***",
        "xxxxx",
    }
    if cleaned in exact_placeholders:
        return True
    return any(
        marker in cleaned
        for marker in ("placeholder", "example", "your-", "your_", "replace-me")
    )


def _colon_value_looks_secret(value: str) -> bool:
    cleaned = value.strip().strip("`").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        return True
    return len(cleaned) >= 8 and not any(character.isspace() for character in cleaned)


def _headings(text: str, level: int | None = None) -> list[tuple[int, str, int]]:
    headings: list[tuple[int, str, int]] = []
    for match in HEADING_RE.finditer(text):
        heading_level = len(match.group(1))
        if level is None or heading_level == level:
            headings.append((heading_level, match.group(2).strip(), match.start()))
    return headings


def _check_structure(text: str) -> list[Finding]:
    findings: list[Finding] = []
    headings = _headings(text)
    h1 = [title for level, title, _ in headings if level == 1]
    if not h1 or "项目核心总结" not in h1[0]:
        findings.append(Finding("H1", "Missing the project-summary H1 heading."))

    h2 = [title for level, title, _ in headings if level == 2]
    for label, fragments in REQUIRED_SECTIONS.items():
        if not any(all(fragment in title for fragment in fragments) for title in h2):
            findings.append(Finding("SECTION", f"Missing required section: {label}."))

    h3 = [title for level, title, _ in headings if level == 3]
    for state in REQUIRED_STATES:
        if not any(title.startswith(state) for title in h3):
            findings.append(Finding("STATE", f"Missing state category: {state}."))

    for field in REQUIRED_METADATA:
        if field not in text:
            findings.append(Finding("METADATA", f"Missing metadata field: {field}."))
    return findings


def _recent_task_lines(text: str) -> tuple[list[tuple[int, str]], int | None]:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = re.match(r"^##\s+(.+)$", line)
        if match and "近期任务" in match.group(1):
            start = index + 1
            break
    if start is None:
        return [], None

    table_lines: list[tuple[int, str]] = []
    table_started = False
    for index in range(start, len(lines)):
        line = lines[index]
        if line.startswith("## "):
            break
        if line.lstrip().startswith("|"):
            table_started = True
            table_lines.append((index + 1, line))
        elif table_started and line.strip():
            break
    return table_lines, start + 1


def _check_recent_tasks(text: str, max_records: int) -> list[Finding]:
    findings: list[Finding] = []
    table_lines, section_line = _recent_task_lines(text)
    if len(table_lines) < 2:
        return [
            Finding(
                "RECORD_TABLE",
                "Recent-task section must contain a Markdown table.",
                section_line,
            )
        ]

    header_line, header_text = table_lines[0]
    header = _split_table_row(header_text)
    if tuple(header) != RECORD_HEADER:
        findings.append(
            Finding(
                "RECORD_HEADER",
                "Recent-task table must use the required seven-column schema.",
                header_line,
            )
        )

    separator_line, separator_text = table_lines[1]
    separator = _split_table_row(separator_text)
    if len(separator) != len(RECORD_HEADER) or not _is_separator_row(separator):
        findings.append(
            Finding(
                "RECORD_SEPARATOR",
                "Recent-task table has an invalid separator row.",
                separator_line,
            )
        )

    records = table_lines[2:]
    if len(records) > max_records:
        findings.append(
            Finding(
                "RECORD_LIMIT",
                f"Recent-task table has {len(records)} records; maximum is {max_records}.",
                records[max_records][0],
            )
        )

    for line_number, row_text in records:
        cells = _split_table_row(row_text)
        if len(cells) != len(RECORD_HEADER):
            findings.append(
                Finding(
                    "RECORD_COLUMNS",
                    f"Recent-task row has {len(cells)} columns; expected 7.",
                    line_number,
                )
            )
            continue
        try:
            parsed_date = date.fromisoformat(cells[0])
        except ValueError:
            findings.append(
                Finding(
                    "RECORD_DATE",
                    "Recent-task date must be a valid ISO date (YYYY-MM-DD).",
                    line_number,
                )
            )
        else:
            if parsed_date.isoformat() != cells[0]:
                findings.append(
                    Finding(
                        "RECORD_DATE",
                        "Recent-task date must use zero-padded ISO format (YYYY-MM-DD).",
                        line_number,
                    )
                )
    return findings


def _has_exact_case(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False

    current = root
    for part in relative.parts:
        try:
            names = {child.name for child in current.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        current /= part
    return True


def _check_links(text: str, summary_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    root = summary_path.parent.resolve()
    for match in MARKDOWN_LINK_RE.finditer(text):
        raw_target = (match.group("angled") or match.group("plain")).strip()
        line_number = _line_number(text, match.start())
        if raw_target.startswith("#") or re.match(
            r"^(?:https?|mailto|tel):", raw_target, re.IGNORECASE
        ):
            continue
        if raw_target.lower().startswith("file:"):
            findings.append(
                Finding("LINK_FILE_URI", "file:// links are not allowed.", line_number)
            )
            continue

        target_without_anchor = raw_target.split("#", 1)[0].split("?", 1)[0]
        decoded_target = unquote(target_without_anchor)
        if not decoded_target:
            continue
        if decoded_target.startswith(("/", "\\")) or re.match(
            r"^[A-Za-z]:[\\/]", decoded_target
        ):
            findings.append(
                Finding(
                    "LINK_ABSOLUTE",
                    "Local links must be repository-relative.",
                    line_number,
                )
            )
            continue

        candidate = (root / Path(decoded_target)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            findings.append(
                Finding(
                    "LINK_ESCAPE",
                    "Local link escapes the repository root.",
                    line_number,
                )
            )
            continue

        if not candidate.exists():
            findings.append(
                Finding(
                    "LINK_MISSING",
                    f"Local link target does not exist: {raw_target}",
                    line_number,
                )
            )
        elif not _has_exact_case(candidate, root):
            findings.append(
                Finding(
                    "LINK_CASE",
                    f"Local link casing does not match: {raw_target}",
                    line_number,
                )
            )
    return findings


def _check_secrets_and_whitespace(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if re.search(r"[ \t]+$", line):
            findings.append(
                Finding(
                    "TRAILING_WHITESPACE", "Line has trailing whitespace.", line_number
                )
            )
        if PRIVATE_KEY_RE.search(line):
            findings.append(
                Finding(
                    "PRIVATE_KEY",
                    "Possible private-key material detected.",
                    line_number,
                )
            )
        if JWT_RE.search(line):
            findings.append(
                Finding("JWT", "Possible JWT credential detected.", line_number)
            )
        if KNOWN_TOKEN_RE.search(line):
            findings.append(
                Finding("TOKEN", "Possible access credential detected.", line_number)
            )
        if CREDENTIAL_URL_RE.search(line):
            findings.append(
                Finding(
                    "URL_CREDENTIAL", "URL appears to contain credentials.", line_number
                )
            )
        for assignment in CONFIG_ASSIGNMENT_RE.finditer(line):
            name = assignment.group("name")
            value = assignment.group("value")
            assignment_looks_secret = assignment.group("separator") == "=" or (
                assignment.group("separator") == ":"
                and _colon_value_looks_secret(value)
            )
            if (
                any(marker in name for marker in SECRET_NAME_MARKERS)
                and assignment_looks_secret
                and not _looks_like_placeholder(value)
            ):
                findings.append(
                    Finding(
                        "SECRET_ASSIGNMENT",
                        f"Possible credential assignment detected for {name}.",
                        line_number,
                    )
                )
    return findings


def check_summary(
    summary_path: Path,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> tuple[list[Finding], int, int]:
    """Return findings, normalized line count, and normalized UTF-8 byte count."""
    if not summary_path.is_file():
        return (
            [
                Finding(
                    "FILE_MISSING", "Project summary file does not exist.", fatal=True
                )
            ],
            0,
            0,
        )
    try:
        raw = summary_path.read_bytes()
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return (
            [Finding("UTF8", "Project summary is not valid UTF-8.", fatal=True)],
            0,
            0,
        )
    except OSError as exc:
        return (
            [Finding("READ", f"Unable to read project summary: {exc}", fatal=True)],
            0,
            0,
        )

    normalized = _normalise_newlines(text)
    line_count = len(normalized.splitlines())
    byte_count = len(normalized.encode("utf-8"))
    findings: list[Finding] = []
    if line_count > max_lines:
        findings.append(
            Finding(
                "LINE_LIMIT", f"Summary has {line_count} lines; maximum is {max_lines}."
            )
        )
    if byte_count > max_bytes:
        findings.append(
            Finding(
                "BYTE_LIMIT", f"Summary has {byte_count} bytes; maximum is {max_bytes}."
            )
        )

    findings.extend(_check_structure(normalized))
    findings.extend(_check_recent_tasks(normalized, max_records))
    findings.extend(_check_links(normalized, summary_path))
    findings.extend(_check_secrets_and_whitespace(normalized))
    return findings, line_count, byte_count


def _escape_workflow_command(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit_finding(path: Path, finding: Finding, github_actions: bool) -> None:
    location = str(path)
    if github_actions:
        level = "error" if finding.fatal else "warning"
        properties = f"file={_escape_workflow_command(location)}"
        if finding.line is not None:
            properties += f",line={finding.line}"
        message = _escape_workflow_command(f"[{finding.code}] {finding.message}")
        print(f"::{level} {properties}::{message}")
        return

    suffix = f":{finding.line}" if finding.line is not None else ""
    print(f"ERROR [{finding.code}] {location}{suffix}: {finding.message}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=repository_root / "PROJECT_SUMMARY.md",
        help="summary path (default: repository-root PROJECT_SUMMARY.md)",
    )
    parser.add_argument("--max-lines", type=_positive_int, default=DEFAULT_MAX_LINES)
    parser.add_argument("--max-bytes", type=_positive_int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--max-recent-records", type=_positive_int, default=DEFAULT_MAX_RECORDS
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.path.resolve()
    findings, line_count, byte_count = check_summary(
        path,
        max_lines=args.max_lines,
        max_bytes=args.max_bytes,
        max_records=args.max_recent_records,
    )
    github_actions = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    for finding in findings:
        _emit_finding(path, finding, github_actions)

    if findings:
        print(
            f"PROJECT_SUMMARY quality check found {len(findings)} issue(s) "
            f"({line_count} lines, {byte_count} UTF-8 bytes)."
        )
        return 2 if any(finding.fatal for finding in findings) else 1

    print(
        f"PROJECT_SUMMARY quality check passed "
        f"({line_count} lines, {byte_count} UTF-8 bytes)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
