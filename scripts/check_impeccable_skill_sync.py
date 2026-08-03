"""Synchronize the GitHub-discovered Impeccable skill from the canonical copy."""

from __future__ import annotations

import argparse
from pathlib import Path


CANONICAL_RELATIVE = Path(".agents/skills/impeccable")
MIRROR_RELATIVE = Path(".github/skills/impeccable")
_CANONICAL_PATH = ".Codex/skills/impeccable"
_MIRROR_PATH = ".github/skills/impeccable"
_AGENT_ONLY_FRONT_MATTER = "allowed-tools:\n  - Bash(npx impeccable *)\n"


def mirror_text(relative_path: Path, content: str) -> str:
    """Apply the documented discovery-host substitutions to canonical text."""
    content = content.replace(_CANONICAL_PATH, _MIRROR_PATH)
    if relative_path == Path("SKILL.md"):
        content = content.replace(_AGENT_ONLY_FRONT_MATTER, "")
    return content


def sync_skill(source: Path, target: Path, *, write: bool) -> list[Path]:
    """Return mirror paths that differ and optionally refresh them."""
    differences: list[Path] = []
    source_files = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}
    target_files = {path.relative_to(target) for path in target.rglob("*") if path.is_file()} if target.exists() else set()

    for relative_path in sorted(source_files | target_files):
        source_path = source / relative_path
        target_path = target / relative_path
        expected = mirror_text(relative_path, source_path.read_text(encoding="utf-8")) if source_path.exists() else None
        actual = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if expected == actual:
            continue
        differences.append(relative_path)
        if write:
            if expected is None:
                target_path.unlink()
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(expected, encoding="utf-8", newline="\n")
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="refresh the GitHub mirror")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    differences = sync_skill(
        root / CANONICAL_RELATIVE,
        root / MIRROR_RELATIVE,
        write=args.write,
    )
    if not differences:
        return 0
    for relative_path in differences:
        print(relative_path.as_posix())
    return 0 if args.write else 1


if __name__ == "__main__":
    raise SystemExit(main())
