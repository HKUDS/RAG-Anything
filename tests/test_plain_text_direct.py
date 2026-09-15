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


class TestMarkdownCodeFences:
    @pytest.mark.parametrize(
        "opening,non_closing",
        [
            ("````", "```"),
            ("~~~~", "~~~"),
            ("```", "```python"),
            ("~~~", "~~~python"),
            ("```", "~~~"),
            ("~~~", "```"),
        ],
    )
    def test_non_closing_fence_keeps_headings_and_images_literal(
        self, tmp_path, opening, non_closing
    ):
        # Image resolution checks existence; no image decoding is needed here.
        image = tmp_path / "diagram.png"
        image.touch()
        code = (
            f"{opening}markdown\n{non_closing}\n"
            f"# Example heading\n\n![Example](diagram.png)\n{opening}"
        )
        f = tmp_path / "doc.md"
        f.write_text(f"{code}\n\n# Real heading\n\n![Real](diagram.png)\n")

        blocks = MineruParser().parse_text_file(f)

        assert blocks == [
            {"type": "text", "text": code, "page_idx": 0},
            {"type": "text", "text": "Real heading", "text_level": 1, "page_idx": 0},
            {
                "type": "image",
                "img_path": str(image.resolve()),
                "img_caption": ["Real"],
                "img_footnote": [],
                "page_idx": 0,
            },
        ]

    @pytest.mark.parametrize("marker", ["`", "~"])
    def test_longer_closing_fence_with_whitespace_is_accepted(self, marker):
        code = f"{marker * 4}markdown\n# Literal\n  {marker * 5}"
        blocks = Parser._text_to_content_blocks(
            f"{code} \t\n# Heading", is_markdown=True
        )
        assert blocks == [
            {"type": "text", "text": code, "page_idx": 0},
            {"type": "text", "text": "Heading", "text_level": 1, "page_idx": 0},
        ]

    @pytest.mark.parametrize("marker", ["`", "~"])
    def test_shorter_fence_does_not_close_unterminated_block(self, marker):
        code = f"{marker * 4}markdown\n{marker * 3}\n# Still literal"
        assert Parser._text_to_content_blocks(code, is_markdown=True) == [
            {"type": "text", "text": code, "page_idx": 0}
        ]


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


class TestMarkdownImageTargets:
    @pytest.mark.parametrize(
        "filename,target",
        [
            ("figure 1.png", "figure%201.png"),
            ("图表.png", "%E5%9B%BE%E8%A1%A8.png"),
            ("100%.png", "100%25.png"),
            ("figure#1.png", "figure%231.png"),
            ("figure%20literal.png", "figure%2520literal.png"),
            ("a%2Bb.png", "a%2Bb.png"),
            ("figure%20literal.png", "figure%20literal.png"),
            ("plot+1.png", "plot+1.png"),
            ("plain.png", "plain.png"),
            ("figure 1.png", "<figure%201.png>"),
        ],
    )
    def test_local_image_targets_resolve_to_file(self, tmp_path, filename, target):
        image = tmp_path / filename
        image.touch()
        document = tmp_path / "doc.md"
        document.write_text(f'![Figure]({target} "Figure%20title")\n', encoding="utf-8")

        assert MineruParser().parse_text_file(document) == [
            {
                "type": "image",
                "img_path": str(image.resolve()),
                "img_caption": ["Figure", "Figure%20title"],
                "img_footnote": [],
                "page_idx": 0,
            }
        ]

    def test_absolute_encoded_image_target_is_not_joined_to_source_dir(self, tmp_path):
        image = tmp_path / "figure 1.png"
        image.touch()
        source_dir = tmp_path / "docs"
        source_dir.mkdir()
        document = source_dir / "doc.md"
        target = image.as_posix().replace(" ", "%20")
        document.write_text(f"![Figure]({target})", encoding="utf-8")

        blocks = MineruParser().parse_text_file(document)

        assert blocks[0]["type"] == "image"
        assert blocks[0]["img_path"] == str(image.resolve())

    @pytest.mark.parametrize(
        "target", ["missing%20image.png", "https://example.com/figure%201.png"]
    )
    def test_unresolved_image_targets_remain_literal(self, tmp_path, target):
        text = f"![Figure]({target})"
        document = tmp_path / "doc.md"
        document.write_text(text, encoding="utf-8")

        assert MineruParser().parse_text_file(document) == [
            {"type": "text", "text": text, "page_idx": 0}
        ]
