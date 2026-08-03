import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_impeccable_skill_sync.py"
_SPEC = importlib.util.spec_from_file_location("check_impeccable_skill_sync", _SCRIPT)
checker = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(checker)


def test_mirror_transform_only_changes_host_specific_metadata():
    source = "---\nallowed-tools:\n  - Bash(npx impeccable *)\n---\nnode .Codex/skills/impeccable/scripts/context.mjs\n"

    assert checker.mirror_text(Path("SKILL.md"), source) == (
        "---\n---\nnode .github/skills/impeccable/scripts/context.mjs\n"
    )


def test_repository_skill_mirror_is_current():
    root = Path(__file__).resolve().parents[1]

    assert checker.sync_skill(
        root / checker.CANONICAL_RELATIVE,
        root / checker.MIRROR_RELATIVE,
        write=False,
    ) == []
