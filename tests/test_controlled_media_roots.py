"""Tests for project-owned controlled media roots.

Covers fix-citation-docnames-and-media-recall: exact `output`/`output_*`
directories, the OUTPUT_DIR override (absolute and relative), rejection of
project-outside paths, symlink filtering, and the TTL cache reset hook.
"""

from pathlib import Path

import pytest

import raganything.services.odl_media_delivery as odl_media_delivery
from raganything.services.odl_media_delivery import (
    _controlled_roots,
    _reset_controlled_roots_cache,
    validate_legacy_media_path,
)


def _write_png(path: Path, size: int = 16) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * size))


@pytest.fixture(autouse=True)
def _project_root(tmp_path, monkeypatch):
    """Pin the project root to a temp dir and clear the TTL cache."""
    _reset_controlled_roots_cache()
    monkeypatch.setattr(odl_media_delivery, "_project_root", lambda: tmp_path)
    yield tmp_path
    _reset_controlled_roots_cache()


def test_output_and_output_prefix_dirs_are_controlled(_project_root):
    root = _project_root
    output = root / "output"
    output.mkdir()
    output_demo = root / "output_demo"
    output_demo.mkdir()
    _write_png(output / "img.png")
    _write_png(output_demo / "img2.png")

    resolved, reason = validate_legacy_media_path(output / "img.png")
    assert resolved is not None and reason is None
    resolved, reason = validate_legacy_media_path(output_demo / "img2.png")
    assert resolved is not None and reason is None

    roots = _controlled_roots()
    assert output.resolve() in roots
    assert output_demo.resolve() in roots


def test_outside_project_root_is_rejected(_project_root):
    root = _project_root
    outside = root / "outside.png"
    _write_png(outside)

    resolved, reason = validate_legacy_media_path(outside)

    assert resolved is None
    assert reason == "outside_controlled_root"


def test_output_dir_env_override_allows_custom_directory(_project_root, monkeypatch):
    root = _project_root
    custom = root / "out_custom"
    custom.mkdir()
    _write_png(custom / "custom.png")

    monkeypatch.setenv("OUTPUT_DIR", str(custom))
    _reset_controlled_roots_cache()

    resolved, reason = validate_legacy_media_path(custom / "custom.png")
    assert resolved is not None and reason is None


def test_relative_output_dir_is_absolutized_against_project_root(_project_root, monkeypatch):
    root = _project_root
    target = root / "out_rel"
    target.mkdir()

    monkeypatch.setenv("OUTPUT_DIR", "out_rel")
    _reset_controlled_roots_cache()

    assert target.resolve() in _controlled_roots()


def test_output_like_names_without_underscore_are_not_controlled(_project_root):
    root = _project_root
    for name in ("outputs", "output-backup", "outputx"):
        (root / name).mkdir()
        _write_png(root / name / "x.png")

    roots = _controlled_roots()
    assert all(
        (root / name).resolve() not in roots
        for name in ("outputs", "output-backup", "outputx")
    )


def test_symlink_output_dir_is_excluded(_project_root):
    root = _project_root
    real = root / "real_out"
    real.mkdir()
    link = root / "output_link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    roots = _controlled_roots()
    assert link.resolve() not in roots


def test_controlled_roots_cache_is_ttl_cached_and_resettable(_project_root, monkeypatch):
    root = _project_root
    first = root / "out_first"
    first.mkdir()
    _write_png(first / "a.png")
    monkeypatch.setenv("OUTPUT_DIR", str(first))
    _reset_controlled_roots_cache()
    assert first.resolve() in _controlled_roots()

    second = root / "out_second"
    second.mkdir()
    _write_png(second / "b.png")
    monkeypatch.setenv("OUTPUT_DIR", str(second))
    # The cached tuple is still served until TTL expiry or an explicit reset.
    assert second.resolve() not in _controlled_roots()
    assert first.resolve() in _controlled_roots()

    _reset_controlled_roots_cache()
    assert second.resolve() in _controlled_roots()
