from unittest.mock import AsyncMock, MagicMock

import pytest

from raganything.config import RAGAnythingConfig
from raganything.modalprocessors import (
    EquationModalProcessor,
    ImageModalProcessor,
    TableModalProcessor,
)
from raganything.raganything import RAGAnything


def test_raganything_inherits_model_funcs_from_lightrag(tmp_path):
    """Test RAGAnything inherits llm_model_func and embedding_func from existing LightRAG."""
    mock_llm = AsyncMock(return_value="llm response")
    mock_embed = AsyncMock(return_value=[0.1] * 1536)

    mock_lightrag = MagicMock()
    mock_lightrag.llm_model_func = mock_llm
    mock_lightrag.embedding_func = mock_embed
    mock_lightrag.tokenizer = MagicMock()

    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag_storage"),
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    rag = RAGAnything(config=config, lightrag=mock_lightrag)
    rag.finalize_storages = AsyncMock()
    rag._initialize_processors()

    # Verify model functions were inherited
    assert rag.llm_model_func is mock_llm
    assert rag.embedding_func is mock_embed

    # Initialize processors and verify they receive the inherited function
    rag._initialize_processors()
    assert rag.modal_processors["table"].modal_caption_func is mock_llm
    assert rag.modal_processors["equation"].modal_caption_func is mock_llm
    assert rag.modal_processors["image"].modal_caption_func is mock_llm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "processor_cls", [TableModalProcessor, EquationModalProcessor, ImageModalProcessor]
)
async def test_missing_caption_model_is_an_explicit_error(processor_cls):
    processor = processor_cls(lightrag=MagicMock(), modal_caption_func=None)
    with pytest.raises(ValueError, match="Configure a callable model"):
        await processor.generate_description_only({"table_body": "A table"}, "table")


def test_invalid_caption_model_is_rejected():
    with pytest.raises(TypeError, match="modal_caption_func"):
        TableModalProcessor(lightrag=MagicMock(), modal_caption_func="model-name")


def test_explicit_models_override_existing_lightrag(tmp_path):
    inherited, explicit = AsyncMock(), AsyncMock()
    backend = MagicMock(llm_model_func=inherited, embedding_func=inherited)
    rag = RAGAnything(
        config=RAGAnythingConfig(working_dir=str(tmp_path)),
        lightrag=backend,
        llm_model_func=explicit,
        embedding_func=explicit,
    )
    rag.finalize_storages = AsyncMock()
    rag._initialize_processors()
    assert rag.llm_model_func is explicit
    assert rag.embedding_func is explicit
    assert rag.modal_processors["table"].modal_caption_func is explicit


@pytest.mark.asyncio
async def test_insert_content_list_with_existing_lightrag_modal_content(tmp_path):
    """Test insert_content_list with multimodal content when passing existing LightRAG instance."""
    from unittest.mock import patch

    mock_llm = AsyncMock(return_value="Caption: Summary\nEntity Name: ExtractedEntity")
    mock_embed = AsyncMock(return_value=[0.1] * 1536)

    mock_lightrag = MagicMock()
    mock_lightrag.llm_model_func = mock_llm
    mock_lightrag.embedding_func = mock_embed
    mock_lightrag.tokenizer = MagicMock()
    mock_lightrag.insert = AsyncMock()
    mock_lightrag.ainsert = AsyncMock()
    mock_lightrag.full_docs = MagicMock()
    mock_lightrag.full_docs.get_by_id = AsyncMock(return_value={"content": "test text"})
    mock_lightrag.text_chunks = MagicMock()
    mock_lightrag.text_chunks.get_by_id = AsyncMock(return_value=None)
    mock_lightrag.text_chunks.upsert = AsyncMock()
    mock_lightrag.chunks_vdb = MagicMock()
    mock_lightrag.chunks_vdb.upsert = AsyncMock()
    mock_lightrag.doc_status = MagicMock()
    mock_lightrag.doc_status.get_by_id = AsyncMock(
        return_value={"status": "processed", "chunks_list": []}
    )
    mock_lightrag.doc_status.upsert = AsyncMock()
    mock_lightrag.doc_status.index_done_callback = AsyncMock()

    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag_storage"),
        enable_image_processing=False,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    rag = RAGAnything(config=config, lightrag=mock_lightrag)
    rag.finalize_storages = AsyncMock()
    rag._initialize_processors()

    content_list = [
        {"type": "text", "text": "Intro text before table."},
        {
            "type": "table",
            "table_body": "| Col1 | Col2 |\n| Val1 | Val2 |",
            "page_idx": 0,
        },
        {"type": "equation", "equation_text": "\\sum_{i=1}^n x_i", "page_idx": 0},
    ]

    with (
        patch.object(
            rag, "_ensure_lightrag_initialized", return_value={"success": True}
        ),
        patch.object(
            rag, "_process_multimodal_content", new=AsyncMock()
        ) as mock_mm_process,
    ):
        await rag.insert_content_list(
            content_list=content_list, file_path="test_doc.pdf", doc_id="doc-test-123"
        )
        mock_mm_process.assert_awaited_once()


def test_legacy_parser_check_alias_delegates(tmp_path, monkeypatch):
    rag = RAGAnything(config=RAGAnythingConfig(working_dir=str(tmp_path)))
    monkeypatch.setattr(rag, "check_parser_installation", lambda: True)
    with pytest.warns(DeprecationWarning, match="check_parser_installation"):
        assert rag.check_mineru_installation() is True
