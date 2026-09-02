import json
from unittest.mock import patch

import pytest

from raganything.mineru_content import (
    MineruContentListV2Error,
    convert_mineru_content_list_v2,
)
from raganything.parser import MineruParser
from raganything.processor import ProcessorMixin
from raganything.utils import separate_content


def _text_span(text):
    return {"type": "text", "content": text}


def _v2_payload():
    return [
        [
            {
                "type": "page_header",
                "content": {"page_header_content": [_text_span("Running header")]},
                "bbox": [0, 0, 100, 20],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [_text_span("1 Introduction")],
                    "level": 1,
                },
                "bbox": [83, 121, 917, 156],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        _text_span("The method uses"),
                        {"type": "equation_inline", "content": "x^2"},
                        _text_span("features."),
                    ]
                },
            },
            {
                "type": "image",
                "content": {
                    "image_source": {"path": "images/figure.png"},
                    "content": "A system overview",
                    "image_caption": [_text_span("Figure 1")],
                    "image_footnote": [_text_span("Source: paper")],
                },
            },
            {
                "type": "table",
                "content": {
                    "image_source": {"path": "images/table.png"},
                    "html": "<table><tr><td>value</td></tr></table>",
                    "table_caption": [_text_span("Results")],
                    "table_footnote": [_text_span("Higher is better")],
                    "table_type": "simple_table",
                },
            },
            {
                "type": "equation_interline",
                "content": {
                    "math_content": "E = mc^2",
                    "math_type": "latex",
                    "image_source": {"path": "images/equation.png"},
                },
            },
            {
                "type": "page_number",
                "content": {"page_number_content": [_text_span("1")]},
            },
        ],
        [
            {
                "type": "list",
                "content": {
                    "list_type": "text_list",
                    "list_items": [
                        {"item_type": "text", "item_content": [_text_span("First")]},
                        {"item_type": "text", "item_content": [_text_span("Second")]},
                    ],
                },
            }
        ],
    ]


def test_convert_v2_flattens_pages_and_preserves_semantic_metadata():
    content_list = convert_mineru_content_list_v2(_v2_payload())

    assert [item["type"] for item in content_list] == [
        "text",
        "text",
        "image",
        "table",
        "equation",
        "text",
    ]
    assert content_list[0]["text"] == "1 Introduction"
    assert content_list[0]["text_level"] == 1
    assert content_list[0]["bbox"] == [83, 121, 917, 156]
    assert content_list[1]["text"] == "The method uses $x^2$ features."
    assert content_list[2]["img_path"] == "images/figure.png"
    assert content_list[2]["image_caption"] == ["Figure 1"]
    assert content_list[2]["image_footnote"] == ["Source: paper"]
    assert content_list[3]["table_body"].startswith("<table>")
    assert content_list[3]["table_caption"] == ["Results"]
    assert content_list[4]["text"] == "E = mc^2"
    assert content_list[4]["text_format"] == "latex"
    assert content_list[5]["page_idx"] == 1
    assert content_list[5]["list_items"] == ["First", "Second"]


def test_convert_v2_filters_layout_blocks_by_default_and_can_restore_them():
    default_content = convert_mineru_content_list_v2(_v2_payload())
    with_layout = convert_mineru_content_list_v2(
        _v2_payload(), include_layout_blocks=True
    )

    assert all(item["_mineru_v2_type"] != "page_header" for item in default_content)
    assert all(item["_mineru_v2_type"] != "page_number" for item in default_content)
    layout_items = [
        item
        for item in with_layout
        if item["_mineru_v2_type"] in {"page_header", "page_number"}
    ]
    assert [item["text"] for item in layout_items] == ["Running header", "1"]
    assert all(item["type"].startswith("page_") for item in layout_items)


