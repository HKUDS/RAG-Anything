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
async def test_modal_processors_graceful_degradation_without_caption_func(tmp_path):
    """Test modal processors do not crash with NoneType is not callable when caption_func is None (#9)."""
    mock_lightrag = MagicMock()
    mock_lightrag.text_chunks = MagicMock()
    mock_lightrag.chunks_vdb = MagicMock()
    mock_lightrag.entities_vdb = MagicMock()
    mock_lightrag.relationships_vdb = MagicMock()

    # 1. TableModalProcessor without caption function
    table_proc = TableModalProcessor(lightrag=mock_lightrag, modal_caption_func=None)
    _caption, entity = await table_proc.generate_description_only(
        modal_content={"table_body": "| A | B |\n| 1 | 2 |"},
        content_type="table",
        entity_name="test_table",
    )
    assert entity["entity_name"] == "test_table"
    assert entity["entity_type"] == "table"

    # 2. EquationModalProcessor without caption function
    eq_proc = EquationModalProcessor(lightrag=mock_lightrag, modal_caption_func=None)
    _caption, entity = await eq_proc.generate_description_only(
        modal_content={"equation_text": "E = mc^2"},
        content_type="equation",
        entity_name="einstein_eq",
    )
    assert entity["entity_name"] == "einstein_eq"
    assert entity["entity_type"] == "equation"

    # 3. ImageModalProcessor without caption function
    img_proc = ImageModalProcessor(lightrag=mock_lightrag, modal_caption_func=None)
    _caption, entity = await img_proc.generate_description_only(
        modal_content={"img_path": "dummy.jpg"},
        content_type="image",
        entity_name="test_img",
    )
    assert entity["entity_name"] == "test_img"
    assert entity["entity_type"] == "image"


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
