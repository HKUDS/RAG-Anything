"""Docling items without content must not become content blocks.

Docling's HTML backend does not fetch ``<img>`` sources, so those pictures
carry no image data (their alt text and captions are separate text items),
and an empty document exports a body without children. Neither may reach
LightRAG as placeholder text or as an invented empty table. Real tables reach
it as rows of cell text, with the captions and footnotes Docling links by
reference. The documents below follow the shape Docling 2.x exports.
"""

import base64
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from raganything.parser import DoclingParser
from raganything.processor import ProcessorMixin
from raganything.utils import format_table_body

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC"
)


def _text(label, orig, parent="#/body", children=()):
    return {
        "label": label,
        "orig": orig,
        "text": orig,
        "parent": {"$ref": parent},
        "children": [{"$ref": ref} for ref in children],
    }


def _picture(parent, captions=(), children=(), uri=None):
    picture = {
        "label": "picture",
        "parent": {"$ref": parent},
        "children": [{"$ref": ref} for ref in children],
        "captions": [{"$ref": ref} for ref in captions],
        "footnotes": [],
    }
    if uri is not None:
        picture["image"] = {"mimetype": "image/png", "uri": uri}
    return picture


def _cell(row, col, text, col_span=1):
    # Every cell carries its bounding box, offsets and header flags.
    return {
        "bbox": {
            "l": 72.0 + 80.0 * col,
            "t": 140.0 + 15.0 * row,
            "r": 72.0 + 80.0 * (col + col_span),
            "b": 155.0 + 15.0 * row,
            "coord_origin": "TOPLEFT",
        },
        "row_span": 1,
        "col_span": col_span,
        "start_row_offset_idx": row,
        "end_row_offset_idx": row + 1,
        "start_col_offset_idx": col,
        "end_col_offset_idx": col + col_span,
        "text": text,
        "column_header": row == 0,
        "row_header": False,
        "row_section": False,
        "fillable": False,
    }


def _table_data(rows):
    # Docling exports each cell twice: in table_cells and in the computed grid.
    grid = [
        [_cell(r, c, text) for c, text in enumerate(row)] for r, row in enumerate(rows)
    ]
    return {
        "table_cells": [cell for row in grid for cell in row],
        "num_rows": len(rows),
        "num_cols": len(rows[0]),
        "grid": grid,
    }


def _document(body_children, **items):
    return {
        "body": {"self_ref": "#/body", "children": body_children},
        "groups": [],
        "texts": [],
        "pictures": [],
        "tables": [],
        **items,
    }


def _parser_returning(monkeypatch, document):
    exported = SimpleNamespace(
        export_to_dict=lambda: document, export_to_markdown=lambda: ""
    )
    converter = SimpleNamespace(convert=lambda _: SimpleNamespace(document=exported))
    parser = DoclingParser()
    monkeypatch.setattr(parser, "_get_converter", lambda **kwargs: converter)
    return parser


def _parse_html(tmp_path, monkeypatch, document):
    page = tmp_path / "page.html"
    page.write_text("<html></html>", encoding="utf-8")
    parser = _parser_returning(monkeypatch, document)
    return parser.parse_html(page, output_dir=str(tmp_path / "output"))


def test_html_pictures_without_image_data_are_skipped(tmp_path, monkeypatch):
    # <h1>, <p>, <img alt=...>, <figure><img><figcaption>, <img>, <p>
    document = _document(
        [{"$ref": f"#/texts/{i}"} for i in (0, 1, 3, 4)],
        texts=[
            _text("title", "Q"),
            _text(
                "title",
                "Quarterly report",
                children=[
                    "#/texts/2",
                    "#/pictures/0",
                    "#/pictures/1",
                    "#/pictures/2",
                    "#/texts/5",
                ],
            ),
            _text("text", "Revenue grew in Q3.", parent="#/texts/1"),
            _text("caption", "Revenue chart for Q3"),
            _text("caption", "Inline data URI figure"),
            _text("text", "Closing paragraph.", parent="#/texts/1"),
        ],
        pictures=[
            _picture("#/texts/1", captions=["#/texts/3"]),
            _picture("#/texts/1", captions=["#/texts/4"]),
            _picture("#/texts/1"),
        ],
    )

    items = _parse_html(tmp_path, monkeypatch, document)

    assert items == [
        {"type": "text", "text": text, "page_idx": 0}
        for text in (
            "Q",
            "Quarterly report",
            "Revenue grew in Q3.",
            "Closing paragraph.",
            "Revenue chart for Q3",
            "Inline data URI figure",
        )
    ]


def test_html_document_of_only_imageless_pictures_has_no_content(tmp_path, monkeypatch):
    document = _document([{"$ref": "#/pictures/0"}], pictures=[_picture("#/body")])

    assert _parse_html(tmp_path, monkeypatch, document) == []


def test_picture_with_image_data_becomes_image_block_with_captions(
    tmp_path, monkeypatch
):
    # PDF shape: the caption is the picture's child and linked as its caption.
    document = _document(
        [{"$ref": "#/texts/0"}, {"$ref": "#/pictures/0"}],
        texts=[
            _text("text", "Revenue grew in Q3."),
            _text("caption", "Figure 1: Revenue", parent="#/pictures/0"),
        ],
        pictures=[
            _picture(
                "#/body",
                captions=["#/texts/1"],
                children=["#/texts/1"],
                uri=f"data:image/png;base64,{PNG_BASE64}",
            )
        ],
    )
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    parser = _parser_returning(monkeypatch, document)

    items = parser.parse_pdf(source, output_dir=str(tmp_path / "output"))

    assert [item["type"] for item in items] == ["text", "image", "text"]
    image = items[1]
    assert Path(image["img_path"]).read_bytes() == base64.b64decode(PNG_BASE64)
    assert image["image_caption"] == ["Figure 1: Revenue"]
    assert image["image_footnote"] == []
    assert items[2]["text"] == "Figure 1: Revenue"


