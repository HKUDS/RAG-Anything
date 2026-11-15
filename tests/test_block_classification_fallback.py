"""Unit tests for semantic block classification and markdown fallback (Issue #21).

Verifies that:
1. Blocks with alternative or unknown types ('paragraph', 'code', 'list', 'unknown')
   containing text are appropriately classified and extracted as text content.
2. Multimodal blocks ('image', 'table', 'equation') retain their dedicated routing.
3. Empty or payload-free unknown blocks do not pollute the multimodal pipeline.
4. Neighbor text extraction captures context from all text block variants.
5. Markdown files are located as fail-safe fallback when content_list produces zero text.
"""

from pathlib import Path
from unittest.mock import MagicMock

from raganything.processor import ProcessorMixin
from raganything.utils import (
    extract_block_text,
    extract_neighbor_text_from_content_list,
    is_multimodal_block,
    is_text_block,
    separate_content_with_page_map,
)


def test_is_multimodal_block_detection():
    # Explicit multimodal types
    assert is_multimodal_block({"type": "image", "img_path": "test.png"})
    assert is_multimodal_block({"type": "table", "table_body": "| a | b |"})
    assert is_multimodal_block({"type": "equation", "equation": "E = mc^2"})
    assert is_multimodal_block({"type": "audio", "audio_path": "test.mp3"})
    assert is_multimodal_block({"type": "video", "video_path": "test.mp4"})

    # Blocks with modal payload keys even if type is generic or missing
    assert is_multimodal_block({"type": "custom", "img_path": "pic.jpg"})
    assert is_multimodal_block({"type": "figure", "image_path": "pic.jpg"})
    assert is_multimodal_block({"type": "tabular", "table_body": "data"})
    assert is_multimodal_block({"latex": "\\sum x_i"})

    assert is_multimodal_block({"type": "code", "code_body": "print(1)"})

    # Pure text blocks should NOT be identified as multimodal
    assert not is_multimodal_block({"type": "text", "text": "hello"})
    assert not is_multimodal_block({"type": "paragraph", "text": "lorem ipsum"})
    assert not is_multimodal_block({"type": "unknown", "text": "unknown text"})
    assert not is_multimodal_block({"type": "blockquote", "content": "quote"})
    assert not is_multimodal_block({})


def test_is_text_block_and_text_extraction():
    # Standard text
    item1 = {"type": "text", "text": "Standard text"}
    assert is_text_block(item1)
    assert extract_block_text(item1) == "Standard text"

    # Paragraph and quote blocks
    item2 = {"type": "paragraph", "text": "Paragraph content"}
    assert is_text_block(item2)
    assert extract_block_text(item2) == "Paragraph content"

    item3 = {"type": "blockquote", "content": "Expert testimony"}
    assert is_text_block(item3)
    assert extract_block_text(item3) == "Expert testimony"

    # Unknown type with text payload (reproduces Issue #21)
    item4 = {"type": "unknown", "text": "Space orbit mechanics text"}
    assert is_text_block(item4)
    assert extract_block_text(item4) == "Space orbit mechanics text"

    # Multimodal items are not text blocks even if they contain caption/text fields
    item5 = {"type": "image", "img_path": "chart.png", "text": "Figure 1"}
    assert not is_text_block(item5)

    # Empty block
    assert not is_text_block({"type": "unknown"})
    assert extract_block_text({"type": "unknown"}) == ""


def test_separate_content_with_unknown_blocks_reproduction_issue_21():
    """Reproduces the exact scenario of Issue #21 where all 22 blocks are 'unknown'."""
    raw_blocks = [
        {
            "type": "unknown",
            "text": f"Chapter {i}: Dynamics of special space orbits and trajectory analysis.",
            "page_idx": (i // 5) + 1,
        }
        for i in range(22)
    ]

    text_content, multimodal_items, page_intervals = separate_content_with_page_map(
        raw_blocks
    )

    # Text content must NOT be 0 characters
    assert len(text_content) > 0
    assert "Chapter 0: Dynamics" in text_content
    assert "Chapter 21: Dynamics" in text_content
    assert len(page_intervals) == 22
    assert page_intervals[0][2] == 1

    # Multimodal items must not contain the text blocks
    assert len(multimodal_items) == 0


def test_separate_content_mixed_blocks():
    blocks = [
        {"type": "title", "text": "Research Report", "page_idx": 0},
        {"type": "paragraph", "text": "Introduction section text.", "page_idx": 0},
        {"type": "image", "img_path": "/tmp/plot.png", "page_idx": 0},
        {"type": "aside", "content": "Side note commentary.", "page_idx": 1},
        {
            "type": "table",
            "table_body": "| Metric | Value |\n|---|---|\n| Accuracy | 98% |",
            "page_idx": 1,
        },
        {"type": "footnote", "text": "Source: Lab measurement.", "page_idx": 1},
    ]

    text_content, multimodal_items, page_intervals = separate_content_with_page_map(
        blocks
    )

    # Text content includes title, paragraph, aside, and footnote
    assert "Research Report" in text_content
    assert "Introduction section text." in text_content
    assert "Side note commentary." in text_content
    assert "Source: Lab measurement." in text_content
    assert len(page_intervals) == 4

    # Multimodal items only contain image and table
    assert len(multimodal_items) == 2
    types = [item.get("type") for item in multimodal_items]
    assert "image" in types
    assert "table" in types


def test_neighbor_text_extraction_across_block_types():
    content_list = [
        {"type": "heading", "text": "Experiment Results"},
        {"type": "paragraph", "text": "The test was executed at 300K temperature."},
        {"type": "image", "img_path": "fig1.png"},
        {"type": "unknown", "text": "Figure 1 illustrates the phase transition."},
    ]

    neighbor_text = extract_neighbor_text_from_content_list(
        content_list, current_index=2, window_size=2
    )

    assert "Experiment Results" in neighbor_text
    assert "The test was executed at 300K temperature." in neighbor_text
    assert "Figure 1 illustrates the phase transition." in neighbor_text


def test_processor_find_fallback_markdown_text(tmp_path: Path):
    class DummyProcessor(ProcessorMixin):
        def __init__(self, out_dir: Path):
            self.logger = MagicMock()
            self._out_dir = out_dir

        def _compute_parsed_output_dirs(self, file_path, output_dir=None):
            return self._out_dir, [self._out_dir]

    proc = DummyProcessor(tmp_path)
    file_path = tmp_path / "paper.pdf"
    file_path.touch()

    # When no markdown file exists, returns None
    assert proc._find_fallback_markdown_text(file_path, tmp_path) is None

    # When markdown file exists, returns content
    md_file = tmp_path / "paper.md"
    md_file.write_text("# Title\n\nFull document markdown text.", encoding="utf-8")

    fallback_text = proc._find_fallback_markdown_text(file_path, tmp_path)
    assert fallback_text is not None
    assert "# Title" in fallback_text
    assert "Full document markdown text." in fallback_text
