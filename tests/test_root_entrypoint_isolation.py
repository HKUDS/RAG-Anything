from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]

RETIRED_ENTRYPOINTS = (
    "server.py.integration-backup",
    "_apply_changes.py",
    "query.py",
    "upload_and_query.py",
)

IGNORED_ROOT_OUTPUTS = (
    "worker_output.txt",
    ".tmp-redesign-full-suite.xml",
    "38692",
    "cd",
)


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_retired_root_entrypoints_are_absent_and_server_remains():
    assert (ROOT / "server.py").is_file()
    assert not any((ROOT / path).exists() for path in RETIRED_ENTRYPOINTS)


def test_generated_root_outputs_are_ignored_without_affecting_nested_names():
    for path in IGNORED_ROOT_OUTPUTS:
        assert not (ROOT / path).exists()
        assert _is_ignored(path)
        assert not _is_ignored(f"nested/{path}")


def test_excluded_json_ownership_remains_unchanged():
    stress_report = ROOT / "sse_stress_summary.json"
    metadata_mirror = ROOT / "rag_storage_kb_meta.json"

    assert stress_report.is_file()
    assert metadata_mirror.is_file()
    assert not _is_ignored(stress_report.name)
    assert _is_ignored(metadata_mirror.name)

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", stress_report.name],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0
