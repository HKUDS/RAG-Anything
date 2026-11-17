import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from raganything.prompt import PROMPTS
from raganything.prompt_manager import (
    set_prompt_language,
    get_prompt_language,
    reset_prompts,
)
from raganything.modalprocessors import (
    ImageModalProcessor,
    TableModalProcessor,
    EquationModalProcessor,
    GenericModalProcessor,
    ContextExtractor,
    ContextConfig,
    _prepend_page_grounding,
)
from raganything.processor import ProcessorMixin


def test_traditional_chinese_prompts_switching():
    # Reset to English baseline
    reset_prompts()
    assert get_prompt_language() == "en"
    assert "expert image analyst" in PROMPTS["IMAGE_ANALYSIS_SYSTEM"]

    # Switch to zh-tw
    set_prompt_language("zh-tw")
    assert get_prompt_language() == "zh-tw"
    assert "專業的圖像分析專家" in PROMPTS["IMAGE_ANALYSIS_SYSTEM"]
    assert "繁體" in PROMPTS["vision_prompt"] or "版面配置" in PROMPTS["vision_prompt"]

    # Switch using zh-hant alias
    set_prompt_language("zh-hant")
    assert get_prompt_language() == "zh-hant"
    assert "專業的圖像分析專家" in PROMPTS["IMAGE_ANALYSIS_SYSTEM"]

    # Reset back to English
    reset_prompts()
    assert get_prompt_language() == "en"
    assert "expert image analyst" in PROMPTS["IMAGE_ANALYSIS_SYSTEM"]


def test_prepend_page_grounding_helper():
    chunk = "Sample content"
    assert _prepend_page_grounding(chunk, 0) == "[Page 1]\nSample content"
    assert _prepend_page_grounding(chunk, 5) == "[Page 6]\nSample content"
    assert _prepend_page_grounding(chunk, None) == "Sample content"
    assert _prepend_page_grounding(chunk, -1) == "Sample content"

    # Idempotency check: do not double-prepend
    already_prefixed = "[Page 3]\nExisting content"
    assert _prepend_page_grounding(already_prefixed, 2) == already_prefixed


def test_context_extractor_1_based_page_citation():
    extractor = ContextExtractor(config=ContextConfig(context_window=2))
    content_list = [
        {"type": "text", "text": "First page paragraph", "page_idx": 0},
        {"type": "text", "text": "Second page paragraph", "page_idx": 1},
    ]

    # Target item on page 1 (1-based Page 2)
    current_item = {"page_idx": 1, "index": 1}
    context = extractor.extract_context(
        content_list, current_item, content_format="minerU"
    )

    assert "[Page 1] First page paragraph" in context


def _fake_lightrag():
    lr = MagicMock()
    lr.working_dir = "/tmp/fake_lightrag"
    lr.text_chunks = MagicMock()
    lr.text_chunks.upsert = AsyncMock()
    lr.text_chunks.get_by_id = AsyncMock(
        return_value={"content": "test chunk", "tokens": 10, "chunk_order_index": 0}
    )
    lr.chunks_vdb = MagicMock()
    lr.chunks_vdb.upsert = AsyncMock()
    lr.entities_vdb = MagicMock()
    lr.entities_vdb.upsert = AsyncMock()
    lr.relationships_vdb = MagicMock()
    lr.chunk_entity_relation_graph = MagicMock()
    lr.chunk_entity_relation_graph.upsert_node = AsyncMock()
    lr.embedding_func = AsyncMock()
    lr.llm_model_func = AsyncMock()
    lr.llm_response_cache = MagicMock()
    mock_tok = MagicMock()
    mock_tok.encode = lambda text: [1] * max(1, len(str(text).split()))
    lr.tokenizer = mock_tok
    return lr


@pytest.mark.asyncio
async def test_modal_processors_format_1_based_page_citations():
    lr = _fake_lightrag()

    # Test TableModalProcessor
    table_proc = TableModalProcessor(
        lr, modal_caption_func=AsyncMock(return_value="Table summary")
    )
    table_proc._create_entity_and_chunk = AsyncMock(
        side_effect=lambda modal_chunk, entity_info, *args, **kwargs: (
            modal_chunk,
            entity_info,
            [],
        )
    )

    table_item = {
        "type": "table",
        "table_body": "| A | B |\n|---|---|\n| 1 | 2 |",
        "page_idx": 2,  # 0-indexed page 2 -> 1-based Page 3
    }
    chunk, entity_info, _ = await table_proc.process_multimodal_content(
        table_item, "table"
    )
    assert chunk.startswith("[Page 3]\n")

    # Test EquationModalProcessor
    eq_proc = EquationModalProcessor(
        lr, modal_caption_func=AsyncMock(return_value="Equation summary")
    )
    eq_proc._create_entity_and_chunk = AsyncMock(
        side_effect=lambda modal_chunk, entity_info, *args, **kwargs: (
            modal_chunk,
            entity_info,
            [],
        )
    )

    eq_item = {
        "type": "equation",
        "latex": "E = mc^2",
        "page_idx": 0,  # 0-indexed page 0 -> 1-based Page 1
    }
    chunk, entity_info, _ = await eq_proc.process_multimodal_content(
        eq_item, "equation"
    )
    assert chunk.startswith("[Page 1]\n")


def test_processor_format_modal_chunk_page_spans():
    class DummyProcessor(ProcessorMixin):
        def __init__(self):
            self.logger = MagicMock()
            self._instance_prompts = PROMPTS

    proc = DummyProcessor()

    # Single page chunk (page_idx: 3 -> [Page 4])
    item_single = {
        "type": "equation",
        "latex": "a^2 + b^2 = c^2",
        "page_idx": 3,
    }
    res_single = proc._apply_chunk_template(
        "equation", item_single, "Pythagoras theorem"
    )
    assert res_single.startswith("[Page 4]\n")

    # Multi-page table span (page_idx: 1, page_idx_end: 3 -> [Page 2-4])
    item_span = {
        "type": "table",
        "table_body": "| Col1 | Col2 |",
        "page_idx": 1,
        "page_idx_end": 3,
    }
    res_span = proc._apply_chunk_template(
        "table", item_span, "Continued financial table"
    )
    assert res_span.startswith("[Page 2-4]\n")

    # No page_idx provided: no [Page prefix
    item_nopage = {
        "type": "equation",
        "latex": "x = y",
    }
    res_nopage = proc._apply_chunk_template("equation", item_nopage, "Simple equality")
    assert not res_nopage.startswith("[Page")
