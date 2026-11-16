"""Unit tests for token budgeting and structure-preserving table truncation (Issue #83).

Verifies that:
1. Tables and equations exceeding token budgets are truncated defensively.
2. Markdown table structure (header row and separator) is preserved while retaining
   data rows up to the configured token budget.
3. HTML tables are truncated at row boundaries and closed cleanly.
4. An explicit structural summary marker is appended documenting the omitted rows.
5. End-to-end captioning functions receive bounded prompts preventing LLM context overflows.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from raganything.config import RAGAnythingConfig
from raganything.modalprocessors import EquationModalProcessor, TableModalProcessor


def create_mock_lightrag(tokenizer=None):
    lr = MagicMock()
    lr.text_chunks = MagicMock()
    lr.chunks_vdb = MagicMock()
    lr.entities_vdb = MagicMock()
    lr.relationships_vdb = MagicMock()
    lr.chunk_entity_relation_graph = MagicMock()
    lr.embedding_func = MagicMock()
    lr.llm_model_func = MagicMock()
    lr._build_global_config = MagicMock(return_value={})
    lr.llm_response_cache = MagicMock()
    lr.tokenizer = tokenizer
    return lr


def test_config_token_budget_defaults():
    config = RAGAnythingConfig()
    assert config.max_table_tokens == 0
    assert config.max_modal_content_tokens == 0


@pytest.mark.parametrize("kind", ["markdown", "html", "equation"])
def test_explicit_budget_counts_the_marker_and_multibyte_text(kind):
    from raganything.token_budget import truncate_table, truncate_text

    def count(text):
        return len(text.encode("utf-8"))

    budget = 300
    if kind == "equation":
        result = truncate_text(
            "变量甲乙丙" * 200, budget, count, "\n[... truncated ...]"
        )
    else:
        content = (
            ("| 项目 | 数量 |\n|---|---|\n" + "| 中文项目 | 42 |\n" * 100)
            if kind == "markdown"
            else (
                "<table><tr><th>项目</th><th>数量</th></tr>"
                + "<tr><td>中文项目</td><td>42</td></tr>" * 100
                + "</table>"
            )
        )
        result = truncate_table(content, budget, count)
    assert count(result) <= budget
    assert "�" not in result


@pytest.mark.asyncio
async def test_budget_too_small_is_an_error_and_never_a_successful_caption():
    from raganything.token_budget import TokenBudgetError

    model = AsyncMock()
    processor = TableModalProcessor(create_mock_lightrag(), model, max_table_tokens=1)
    with pytest.raises(TokenBudgetError, match="header"):
        await processor.generate_description_only(
            {"table_body": "| Long header |\n|---|\n" + "| a value |\n" * 20}, "table"
        )
    model.assert_not_called()


def test_table_small_markdown_passes_through():
    lr = create_mock_lightrag()
    proc = TableModalProcessor(
        lightrag=lr, modal_caption_func=AsyncMock(), max_table_tokens=100
    )
    small_md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    truncated = proc._truncate_table_for_context(small_md)
    assert truncated == small_md


def test_table_large_markdown_structure_preserved():
    lr = create_mock_lightrag()
    # Token budget of 50 tokens (approx 200 chars)
    proc = TableModalProcessor(
        lightrag=lr, modal_caption_func=AsyncMock(), max_table_tokens=50
    )

    rows = [
        f"| Item {i} | Category {i} | Description for value {i} in table |"
        for i in range(100)
    ]
    large_md = "| ID | Name | Details |\n|---|---|---|\n" + "\n".join(rows)

    truncated = proc._truncate_table_for_context(large_md)

    # Header and separator MUST be preserved
    assert "| ID | Name | Details |" in truncated
    assert "|---|---|---|" in truncated

    # Truncation marker must be present with row counts
    assert "rows omitted for LLM context window budget" in truncated
    assert "total rows: 100" in truncated

    # Total token count must be within reasonable bounds
    assert proc._count_tokens(truncated) <= 65


def test_table_large_html_structure_preserved():
    lr = create_mock_lightrag()
    proc = TableModalProcessor(
        lightrag=lr, modal_caption_func=AsyncMock(), max_table_tokens=60
    )

    html_rows = [
        f"<tr><td>{i}</td><td>Value_{i}</td><td>Extra long text details for row {i}</td></tr>"
        for i in range(80)
    ]
    large_html = (
        "<table><thead><tr><th>ID</th><th>Val</th><th>Desc</th></tr></thead><tbody>\n"
        + "\n".join(html_rows)
        + "</tbody></table>"
    )

    truncated = proc._truncate_table_for_context(large_html)

    # Header must be present
    assert "<th>ID</th>" in truncated
    # Closing tags and comments must be present
    assert "rows omitted for context budget" in truncated
    assert "</tbody></table>" in truncated


def test_table_disable_truncation():
    lr = create_mock_lightrag()
    proc = TableModalProcessor(
        lightrag=lr, modal_caption_func=AsyncMock(), max_table_tokens=0
    )
    large_text = "| Col |\n|---|\n" + "\n".join([f"| row {i} |" for i in range(200)])
    # When max_table_tokens is 0, no truncation occurs
    assert proc._truncate_table_for_context(large_text) == large_text


def test_equation_truncation():
    lr = create_mock_lightrag()
    proc = EquationModalProcessor(
        lightrag=lr, modal_caption_func=AsyncMock(), max_modal_content_tokens=30
    )

    long_eq = "x = " + " + ".join([f"a_{i} * y_{i}" for i in range(100)])
    truncated = proc._truncate_equation_for_context(long_eq)

    assert "equation truncated to ~30 tokens" in truncated
    assert len(truncated) < len(long_eq)


@pytest.mark.asyncio
async def test_table_generate_description_only_respects_token_budget():
    lr = create_mock_lightrag()
    caption_calls = []

    async def mock_caption(prompt, system_prompt=None):
        caption_calls.append(prompt)
        return '{"detailed_description": "Analyzed table", "entity_info": {"entity_name": "T1", "entity_type": "table", "summary": "Sum"}}'

    proc = TableModalProcessor(
        lightrag=lr, modal_caption_func=mock_caption, max_table_tokens=80
    )

    rows = [
        f"| Row {i} | Value {i * 10} | Extremely descriptive narrative for line {i} |"
        for i in range(150)
    ]
    massive_table = "| Col A | Col B | Col C |\n|---|---|---|\n" + "\n".join(rows)

    desc, entity_info = await proc.generate_description_only(
        modal_content={"table_body": massive_table},
        content_type="table",
    )

    assert len(caption_calls) == 1
    prompt_sent = caption_calls[0]

    # Verify the table in the prompt was truncated and includes the summary marker
    assert "rows omitted for LLM context window budget" in prompt_sent
    assert desc == "Analyzed table"
    assert entity_info["entity_name"] == "T1 (table)"
