"""Tests for optional public URL mapping of local media paths."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "asset_urls",
    _ROOT / "raganything" / "asset_urls.py",
)
assert _SPEC and _SPEC.loader
_asset_urls = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_asset_urls)

attach_public_media_urls = _asset_urls.attach_public_media_urls
public_url_for_local_path = _asset_urls.public_url_for_local_path
MEDIA_PATH_FIELDS = _asset_urls.MEDIA_PATH_FIELDS
_MISCONFIG_WARNED = _asset_urls._MISCONFIG_WARNED


@pytest.fixture(autouse=True)
def _clear_misconfig_state():
    _MISCONFIG_WARNED.clear()
    yield
    _MISCONFIG_WARNED.clear()


def test_public_url_builds_from_strip_prefix(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    img = root / "doc" / "images" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")

    url = public_url_for_local_path(
        str(img.resolve()),
        base_url="https://cdn.example.com/assets",
        strip_prefix=str(root),
    )
    assert url == "https://cdn.example.com/assets/doc/images/a.png"


def test_attach_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "bundle"
    root.mkdir()
    img = root / "fig.png"
    img.write_bytes(b"x")

    monkeypatch.setenv(
        "RAGANYTHING_PUBLIC_ASSET_BASE_URL", "https://bucket.s3.amazonaws.com/proj"
    )
    monkeypatch.setenv("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", str(root.resolve()))

    item: dict = {"type": "image", "img_path": str(img.resolve())}
    attach_public_media_urls(item)

    assert item["img_path"] == str(img.resolve())
    assert item["img_path_public_url"] == "https://bucket.s3.amazonaws.com/proj/fig.png"


def test_skips_when_already_http(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAGANYTHING_PUBLIC_ASSET_BASE_URL", "https://x.com")
    monkeypatch.setenv("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", "/var")

    item = {"img_path": "https://cdn/a.png"}
    attach_public_media_urls(item)
    assert "img_path_public_url" not in item


def test_all_media_fields_documented():
    # Guardrail so new parser fields stay in sync with attach_public_media_urls
    assert "img_path" in MEDIA_PATH_FIELDS


def test_warns_once_when_only_base_url_is_set(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setenv("RAGANYTHING_PUBLIC_ASSET_BASE_URL", "https://x.com")
    monkeypatch.delenv("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", raising=False)

    item = {"img_path": "/var/rag/out/a.png"}
    with caplog.at_level(logging.WARNING, logger="raganything.asset_urls"):
        attach_public_media_urls(item)
        attach_public_media_urls(item)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "STRIP_PREFIX" in warnings[0].getMessage()
    assert "img_path_public_url" not in item


def test_warns_once_when_only_strip_prefix_is_set(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.delenv("RAGANYTHING_PUBLIC_ASSET_BASE_URL", raising=False)
    monkeypatch.setenv("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", "/var")

    item = {"img_path": "/var/a.png"}
    with caplog.at_level(logging.WARNING, logger="raganything.asset_urls"):
        attach_public_media_urls(item)
        attach_public_media_urls(item)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "BASE_URL" in warnings[0].getMessage()
    assert "img_path_public_url" not in item


def test_silent_when_neither_env_is_set(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.delenv("RAGANYTHING_PUBLIC_ASSET_BASE_URL", raising=False)
    monkeypatch.delenv("RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX", raising=False)

    item = {"img_path": "/var/a.png"}
    with caplog.at_level(logging.WARNING, logger="raganything.asset_urls"):
        attach_public_media_urls(item)

    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "img_path_public_url" not in item
