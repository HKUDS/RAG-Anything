"""Multimodal query descriptions must preserve parser content-list shapes."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from raganything.query import QueryMixin


@pytest.fixture
def query():
    instance = QueryMixin()
    instance.logger = logging.getLogger(__name__)
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caption,footnote",
    [
        ("A revenue chart", "Values in millions"),
        (["A revenue chart"], ["Values in millions"]),
    ],
)
async def test_image_fallback_keeps_captions_whole(query, caption, footnote):
    description = await query._describe_image_for_query(
        None,
        {"image_caption": caption, "image_footnote": footnote},
    )
    assert "Image captions: A revenue chart" in description
    assert "Image footnotes: Values in millions" in description


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["table_body", "table_data", "text"])
async def test_table_aliases_reach_the_analysis_prompt(query, field):
    processor = SimpleNamespace(
        modal_caption_func=AsyncMock(return_value="table description")
    )
    result = await query._describe_table_for_query(
        processor,
        {
            field: "<table><tr><td>Revenue</td><td>42</td></tr></table>",
            "table_caption": "Annual revenue",
        },
    )
    assert result == "table description"
    prompt = processor.modal_caption_func.call_args.args[0]
    assert "<td>Revenue</td><td>42</td>" in prompt
    assert "Annual revenue" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["text", "latex", "equation"])
async def test_equation_aliases_reach_the_analysis_prompt(query, field):
    processor = SimpleNamespace(
        modal_caption_func=AsyncMock(return_value="equation description")
    )
    result = await query._describe_equation_for_query(
        processor, {field: "E = mc^2", "equation_caption": "Mass-energy equivalence"}
    )
    assert result == "equation description"
    prompt = processor.modal_caption_func.call_args.args[0]
    assert "E = mc^2" in prompt
    assert "Mass-energy equivalence" in prompt


@pytest.mark.asyncio
async def test_explicit_latex_is_not_replaced_by_its_text_description(query):
    processor = SimpleNamespace(
        modal_caption_func=AsyncMock(return_value="description")
    )
    await query._describe_equation_for_query(
        processor, {"latex": "E = mc^2", "text": "Mass-energy equivalence"}
    )
    assert "LaTeX formula: E = mc^2" in processor.modal_caption_func.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["table", "equation"])
async def test_list_captions_are_presented_as_text(query, kind):
    processor = SimpleNamespace(
        modal_caption_func=AsyncMock(return_value="description")
    )
    await getattr(query, f"_describe_{kind}_for_query")(
        processor,
        {f"{kind}_caption": ["First caption", "Second caption"]},
    )
    prompt = processor.modal_caption_func.call_args.args[0]
    assert "First caption, Second caption" in prompt
    assert "['First caption'" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,expected",
    [
        ({"type": "image", "image_caption": "Revenue chart"}, "Revenue chart"),
        ({"type": "table", "table_body": [["Revenue", 42]]}, "| Revenue | 42 |"),
        ({"type": "equation", "text": "E = mc^2"}, "E = mc^2"),
    ],
)
async def test_query_enhancement_preserves_parser_content(query, content, expected):
    processor = SimpleNamespace(
        modal_caption_func=AsyncMock(side_effect=lambda prompt, **kwargs: prompt)
    )
    query.modal_processors = {content["type"]: processor}
    result = await query._process_multimodal_query_content("Explain this", [content])
    assert "Explain this" in result
    assert expected in result