def test_convert_v2_preserves_extended_mineru_modalities_and_routes_text():
    payload = [
        [
            {
                "type": "list",
                "content": {
                    "list_type": "reference_list",
                    "list_items": [
                        {"item_type": "text", "item_content": [_text_span("[1] Ref")]}
                    ],
                },
            },
            {
                "type": "chart",
                "sub_type": "bar_chart",
                "anchor": "figure-2",
                "content": {
                    "image_source": {"path": "images/chart.png"},
                    "content": "Revenue by quarter",
                    "chart_caption": [_text_span("Quarterly revenue")],
                    "chart_footnote": [_text_span("USD millions")],
                },
            },
            {
                "type": "code",
                "content": {
                    "code_content": "print('hello')",
                    "code_language": "python",
                    "code_caption": [_text_span("Example")],
                    "code_footnote": [_text_span("Simplified")],
                },
            },
            {
                "type": "algorithm",
                "content": {
                    "algorithm_content": "for each item",
                    "algorithm_caption": [_text_span("Algorithm 1")],
                    "algorithm_footnote": [_text_span("Pseudocode")],
                },
            },
            {
                "type": "abstract",
                "content": {"abstract_content": [_text_span("Summary")]},
            },
            {
                "type": "ref_text",
                "content": {"ref_text_content": [_text_span("Reference")]},
            },
            {"type": "equation_inline", "content": "a+b"},
        ]
    ]

    content_list = convert_mineru_content_list_v2(payload)

    assert content_list[0] == {
        "type": "text",
        "text": "[1] Ref",
        "list_items": ["[1] Ref"],
        "list_type": "reference_list",
        "page_idx": 0,
        "_mineru_v2_type": "list",
    }
    assert content_list[1]["img_path"] == "images/chart.png"
    assert content_list[1]["chart_caption"] == ["Quarterly revenue"]
    assert content_list[1]["chart_footnote"] == ["USD millions"]
    assert content_list[1]["sub_type"] == "bar_chart"
    assert content_list[1]["anchor"] == "figure-2"
    assert content_list[2]["code_body"] == "print('hello')"
    assert content_list[2]["code_footnote"] == ["Simplified"]
    assert content_list[3]["type"] == "code"
    assert content_list[3]["sub_type"] == "algorithm"
    assert content_list[3]["code_body"] == "for each item"
    assert content_list[3]["algorithm_footnote"] == ["Pseudocode"]
    assert content_list[4]["text"] == "Summary"
    assert content_list[5]["list_type"] == "reference_list"
    assert content_list[5]["text"] == "Reference"
    assert content_list[6]["text"] == "$a+b$"

    text_content, multimodal_items = separate_content(content_list)
    assert text_content == "[1] Ref\n\nSummary\n\nReference\n\n$a+b$"
    assert [item["type"] for item in multimodal_items] == [
        "chart",
        "code",
        "code",
    ]


def test_convert_v2_preserves_explicit_span_spacing_and_nested_links():
    payload = [
        [
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "A "},
                        {
                            "type": "hyperlink",
                            "content": "linked text",
                            "children": [{"type": "text", "content": " text"}],
                        },
                        {"type": "equation_inline", "content": "x"},
                        {"type": "text", "content": " works."},
                    ]
                },
            }
        ]
    ]

    assert convert_mineru_content_list_v2(payload)[0]["text"] == (
        "A linked text $x$ works."
    )


def test_convert_v2_skips_unknown_blocks_but_rejects_nonsemantic_payloads(caplog):
    payload = [
        [
            {"type": "future_block", "content": {"content": "ignored"}},
            {"content": {"content": "also ignored"}},
            {"type": "paragraph", "content": {"paragraph_content": "kept"}},
        ]
    ]

    assert convert_mineru_content_list_v2(payload)[0]["text"] == "kept"
    assert "future_block" in caplog.text

    with pytest.raises(MineruContentListV2Error, match="supported content blocks"):
        convert_mineru_content_list_v2([[{"type": "future_block"}]])


def test_convert_v2_rejects_invalid_shapes():
    with pytest.raises(MineruContentListV2Error):
        convert_mineru_content_list_v2([])
    with pytest.raises(MineruContentListV2Error):
        convert_mineru_content_list_v2([{"type": "paragraph"}])
    with pytest.raises(MineruContentListV2Error):
        convert_mineru_content_list_v2([["not a block"]])


def test_read_output_files_prefers_v2_and_resolves_media_paths(tmp_path):
    output_dir = tmp_path / "output"
    parse_dir = output_dir / "paper" / "auto"
    images_dir = parse_dir / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "figure.png").write_bytes(b"image")
    (parse_dir / "paper.md").write_text("markdown", encoding="utf-8")
    (parse_dir / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "legacy"}]), encoding="utf-8"
    )
    (parse_dir / "paper_content_list_v2.json").write_text(
        json.dumps(_v2_payload()), encoding="utf-8"
    )

    content_list, markdown = MineruParser._read_output_files(
        output_dir, "paper", method="auto"
    )

    assert markdown == "markdown"
    assert content_list[0]["text"] == "1 Introduction"
    image = next(item for item in content_list if item["type"] == "image")
    assert image["img_path"] == str((images_dir / "figure.png").resolve())


def test_read_output_files_prefers_exact_stem_over_generic_v2(tmp_path):
    parse_dir = tmp_path / "paper" / "auto"
    parse_dir.mkdir(parents=True)
    (tmp_path / "content_list_v2.json").write_text(
        json.dumps(
            [[{"type": "paragraph", "content": {"paragraph_content": "wrong"}}]]
        ),
        encoding="utf-8",
    )
    (parse_dir / "paper_content_list_v2.json").write_text(
        json.dumps(
            [[{"type": "paragraph", "content": {"paragraph_content": "right"}}]]
        ),
        encoding="utf-8",
    )

    content_list, _ = MineruParser._read_output_files(tmp_path, "paper")

    assert content_list[0]["text"] == "right"


