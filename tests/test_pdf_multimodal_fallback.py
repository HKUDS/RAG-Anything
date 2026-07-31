import io
from pathlib import Path

import pypdf
import pytest
from PIL import Image

from raganything.utils._image import image_mime_type
from raganything.utils.pdf_fallback import extract_pdf_embedded_images


def test_extract_pdf_embedded_images_creates_parser_compatible_items(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-fallback-fixture")
    jpeg_buffer = io.BytesIO()
    Image.new("RGB", (20, 10), "red").save(jpeg_buffer, format="JPEG")

    class FakeImage:
        # pypdf display names are not reliable, so use an intentionally wrong
        # suffix and assert the fallback uses the decoded bytes instead.
        name = "embedded.png"
        data = jpeg_buffer.getvalue()

    class FakePage:
        images = {"/Im1": FakeImage()}

    class FakeReader:
        pages = [FakePage()]

        def __init__(self, _path):
            pass

    monkeypatch.setattr(pypdf, "PdfReader", FakeReader)

    items = extract_pdf_embedded_images(source, tmp_path / "output")

    assert len(items) == 1
    assert items[0]["type"] == "image"
    assert items[0]["page_idx"] == 0
    assert items[0]["source"] == "pdf_embedded_image_fallback"
    artifact = Path(items[0]["img_path"])
    assert artifact.suffix == ".jpg"
    assert image_mime_type(artifact) == "image/jpeg"
    with Image.open(artifact) as extracted:
        assert extracted.format == "JPEG"


def test_extract_pdf_embedded_images_respects_limit(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-fallback-fixture")

    class FakeImage:
        def __init__(self, name):
            self.name = name
            buffer = io.BytesIO()
            Image.new("RGB", (10, 10), "blue").save(buffer, format="PNG")
            self.data = buffer.getvalue()

    class FakePage:
        images = {"/Im1": FakeImage("one.png"), "/Im2": FakeImage("two.png")}

    class FakeReader:
        pages = [FakePage()]

        def __init__(self, _path):
            pass

    monkeypatch.setattr(pypdf, "PdfReader", FakeReader)

    items = extract_pdf_embedded_images(source, tmp_path / "output", max_images=1)

    assert [Path(item["img_path"]).name for item in items] == ["page_0001_image_001.png"]


def test_extract_pdf_embedded_images_normalizes_jpeg2000_named_as_png(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-fallback-fixture")
    jp2_buffer = io.BytesIO()
    try:
        Image.new("RGB", (20, 10), "green").save(jp2_buffer, format="JPEG2000")
    except OSError:
        pytest.skip("Pillow JPEG2000 encoder is unavailable")

    class FakeImage:
        name = "misleading.png"
        data = jp2_buffer.getvalue()

        def __init__(self):
            self._buffer = io.BytesIO(self.data)
            self.image = Image.open(self._buffer)
            self.image.load()

    class FakePage:
        images = {"/Im1": FakeImage()}

    class FakeReader:
        pages = [FakePage()]

        def __init__(self, _path):
            pass

    monkeypatch.setattr(pypdf, "PdfReader", FakeReader)

    items = extract_pdf_embedded_images(source, tmp_path / "output")

    assert len(items) == 1
    artifact = Path(items[0]["img_path"])
    assert artifact.suffix == ".png"
    assert artifact.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(artifact) as extracted:
        assert extracted.format == "PNG"
