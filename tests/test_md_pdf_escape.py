"""Markdown text-to-PDF must escape ReportLab markup like the .txt path does."""

import pytest

from test_parser_url_download import Parser


pytest.importorskip("reportlab")


def test_convert_text_to_pdf_escapes_angle_brackets_in_markdown(tmp_path):
    md_path = tmp_path / "cmp.md"
    md_path.write_text(
        "Use filter when score <threshold.\n\n# Tom & Jerry\n",
        encoding="utf-8",
    )

    pdf_path = Parser.convert_text_to_pdf(md_path, output_dir=str(tmp_path / "out"))

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 100


def test_convert_text_to_pdf_plain_text_still_escapes(tmp_path):
    txt_path = tmp_path / "cmp.txt"
    txt_path.write_text("Use filter when score <threshold.\n", encoding="utf-8")

    pdf_path = Parser.convert_text_to_pdf(txt_path, output_dir=str(tmp_path / "out2"))

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 100


def test_process_inline_markdown_escapes_bare_angle_bracket():
    assert "&lt;threshold" in Parser._process_inline_markdown("score <threshold")


def test_process_inline_markdown_escapes_quotes_in_link_href():
    out = Parser._process_inline_markdown('see [x](http://ex.com/a"b) here')
    assert 'href="http://ex.com/a&quot;b"' in out
