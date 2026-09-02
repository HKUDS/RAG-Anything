"""Tests for direct plain-text parsing (issue #331).

.txt/.md files are parsed straight into content blocks instead of being
rendered to PDF with ReportLab and re-parsed with the OCR pipeline.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.parser import MineruParser, PaddleOCRParser, Parser  # noqa: E402


class TestTextToContentBlocks:
    """The block builder: paragraph splitting, headings, line endings."""

    def test_paragraphs_split_on_blank_lines(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("First paragraph.\n\nSecond paragraph\nwith a wrapped line.\n")
        blocks = MineruParser().parse_text_file(f)
        assert [b["text"] for b in blocks] == [
            "First paragraph.",
            "Second paragraph\nwith a wrapped line.",
        ]
        assert all(b["type"] == "text" for b in blocks)

    def test_crlf_line_endings_still_split_paragraphs(self, tmp_path):
        # File path: text-mode open translates newlines, so this documents
        # the end-to-end behavior rather than the normalization itself.
        f = tmp_path / "doc.txt"
        f.write_bytes(b"First paragraph.\r\n\r\nSecond paragraph.\r\n")
        blocks = MineruParser().parse_text_file(f)
        assert [b["text"] for b in blocks] == ["First paragraph.", "Second paragraph."]

    def test_block_builder_accepts_raw_crlf_strings(self):
        # Direct string input skips text-mode newline translation; CRLF
        # paragraph breaks must still split, and no \r may leak into blocks.
        blocks = Parser._text_to_content_blocks("A.\r\n\r\nB.", is_markdown=False)
        assert [b["text"] for b in blocks] == ["A.", "B."]

    def test_all_blocks_carry_page_idx_zero(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("One.\n\nTwo.\n\nThree.\n")
        blocks = MineruParser().parse_text_file(f)
        assert len(blocks) == 3
        assert all(b["page_idx"] == 0 for b in blocks)

    def test_markdown_headings_get_text_level(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Title\n\nBody paragraph.\n\n## Section\nSection body.\n")
        blocks = MineruParser().parse_text_file(f)
        assert blocks[0] == {
            "type": "text",
            "text": "Title",
            "text_level": 1,
            "page_idx": 0,
        }
        assert "text_level" not in blocks[1]
        assert blocks[2]["text_level"] == 2
        # A heading directly followed by text (no blank line) still becomes
        # its own block, with the text as a separate paragraph.
        assert blocks[3]["text"] == "Section body."

    def test_txt_does_not_interpret_hash_as_heading(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("# not a heading in plain text\n")
        blocks = MineruParser().parse_text_file(f)
        assert blocks[0]["text"] == "# not a heading in plain text"
        assert "text_level" not in blocks[0]

    def test_empty_file_yields_no_blocks(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("\n\n  \n")
        assert MineruParser().parse_text_file(f) == []


class TestEncodingHandling:
    def test_gbk_fallback(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_bytes("涡轮叶片检测报告。".encode("gbk"))
        blocks = MineruParser().parse_text_file(f)
        assert blocks[0]["text"] == "涡轮叶片检测报告。"

    def test_utf8_bom_is_stripped(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_bytes("﻿First paragraph.".encode("utf-8"))
        blocks = MineruParser().parse_text_file(f)
        assert blocks[0]["text"] == "First paragraph."


class TestNoPdfRoundTrip:
    """The point of the change: text formats must never touch the PDF path."""

    @pytest.mark.parametrize("parser_cls", [MineruParser, PaddleOCRParser])
    def test_parse_document_routes_text_without_pdf_conversion(
        self, tmp_path, monkeypatch, parser_cls
    ):
        f = tmp_path / "doc.txt"
        f.write_text("Direct content.\n")

        def fail(*args, **kwargs):
            raise AssertionError("text parsing must not render a PDF")

        monkeypatch.setattr(Parser, "convert_text_to_pdf", classmethod(fail))
        monkeypatch.setattr(parser_cls, "parse_pdf", fail, raising=False)

        blocks = parser_cls().parse_document(f)
        assert blocks == [{"type": "text", "text": "Direct content.", "page_idx": 0}]

    def test_rejects_non_text_extension(self, tmp_path):
        f = tmp_path / "doc.csv"
        f.write_text("a,b\n")
        with pytest.raises(ValueError):
            MineruParser().parse_text_file(f)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MineruParser().parse_text_file(tmp_path / "absent.txt")
