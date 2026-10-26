"""WeasyPrint loads only resources from the Markdown file's directory.

The Markdown being converted is untrusted: WeasyPrint's default fetcher
requested any remote URL it referenced and embedded any local file (images,
stylesheets, PDF attachments). These run the real WeasyPrint.
"""

import base64
import http.server
import io
import threading

import pytest

pytest.importorskip("markdown")
pytest.importorskip("weasyprint")
pypdf = pytest.importorskip("pypdf")
from PIL import Image

from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig


def _png(path, color, size=(12, 8)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _image_colors(pdf):
    return [
        image.image.convert("RGB").getpixel((0, 0))
        for page in pypdf.PdfReader(pdf).pages
        for image in page.images
    ]


@pytest.fixture
def canary():
    """A local HTTP server that records every request it receives."""
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            buffer = io.BytesIO()
            Image.new("RGB", (12, 8), "blue").save(buffer, format="PNG")
            self.wfile.write(buffer.getvalue())

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()


def test_only_files_inside_the_markdown_directory_are_embedded(tmp_path, canary):
    base, requests = canary
    outside = _png(tmp_path / "private" / "outside.png", "blue")
    secret = tmp_path / "private" / "secret.txt"
    secret.write_text("SECRET-ATTACHMENT-CONTENT", encoding="utf-8")
    source_dir = tmp_path / "docs"
    _png(source_dir / "figures" / "inside.png", "red")
    (source_dir / "link.png").symlink_to(outside)
    source = source_dir / "report.md"
    source.write_text(
        "# Report\n\n"
        "![inside](figures/inside.png)\n\n"
        "![parent](../private/outside.png)\n\n"
        f"![absolute]({outside.as_uri()})\n\n"
        "![symlink](link.png)\n\n"
        f"![remote]({base}/image.png)\n\n"
        f'<link rel="stylesheet" href="{base}/style.css">\n'
        f'<link rel="attachment" href="{secret.as_uri()}">\n'
        f'<link rel="attachment" href="{base}/attachment.txt">\n',
        encoding="utf-8",
    )
    output = tmp_path / "report.pdf"

    converter = EnhancedMarkdownConverter(
        MarkdownConfig(custom_css=f"body {{ background: url({base}/bg.png); }}")
    )
    assert converter.convert_file_to_pdf(str(source), str(output), "weasyprint")

    assert _image_colors(output) == [(255, 0, 0)]
    assert requests == []
    pdf = pypdf.PdfReader(output)
    assert not pdf.attachments
    assert b"SECRET-ATTACHMENT-CONTENT" not in output.read_bytes()


def test_data_uri_images_still_embed(tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), "green").save(buffer, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    source = tmp_path / "inline.md"
    source.write_text(f"![inline]({data_uri})\n", encoding="utf-8")
    output = tmp_path / "inline.pdf"

    converter = EnhancedMarkdownConverter()
    assert converter.convert_file_to_pdf(str(source), str(output), "weasyprint")

    assert _image_colors(output) == [(0, 128, 0)]


def test_markdown_string_without_a_source_file_loads_only_data_uris(
    tmp_path, monkeypatch, canary
):
    base, requests = canary
    local = _png(tmp_path / "local.png", "red")
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), "green").save(buffer, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "string.pdf"

    converter = EnhancedMarkdownConverter()
    assert converter.convert_markdown_to_pdf(
        f"![local]({local.as_uri()})\n\n![remote]({base}/x.png)\n\n"
        f"![inline]({data_uri})\n",
        str(output),
        "weasyprint",
    )

    assert _image_colors(output) == [(0, 128, 0)]
    assert requests == []


def test_configured_css_file_still_applies(tmp_path):
    styles = tmp_path / "styles"
    styles.mkdir()
    css_file = styles / "print.css"
    css_file.write_text(
        "@page { size: 100mm 50mm; margin: 5mm; }\n"
        "h1::before { content: url(banner.png); }\n",
        encoding="utf-8",
    )
    source_dir = tmp_path / "docs"
    # The CSS is inlined, so its relative url() resolves against the
    # Markdown file's directory.
    _png(source_dir / "banner.png", "red")
    source = source_dir / "styled.md"
    source.write_text("# Styled\n", encoding="utf-8")
    output = tmp_path / "styled.pdf"

    converter = EnhancedMarkdownConverter(MarkdownConfig(css_file=str(css_file)))
    assert converter.convert_file_to_pdf(str(source), str(output), "weasyprint")

    page = pypdf.PdfReader(output).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    assert width_mm == pytest.approx(100, abs=0.5)
    assert _image_colors(output) == [(255, 0, 0)]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/x.png",
        "ftp://127.0.0.1/x.png",
        "file:///etc/hosts",
        "file://otherhost/share/x.png",
        "javascript:alert(1)",
    ],
)
def test_fetcher_refuses_other_urls_before_any_io(tmp_path, url):
    from raganything.enhanced_markdown import _restricted_url_fetcher

    fetcher = _restricted_url_fetcher((tmp_path / "doc.md").as_uri())
    with pytest.raises(ValueError, match="Markdown file's directory"):
        fetcher(url)