def test_undecodable_picture_is_skipped_not_replaced_by_placeholder(tmp_path):
    block = {"image": {"uri": "data:image/png;base64,abc"}, "captions": []}

    assert DoclingParser().read_from_block(block, "pictures", tmp_path, 1, "0") is None


@pytest.mark.parametrize(
    "document",
    [
        # Empty file, whitespace-only <body>, or an empty .docx.
        _document([]),
        # <html><head><title></title></head><body></body></html>
        _document([{"$ref": "#/texts/0"}], texts=[_text("title", "")]),
        _document([{"$ref": "#/texts/0"}], texts=[_text("text", " \n\t")]),
        # An empty list or other group.
        _document(
            [{"$ref": "#/groups/0"}],
            groups=[{"label": "list", "children": [], "parent": {"$ref": "#/body"}}],
        ),
    ],
    ids=["no-children", "empty-title", "whitespace-text", "empty-group"],
)
def test_empty_documents_yield_no_content_blocks(tmp_path, monkeypatch, document):
    assert _parse_html(tmp_path, monkeypatch, document) == []


def test_real_tables_are_still_emitted(tmp_path, monkeypatch):
    table_data = {"table_cells": [{"text": "Revenue"}], "num_rows": 1, "num_cols": 1}
    document = _document(
        [{"$ref": "#/tables/0"}],
        tables=[{"label": "table", "children": [], "data": table_data}],
    )

    items = _parse_html(tmp_path, monkeypatch, document)

    assert [item["type"] for item in items] == ["table"]
    assert items[0]["table_body"] == table_data


def test_table_chunk_has_rows_caption_and_footnote(tmp_path, monkeypatch):
    # PDF shape: the caption and footnote are the table's children, linked as
    # its captions and footnotes. There is no caption or footnote key.
    table_data = _table_data([["Region", "Q1 revenue"], ["North", "1,200"]])
    document = _document(
        [{"$ref": "#/tables/0"}],
        texts=[
            _text("caption", "Table 1: Revenue by region", parent="#/tables/0"),
            _text("footnote", "Figures in USD thousands", parent="#/tables/0"),
        ],
        tables=[
            {
                "label": "table",
                "parent": {"$ref": "#/body"},
                "children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}],
                "captions": [{"$ref": "#/texts/0"}],
                "footnotes": [{"$ref": "#/texts/1"}],
                "data": table_data,
            }
        ],
    )
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    parser = _parser_returning(monkeypatch, document)

    table = parser.parse_pdf(source, output_dir=str(tmp_path / "output"))[0]
    chunk = _Processor()._apply_chunk_template("table", table, "Revenue by region.")

    assert table["table_caption"] == ["Table 1: Revenue by region"]
    assert table["table_footnote"] == ["Figures in USD thousands"]
    # The content list keeps Docling's data: document IDs are hashed from it.
    assert table["table_body"] == table_data
    assert "Caption: Table 1: Revenue by region\n" in chunk
    assert (
        "Structure: | Region | Q1 revenue |\n| --- | --- |\n| North | 1,200 |\n"
        in chunk
    )
    assert "Footnotes: Figures in USD thousands\n" in chunk
    assert "bbox" not in chunk


def test_table_data_is_rendered_from_its_grid():
    # The grid repeats a spanning cell in every position it covers.
    region = _cell(0, 0, "Region")
    revenue = _cell(0, 1, "Revenue", col_span=2)
    rows = [_cell(1, 0, "North"), _cell(1, 1, "1,200"), _cell(1, 2, "1,350")]
    table_data = {
        "table_cells": [region, revenue, *rows],
        "num_rows": 2,
        "num_cols": 3,
        "grid": [[region, revenue, revenue], rows],
    }

    assert format_table_body(table_data) == (
        "| Region | Revenue | Revenue |\n"
        "| --- | --- | --- |\n"
        "| North | 1,200 | 1,350 |"
    )


class _Processor(ProcessorMixin):
    pass


class _MemoryCache:
    def __init__(self):
        self.entries = {}

    async def get_by_id(self, key):
        return self.entries.get(key)

    async def upsert(self, entries):
        self.entries.update(entries)

    async def index_done_callback(self):
        pass


@pytest.mark.asyncio
async def test_empty_html_reports_that_no_content_was_extracted(tmp_path, monkeypatch):
    page = tmp_path / "empty.html"
    page.write_text("<html><body></body></html>", encoding="utf-8")
    processor = _Processor()
    processor.config = SimpleNamespace(
        parser="docling",
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
    )
    processor.logger = logging.getLogger(__name__)
    processor.parse_cache = _MemoryCache()
    processor.doc_parser = _parser_returning(monkeypatch, _document([]))

    with pytest.raises(ValueError, match="No content was extracted"):
        await processor.parse_document(str(page))
    assert processor.parse_cache.entries == {}