def test_read_output_files_prefers_scoped_legacy_over_shared_generic_v2(tmp_path):
    parse_dir = tmp_path / "paper" / "auto"
    parse_dir.mkdir(parents=True)
    (tmp_path / "content_list_v2.json").write_text(
        json.dumps(
            [[{"type": "paragraph", "content": {"paragraph_content": "wrong"}}]]
        ),
        encoding="utf-8",
    )
    (parse_dir / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "right"}]), encoding="utf-8"
    )

    content_list, _ = MineruParser._read_output_files(tmp_path, "paper")

    assert content_list[0]["text"] == "right"


def test_read_output_files_prefers_v2_when_legacy_and_generic_v2_share_bundle(
    tmp_path,
):
    legacy = [{"type": "text", "text": "legacy"}]
    v2 = [[{"type": "paragraph", "content": {"paragraph_content": "v2"}}]]
    (tmp_path / "paper_content_list.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    (tmp_path / "content_list_v2.json").write_text(json.dumps(v2), encoding="utf-8")

    content_list, _ = MineruParser._read_output_files(tmp_path, "paper")

    assert content_list[0]["text"] == "v2"


def test_read_output_files_accepts_generic_v2_filename_and_layout_option(tmp_path):
    parse_dir = tmp_path / "paper" / "auto"
    parse_dir.mkdir(parents=True)
    (parse_dir / "content_list_v2.json").write_text(
        json.dumps(_v2_payload()), encoding="utf-8"
    )

    content_list, _ = MineruParser._read_output_files(
        tmp_path, "paper", include_layout_blocks=True
    )

    assert content_list[0]["type"] == "page_header"
    assert content_list[-2]["type"] == "page_number"


@pytest.mark.parametrize("v2_value", [[], {"not": "a page list"}, "invalid"])
def test_read_output_files_falls_back_to_legacy_when_v2_is_unusable(tmp_path, v2_value):
    parse_dir = tmp_path / "paper" / "auto"
    parse_dir.mkdir(parents=True)
    legacy = [{"type": "text", "text": "legacy", "page_idx": 0}]
    (parse_dir / "paper_content_list.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    (parse_dir / "paper_content_list_v2.json").write_text(
        json.dumps(v2_value), encoding="utf-8"
    )

    content_list, _ = MineruParser._read_output_files(tmp_path, "paper")

    assert content_list == legacy


def test_read_output_files_falls_back_when_v2_json_is_malformed(tmp_path):
    parse_dir = tmp_path / "paper" / "auto"
    parse_dir.mkdir(parents=True)
    legacy = [{"type": "text", "text": "legacy", "page_idx": 0}]
    (parse_dir / "paper_content_list.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    (parse_dir / "paper_content_list_v2.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    content_list, _ = MineruParser._read_output_files(tmp_path, "paper")

    assert content_list == legacy


def test_read_output_files_refreshes_markdown_when_v2_falls_back(tmp_path):
    output_dir = tmp_path / "output"
    v2_dir = output_dir / "paper" / "auto"
    legacy_dir = output_dir
    v2_dir.mkdir(parents=True)
    (v2_dir / "paper_content_list_v2.json").write_text("[]", encoding="utf-8")
    (legacy_dir / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "legacy"}]), encoding="utf-8"
    )
    (legacy_dir / "paper.md").write_text("legacy markdown", encoding="utf-8")

    content_list, markdown = MineruParser._read_output_files(output_dir, "paper")

    assert content_list == [{"type": "text", "text": "legacy"}]
    assert markdown == "legacy markdown"


def test_layout_option_isolated_in_parse_cache_key(tmp_path):
    class DummyProcessor(ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.config = type(
        "Config", (), {"parser": "mineru", "parse_method": "auto"}
    )()
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    default_key = processor._generate_cache_key(source, include_layout_blocks=False)
    layout_key = processor._generate_cache_key(source, include_layout_blocks=True)

    assert default_key != layout_key
    assert processor._relevant_parser_kwargs(
        {"include_layout_blocks": True, "unrelated": "ignored"}
    ) == {"include_layout_blocks": True}
    assert (
        processor._relevant_parser_kwargs(
            {"include_layout_blocks": False, "unrelated": "ignored"}
        )
        == {}
    )


def test_parse_pdf_wires_layout_option_to_output_reader(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    with (
        patch.object(MineruParser, "_run_mineru_command"),
        patch.object(MineruParser, "_read_output_files", return_value=([], "")) as read,
    ):
        MineruParser().parse_pdf(
            pdf_path, output_dir=tmp_path / "out", include_layout_blocks=True
        )

    assert read.call_args.kwargs["include_layout_blocks"] is True


def test_parse_image_wires_layout_option_to_output_reader(tmp_path):
    image_path = tmp_path / "paper.png"
    image_path.write_bytes(b"\x89PNG\r\n")

    with (
        patch.object(MineruParser, "_run_mineru_command"),
        patch.object(MineruParser, "_read_output_files", return_value=([], "")) as read,
    ):
        MineruParser().parse_image(
            image_path, output_dir=tmp_path / "out", include_layout_blocks=True
        )

    assert read.call_args.kwargs["include_layout_blocks"] is True
