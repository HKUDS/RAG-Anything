"""Tests for multi-page table continuation merging (Issues #424 & #100)."""

from raganything.config import RAGAnythingConfig
from raganything.utils import merge_continued_tables


class TestMergeContinuedTables:
    """Unit tests for merge_continued_tables helper in raganything.utils."""

    def test_empty_or_single_table_untouched(self):
        assert merge_continued_tables([]) == []
        single = [
            {
                "type": "table",
                "table_body": "| a | b |\n|---|---|\n| 1 | 2 |",
                "page_idx": 0,
            }
        ]
        assert merge_continued_tables(single) == single

    def test_merge_two_page_markdown_table_with_repeated_header(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| Column A | Column B |\n| --- | --- |\n| row 1 A | row 1 B |",
                "table_caption": ["Financial Summary"],
                "table_footnote": ["In thousands USD"],
                "page_idx": 0,
            },
            {
                "type": "table",
                "table_body": "| Column A | Column B |\n| --- | --- |\n| row 2 A | row 2 B |",
                "table_caption": ["Financial Summary (continued)"],
                "page_idx": 1,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 1
        table = merged[0]
        assert table["page_idx"] == 0
        assert table["page_idx_end"] == 1
        assert table["table_caption"] == ["Financial Summary"]
        assert table["table_footnote"] == ["In thousands USD"]
        assert "row 1 A" in table["table_body"]
        assert "row 2 A" in table["table_body"]
        # Repeated header in second part should be deduplicated
        assert table["table_body"].count("Column A") == 1

    def test_merge_across_ignorable_continuation_text(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| Header 1 | Header 2 |\n| --- | --- |\n| Data 1 | Data 2 |",
                "table_caption": ["Sales Data"],
                "page_idx": 2,
            },
            {
                "type": "text",
                "text": "Table 1 (continued)",
                "page_idx": 3,
            },
            {
                "type": "table",
                "table_body": "| Header 1 | Header 2 |\n| --- | --- |\n| Data 3 | Data 4 |",
                "table_caption": ["续表"],
                "page_idx": 3,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 1
        table = merged[0]
        assert table["page_idx"] == 2
        assert table["page_idx_end"] == 3
        assert "Data 1" in table["table_body"]
        assert "Data 3" in table["table_body"]

    def test_substantive_text_between_tables_prevents_merge(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| H1 | H2 |\n|---|---|\n| 1 | 2 |",
                "page_idx": 1,
            },
            {
                "type": "text",
                "text": "Section 2.3 discusses the overall methodology and performance evaluation.",
                "page_idx": 2,
            },
            {
                "type": "table",
                "table_body": "| H1 | H2 |\n|---|---|\n| 3 | 4 |",
                "page_idx": 2,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 3
        assert merged[0]["type"] == "table"
        assert merged[1]["type"] == "text"
        assert merged[2]["type"] == "table"

    def test_different_column_counts_prevent_merge(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| Col1 | Col2 |\n|---|---|\n| 1 | 2 |",
                "page_idx": 0,
            },
            {
                "type": "table",
                "table_body": "| Col1 | Col2 | Col3 |\n|---|---|---|\n| 1 | 2 | 3 |",
                "page_idx": 1,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 2

    def test_non_consecutive_pages_prevent_merge(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| Col1 | Col2 |\n|---|---|\n| 1 | 2 |",
                "page_idx": 1,
            },
            {
                "type": "table",
                "table_body": "| Col1 | Col2 |\n|---|---|\n| 3 | 4 |",
                "page_idx": 5,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 2

    def test_conflicting_caption_prevents_merge(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| Col1 | Col2 |\n|---|---|\n| 1 | 2 |",
                "table_caption": ["Table 1: Training Parameters"],
                "page_idx": 1,
            },
            {
                "type": "table",
                "table_body": "| Col1 | Col2 |\n|---|---|\n| 3 | 4 |",
                "table_caption": ["Table 2: Benchmark Results"],
                "page_idx": 2,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 2

    def test_three_page_table_stitching(self):
        content_list = [
            {
                "type": "table",
                "table_body": "| Item | Price |\n| --- | --- |\n| A | 10 |",
                "page_idx": 1,
            },
            {
                "type": "table",
                "table_body": "| Item | Price |\n| --- | --- |\n| B | 20 |",
                "page_idx": 2,
            },
            {
                "type": "table",
                "table_body": "| Item | Price |\n| --- | --- |\n| C | 30 |",
                "page_idx": 3,
            },
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 1
        assert merged[0]["page_idx"] == 1
        assert merged[0]["page_idx_end"] == 3
        for item in ("A | 10", "B | 20", "C | 30"):
            assert item in merged[0]["table_body"]
        assert merged[0]["table_body"].count("Item | Price") == 1

    def test_html_table_merging(self):
        table_html_1 = "<table><tbody><tr><th>Name</th><th>Score</th></tr><tr><td>Alice</td><td>90</td></tr></tbody></table>"
        table_html_2 = "<table><tbody><tr><th>Name</th><th>Score</th></tr><tr><td>Bob</td><td>95</td></tr></tbody></table>"

        content_list = [
            {"type": "table", "table_body": table_html_1, "page_idx": 4},
            {"type": "table", "table_body": table_html_2, "page_idx": 5},
        ]

        merged = merge_continued_tables(content_list)
        assert len(merged) == 1
        assert merged[0]["page_idx"] == 4
        assert merged[0]["page_idx_end"] == 5
        body = merged[0]["table_body"]
        assert "Alice" in body
        assert "Bob" in body
        # Repeated header in second part should be stripped
        assert body.count("<th>Name</th>") == 1


class TestConfigMergeContinuedTables:
    """Test configuration field for merge_continued_tables."""

    def test_default_is_false(self):
        cfg = RAGAnythingConfig()
        assert cfg.merge_continued_tables is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MERGE_CONTINUED_TABLES", "true")
        cfg = RAGAnythingConfig()
        assert cfg.merge_continued_tables is True
