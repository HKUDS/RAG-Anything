"""Tests for the Parser URL detection and download helpers."""

import io
import socket
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
        ("ftp://example.com/x", False),
        ("file://localhost/etc/passwd", False),
    ],
)
def test_is_url(value, expected):
    assert Parser._is_url(value) is expected


def _fake_response(*, body: bytes = b"%PDF-1.4 fake", content_type: str = ""):
    response = MagicMock()
    headers = MagicMock()

    def _get(name, default=""):
        if name.lower() == "content-type":
            return content_type or default
        if name.lower() == "content-length":
            return default
        return default

    headers.get.side_effect = _get
    response.headers = headers
    response.read = io.BytesIO(body).read
    response.close = MagicMock()
    return response


def _public_addrinfo(host, port, *args, **kwargs):
    """Pretend DNS always returns a public address (avoids real network)."""
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("93.184.216.34", port or 443),
        )
    ]


def _patch_download_stack(response):
    """Patch DNS safety checks and opener.open used by _download_file."""
    opener = MagicMock()
    opener.open.return_value = response
    return (
        patch.object(Parser, "_ensure_url_safe_for_download", return_value=None),
        patch("urllib.request.build_opener", return_value=opener),
    )


def test_download_file_uses_extension_from_url_path(tmp_path):
    parser = Parser()
    response = _fake_response()
    safe_patch, opener_patch = _patch_download_stack(response)

    with safe_patch, opener_patch as mock_build:
        downloaded = parser._download_file("https://example.com/docs/report.pdf")

    try:
        assert downloaded.suffix == ".pdf"
        assert downloaded.exists()
        assert downloaded.read_bytes() == b"%PDF-1.4 fake"
        mock_build.assert_called_once()
        opener = mock_build.return_value
        opener.open.assert_called_once()
        _, kwargs = opener.open.call_args
        assert kwargs.get("timeout") == 30, "must pass an explicit timeout"
    finally:
        if downloaded.exists():
            downloaded.unlink()


def test_download_file_infers_extension_from_content_type(tmp_path):
    parser = Parser()
    response = _fake_response(content_type="application/pdf; charset=utf-8")
    safe_patch, opener_patch = _patch_download_stack(response)

    with safe_patch, opener_patch:
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

    response = _fake_response()
    response.read = MagicMock(side_effect=OSError("connection reset"))
    safe_patch, opener_patch = _patch_download_stack(response)

    with (
        safe_patch,
        opener_patch,
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
    """When opener.open itself fails, no temp file should be created or leaked."""
    parser = Parser()
    created: list[Path] = []

    real_mkstemp = __import__("tempfile").mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        created.append(Path(name))
        return fd, name

    opener = MagicMock()
    opener.open.side_effect = TimeoutError("stalled")

    with (
        patch.object(Parser, "_ensure_url_safe_for_download", return_value=None),
        patch("urllib.request.build_opener", return_value=opener),
        patch("tempfile.mkstemp", side_effect=tracking_mkstemp),
    ):
        with pytest.raises(RuntimeError, match="Failed to download"):
            parser._download_file("https://slow.example.com/file.pdf")

    for p in created:
        assert not p.exists(), f"temp file {p} leaked"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file.pdf",
        "file://localhost/etc/passwd",
        "http://127.0.0.1/secret.pdf",
        "http://localhost/secret.pdf",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/secret.pdf",
    ],
)
def test_download_file_rejects_unsafe_urls(url):
    parser = Parser()
    with pytest.raises(RuntimeError, match="Failed to download"):
        parser._download_file(url)


def test_ensure_url_safe_allows_public_hostname():
    with patch("socket.getaddrinfo", side_effect=_public_addrinfo):
        parsed = Parser._ensure_url_safe_for_download(
            "https://example.com/docs/report.pdf"
        )
    assert parsed.hostname == "example.com"


def test_ensure_url_safe_rejects_dns_to_private_ip():
    def _private_addrinfo(host, port, *args, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("10.0.0.5", port or 80),
            )
        ]

    with patch("socket.getaddrinfo", side_effect=_private_addrinfo):
        with pytest.raises(ValueError, match="Blocked address"):
            Parser._ensure_url_safe_for_download("https://evil.example/file.pdf")
