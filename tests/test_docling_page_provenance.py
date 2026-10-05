"""Docling's source page numbers must survive content-list conversion."""

import base64
from types import SimpleNamespace

import pytest

from raganything.parser import DoclingParser


@pytest.mark.parametrize(
    "block_type,block,expected_type",
    [
        ("texts", {"label": "text", "orig": "A paragraph"}, "text"),
        ("texts", {"label": "formula", "orig": "x = 1"}, "equation"),
        (
            "pictures",
            {
                "image": {
                    "uri": "data:image/png;base64,"
                    + base64.b64encode(b"image").decode()
                }
            },
            "image",
        ),
        ("pictures", {}, "text"),  # failed image conversion retains provenance
        ("tables", {"data": {"table_cells": []}}, "table"),
    ],
)
@pytest.mark.parametrize("page_no", [1, 7])
def test_content_blocks_use_source_page(
    tmp_path, block_type, block, expected_type, page_no
):
    block = {**block, "prov": [{"page_no": page_no}]}

    item = DoclingParser().read_from_block(block, block_type, tmp_path, 99, "0")

    assert item["type"] == expected_type
    assert item["page_idx"] == page_no - 1


@pytest.mark.parametrize("provenance", [None, [], [{"page_no": 0}], [{"page_no": -1}]])
def test_missing_source_page_does_not_invent_pages_from_block_count(
    tmp_path, provenance
):
    block = {"label": "text", "orig": "Unpaginated document", "prov": provenance}

    item = DoclingParser().read_from_block(block, "texts", tmp_path, 99, "0")

    assert item["page_idx"] == 0


def test_multipage_block_uses_first_source_page(tmp_path):
    block = {"data": {}, "prov": [{"page_no": 4}, {"page_no": 5}]}

    item = DoclingParser().read_from_block(block, "tables", tmp_path, 2, "0")

    assert item["page_idx"] == 3


def test_parse_pdf_preserves_pages_through_nested_groups(tmp_path, monkeypatch):
    """Run export, artifact writing, and recursion with only the model call stubbed."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    # More than ten blocks on page one, followed by a nested group on page seven.
    texts = [
        {"label": "text", "orig": f"Paragraph {i}", "prov": [{"page_no": 1}]}
        for i in range(12)
    ]
    texts.append({"label": "formula", "orig": "E = mc^2", "prov": [{"page_no": 7}]})
    document = {
        "body": {
            "children": [{"$ref": f"#/texts/{i}"} for i in range(12)]
            + [{"$ref": "#/groups/0"}]
        },
        "groups": [{"children": [{"$ref": "#/texts/12"}]}],
        "texts": texts,
    }
    exported = SimpleNamespace(
        export_to_dict=lambda: document, export_to_markdown=lambda: "content"
    )
    converter = SimpleNamespace(convert=lambda _: SimpleNamespace(document=exported))
    parser = DoclingParser()
    monkeypatch.setattr(parser, "_get_converter", lambda **kwargs: converter)

    items = parser.parse_pdf(source, output_dir=tmp_path / "output")

    assert len(items) == 13
    assert [item["page_idx"] for item in items] == [0] * 12 + [6]
    assert items[-1]["type"] == "equation"
    assert list((tmp_path / "output").rglob("paper.json"))
