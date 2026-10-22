"""File conversion resolves relative images from the Markdown document."""

from pathlib import Path

import pytest

pytest.importorskip("markdown")
pytest.importorskip("weasyprint")
pypdf = pytest.importorskip("pypdf")
from PIL import Image

from raganything.enhanced_markdown import EnhancedMarkdownConverter


@pytest.mark.parametrize("relative_input", [False, True])
@pytest.mark.parametrize("image_reference", ["chart.png", "images/chart%20one.png"])
def test_file_conversion_loads_relative_image(
    tmp_path, monkeypatch, relative_input, image_reference
):
    source_dir = tmp_path / "source documents"
    source_dir.mkdir()
    image_path = source_dir / (
        "images/chart one.png" if image_reference.startswith("images/") else "chart.png"
    )
    image_path.parent.mkdir(exist_ok=True)
    Image.new("RGB", (12, 8), "red").save(image_path)
    source = source_dir / "document.md"
    source.write_text(f"# Chart\n\n![chart]({image_reference})\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output = output_dir / "document.pdf"
    monkeypatch.chdir(tmp_path)
    input_path = source.relative_to(tmp_path) if relative_input else source
    converter = EnhancedMarkdownConverter()
    assert converter.convert_file_to_pdf(str(input_path), str(output), "weasyprint")
    assert output.read_bytes().startswith(b"%PDF-")
    images = list(pypdf.PdfReader(output).pages[0].images)
    assert len(images) == 1
    assert images[0].image.size == (12, 8)
    assert images[0].image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    assert Path.cwd() == tmp_path
