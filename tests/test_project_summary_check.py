from pathlib import Path

from scripts import check_project_summary as summary_check

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _valid_summary(records: int = 1, link: str = "docs") -> str:
    record_rows = "\n".join(
        f"| 2026-07-{index + 1:02d} | task-{index} | test | passed | docs | pytest | none |"
        for index in range(records)
    )
    return f"""# Test 项目核心总结

## 0. 元信息与使用规则
| 项目 | 当前值 |
|---|---|
| 最后核验日期 | 2026-07-30 |
| 核验分支 | test |
| 基准提交 | abc123 |
| 工作区状态 | clean |

## 1. 项目定位与用户
## 2. 当前能力状态
### 稳定现状
### 进行中
### 计划
### 已废弃
## 3. 架构与关键数据流
## 4. 核心目录导航
[`docs`]({link})
## 5. 核心业务规则
## 6. 技术栈、配置与运行
## 7. 开发约束与最低验证
## 8. 已知风险与常见问题
## 9. 总结更新矩阵
## 10. 近期任务记录
| 日期 | 任务/change | 类型 | 结果 | 影响范围 | 验证 | 经验/风险 |
|---|---|---|---|---|---|---|
{record_rows}

## 11. 历史里程碑
## 12. 详细资料索引
"""


def _write_summary(tmp_path: Path, content: str) -> Path:
    repository = tmp_path / "repository"
    (repository / "docs").mkdir(parents=True)
    path = repository / "PROJECT_SUMMARY.md"
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _codes(findings: list[summary_check.Finding]) -> set[str]:
    return {finding.code for finding in findings}


def test_repository_summary_passes_quality_check() -> None:
    findings, _, _ = summary_check.check_summary(REPOSITORY_ROOT / "PROJECT_SUMMARY.md")
    assert findings == []


def test_valid_summary_fixture_passes(tmp_path: Path) -> None:
    content = _valid_summary().replace("passed", r"passed \| acceptable")
    path = _write_summary(tmp_path, content)
    findings, line_count, byte_count = summary_check.check_summary(path)
    assert findings == []
    assert line_count > 0
    assert byte_count == len(content.encode("utf-8"))


def test_limits_are_inclusive_and_record_limit_is_15(tmp_path: Path) -> None:
    path = _write_summary(tmp_path / "base", _valid_summary(records=15))
    _, line_count, byte_count = summary_check.check_summary(path)

    at_limit, _, _ = summary_check.check_summary(
        path, max_lines=line_count, max_bytes=byte_count, max_records=15
    )
    assert not {"LINE_LIMIT", "BYTE_LIMIT", "RECORD_LIMIT"} & _codes(at_limit)

    over_limit, _, _ = summary_check.check_summary(
        path, max_lines=line_count - 1, max_bytes=byte_count - 1, max_records=14
    )
    assert {"LINE_LIMIT", "BYTE_LIMIT", "RECORD_LIMIT"} <= _codes(over_limit)

    sixteen = _write_summary(tmp_path / "sixteen", _valid_summary(records=16))
    findings, _, _ = summary_check.check_summary(sixteen, max_records=15)
    assert "RECORD_LIMIT" in _codes(findings)


def test_default_byte_limit_is_30_kib(tmp_path: Path) -> None:
    path = _write_summary(tmp_path, _valid_summary() + "x" * (21 * 1024))

    findings, _, byte_count = summary_check.check_summary(path)

    assert byte_count > 20 * 1024
    assert byte_count <= 30 * 1024
    assert "BYTE_LIMIT" not in _codes(findings)


def test_structure_schema_and_iso_date_errors_are_aggregated(tmp_path: Path) -> None:
    content = _valid_summary().replace("### 已废弃", "### legacy")
    content = content.replace("## 8. 已知风险与常见问题", "## 8. notes")
    content = content.replace("2026-07-01", "2026-7-1")
    content = content.replace("| 经验/风险 |", "| extra |")
    path = _write_summary(tmp_path, content)

    findings, _, _ = summary_check.check_summary(path)
    assert {"STATE", "SECTION", "RECORD_HEADER", "RECORD_DATE"} <= _codes(findings)


def test_local_link_rules_cover_missing_absolute_and_escape(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    content = _valid_summary(link="missing.md")
    content += "\n[absolute](C:/private/file.md)\n[escape](../outside.md)\n"
    path = repository / "PROJECT_SUMMARY.md"
    path.write_text(content, encoding="utf-8")

    findings, _, _ = summary_check.check_summary(path)
    assert {"LINK_MISSING", "LINK_ABSOLUTE", "LINK_ESCAPE"} <= _codes(findings)


def test_external_anchor_and_mail_links_are_not_local_targets(tmp_path: Path) -> None:
    content = _valid_summary()
    content += "\n[web](https://example.com) [anchor](#section) [mail](mailto:test@example.com)\n"
    path = _write_summary(tmp_path, content)

    findings, _, _ = summary_check.check_summary(path)
    assert not {code for code in _codes(findings) if code.startswith("LINK_")}


def test_secret_diagnostics_are_redacted_and_placeholders_are_allowed(
    tmp_path: Path, capsys
) -> None:
    content = _valid_summary()
    content += "\nAPI_KEY=sk-this-is-a-real-looking-secret-1234567890\n"
    content += "-----BEGIN PRIVATE KEY-----\n"
    content += "JWT_SECRET=<your-secret>\n"
    content += "JWT_SECRET: required in production\n"
    content += 'ADMIN_PASSWORD: "actual password value"\n'
    content += "trailing space   \n"
    path = _write_summary(tmp_path, content)

    result = summary_check.main([str(path)])
    output = capsys.readouterr().out
    assert result == 1
    for code in ("TOKEN", "SECRET_ASSIGNMENT", "PRIVATE_KEY", "TRAILING_WHITESPACE"):
        assert f"[{code}]" in output
    assert output.count("[SECRET_ASSIGNMENT]") == 2
    assert "sk-this-is-a-real-looking-secret" not in output
    assert "JWT_SECRET" not in output


def test_missing_and_non_utf8_files_are_fatal(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    assert summary_check.main([str(missing)]) == 2

    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff\xfe\x00")
    assert summary_check.main([str(invalid)]) == 2


def test_crlf_and_lf_have_equal_normalized_size(tmp_path: Path) -> None:
    content = _valid_summary()
    lf_path = _write_summary(tmp_path / "lf", content)
    crlf_path = _write_summary(tmp_path / "crlf", content)
    crlf_path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

    _, lf_lines, lf_bytes = summary_check.check_summary(lf_path)
    _, crlf_lines, crlf_bytes = summary_check.check_summary(crlf_path)
    assert (lf_lines, lf_bytes) == (crlf_lines, crlf_bytes)


def test_workflow_keeps_the_quality_check_non_blocking() -> None:
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "project-summary-quality.yml"
    ).read_text(encoding="utf-8")
    assert "id: summary_check" in workflow
    assert "continue-on-error: true" in workflow
    assert "if: steps.summary_check.outcome == 'failure'" in workflow
    assert "python scripts/check_project_summary.py" in workflow
