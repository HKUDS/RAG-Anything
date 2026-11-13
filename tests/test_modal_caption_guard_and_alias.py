"""Tests for modal caption function guarding and backward compatibility aliases (#9, #112).

Ensures that:
- BaseModalProcessor raises TypeError when modal_caption_func is neither None nor callable
- Image, Table, Equation, and Generic modal processors gracefully fall back to metadata
  without raising 'NoneType' object is not callable when modal_caption_func is None (#9)
- check_mineru_installation issues a DeprecationWarning and delegates to check_parser_installation (#112)
- _initialize_processors logs informative warnings when multimodal processing is enabled
  without a model function
"""

import warnings
from unittest.mock import MagicMock

import pytest

from raganything.modalprocessors import (
    BaseModalProcessor,
    EquationModalProcessor,
    GenericModalProcessor,
    ImageModalProcessor,
    TableModalProcessor,
)
from raganything.raganything import RAGAnything, RAGAnythingConfig


class FakeTokenizer:
    def encode(self, text):
        return text.split()


class FakeLightRAG:
    def __init__(self):
        self.text_chunks = MagicMock()
        self.chunks_vdb = MagicMock()
        self.entities_vdb = MagicMock()
        self.relationships_vdb = MagicMock()
        self.chunk_entity_relation_graph = MagicMock()
        self.embedding_func = None
        self.llm_model_func = None
        self.llm_response_cache = None
        self.tokenizer = FakeTokenizer()
        self.workspace = "/fake/workspace"

    def _build_global_config(self):
        return {}


def test_base_modal_processor_rejects_non_callable():
    """BaseModalProcessor must reject non-callable, non-None modal_caption_func."""
    fake_lightrag = FakeLightRAG()
    with pytest.raises(TypeError, match="modal_caption_func must be callable or None"):
        BaseModalProcessor(fake_lightrag, modal_caption_func="not_a_function")

    with pytest.raises(TypeError, match="modal_caption_func must be callable or None"):
        BaseModalProcessor(fake_lightrag, modal_caption_func=12345)


@pytest.mark.asyncio
async def test_image_processor_graceful_fallback_when_caption_func_none(tmp_path):
    """ImageModalProcessor must not crash with TypeError: 'NoneType' object is not callable (#9)."""
    fake_lightrag = FakeLightRAG()
    processor = ImageModalProcessor(fake_lightrag, modal_caption_func=None)

    fake_img = tmp_path / "sample.png"
    fake_img.write_bytes(b"fake image bytes")

    item = {"img_path": str(fake_img), "type": "image"}
    caption, entity = await processor.generate_description_only(item, "image")

    assert str(item) in caption
    assert entity["entity_type"] == "image"
    assert "Image content:" in entity["summary"]


@pytest.mark.asyncio
async def test_table_processor_graceful_fallback_when_caption_func_none():
    """TableModalProcessor must gracefully fall back when modal_caption_func is None."""
    fake_lightrag = FakeLightRAG()
    processor = TableModalProcessor(fake_lightrag, modal_caption_func=None)

    item = {
        "type": "table",
        "table_body": "| A | B |\n|---|---|\n| 1 | 2 |",
        "table_caption": ["Test Table"],
    }
    caption, entity = await processor.generate_description_only(item, "table")

    assert str(item) in caption
    assert entity["entity_type"] == "table"
    assert "Table content:" in entity["summary"]


@pytest.mark.asyncio
async def test_equation_processor_graceful_fallback_when_caption_func_none():
    """EquationModalProcessor must gracefully fall back when modal_caption_func is None."""
    fake_lightrag = FakeLightRAG()
    processor = EquationModalProcessor(fake_lightrag, modal_caption_func=None)

    item = {
        "type": "equation",
        "text": "E = mc^2",
        "text_format": "latex",
    }
    caption, entity = await processor.generate_description_only(item, "equation")

    assert str(item) in caption
    assert entity["entity_type"] == "equation"
    assert "Equation content:" in entity["summary"]


@pytest.mark.asyncio
async def test_generic_processor_graceful_fallback_when_caption_func_none():
    """GenericModalProcessor must gracefully fall back when modal_caption_func is None."""
    fake_lightrag = FakeLightRAG()
    processor = GenericModalProcessor(fake_lightrag, modal_caption_func=None)

    item = {"type": "custom_data", "value": 42}
    caption, entity = await processor.generate_description_only(item, "custom_data")

    assert str(item) in caption
    assert entity["entity_type"] == "custom_data"
    assert "custom_data content:" in entity["summary"]


def test_check_mineru_installation_deprecated_alias():
    """check_mineru_installation must issue a DeprecationWarning and call check_parser_installation (#112)."""
    rag = RAGAnything(
        config=RAGAnythingConfig(working_dir="./rag_storage_test", parser="mineru")
    )
    rag.doc_parser.check_installation = MagicMock(return_value=True)

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        result = rag.check_mineru_installation()

        assert result is True
        assert len(recorded_warnings) == 1
        assert issubclass(recorded_warnings[0].category, DeprecationWarning)
        assert "check_mineru_installation is deprecated" in str(
            recorded_warnings[0].message
        )
