"""Tests for the Parser URL detection and download helpers."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_parser_class():
    """Load Parser without importing the heavy raganything package."""
    import importlib.util

    module_path = Path(__file__).resolve().parents[1] / "raganything" / "parser.py"
    spec = importlib.util.spec_from_file_location("_raganything_parser", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Parser


Parser = _load_parser_class()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.com/file.pdf", True),
        ("http://example.com/path?id=1", True),
        ("/local/path/file.pdf", False),
        ("file.pdf", False),
        ("", False),
        ("ftp://example.com/x", True),
    ],
)
def test_is_url(value, expected):
    assert Parser._is_url(value) is expected


def _fake_response(*, body: bytes = b"%PDF-1.4 fake", content_type: str = ""):
    response = MagicMock()
    response.headers.get.return_value = content_type
    response.read = io.BytesIO(body).read
    response.close = MagicMock()
    return response


def test_download_file_uses_extension_from_url_path(tmp_path):
    parser = Parser()
    response = _fake_response()

    with patch("urllib.request.urlopen", return_value=response) as mock_open:
        downloaded = parser._download_file("https://example.com/docs/report.pdf")

    try:
        assert downloaded.suffix == ".pdf"
        assert downloaded.exists()
        assert downloaded.read_bytes() == b"%PDF-1.4 fake"
        mock_open.assert_called_once()
        _, kwargs = mock_open.call_args
        assert kwargs.get("timeout") == 30, "must pass an explicit timeout"
    finally:
        if downloaded.exists():
            downloaded.unlink()


def test_download_file_infers_extension_from_content_type(tmp_path):
    parser = Parser()
    response = _fake_response(content_type="application/pdf; charset=utf-8")

    with patch("urllib.request.urlopen", return_value=response):
        downloaded = parser._download_file("https://example.com/download?id=123")

    try:
        assert downloaded.suffix == ".pdf"
        assert downloaded.exists()
    finally:
        if downloaded.exists():
            downloaded.unlink()


def test_download_file_cleans_up_temp_on_failure():
    parser = Parser()
    leaked: list[Path] = []

    real_mkstemp = __import__("tempfile").mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        leaked.append(Path(name))
        return fd, name

    response = MagicMock()
    response.headers.get.return_value = ""
    response.read.side_effect = OSError("connection reset")
    response.close = MagicMock()

    with (
        patch("urllib.request.urlopen", return_value=response),
        patch("tempfile.mkstemp", side_effect=tracking_mkstemp),
    ):
        with pytest.raises(RuntimeError, match="Failed to download"):
            parser._download_file("https://example.com/file.pdf")

    assert leaked, "temp file should have been created"
    for p in leaked:
        assert not p.exists(), (
            f"temp file {p} leaked after failed download — exception path "
            "must clean it up"
        )
    response.close.assert_called_once()


def test_download_file_cleans_up_temp_on_urlopen_failure():
    """When urlopen itself fails, no temp file should be created or leaked."""
    parser = Parser()
    created: list[Path] = []

    real_mkstemp = __import__("tempfile").mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        created.append(Path(name))
        return fd, name

    with (
        patch("urllib.request.urlopen", side_effect=TimeoutError("stalled")),
        patch("tempfile.mkstemp", side_effect=tracking_mkstemp),
    ):
        with pytest.raises(RuntimeError, match="Failed to download"):
            parser._download_file("https://slow.example.com/file.pdf")

    for p in created:
        assert not p.exists(), f"temp file {p} leaked"
