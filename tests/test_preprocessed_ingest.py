import json
from unittest.mock import AsyncMock, patch

import pytest

from raganything.config import RAGAnythingConfig
from raganything.raganything import RAGAnything


@pytest.fixture
def temp_mineru_output(tmp_path):
    """Create a mock MinerU output directory structure."""
    doc_dir = tmp_path / "sample_doc"
    doc_dir.mkdir()

    content_list = [
        {
            "type": "text",
            "text": "This is preprocessed document content.",
            "page_idx": 0,
        },
        {
            "type": "image",
            "img_path": "images/test.jpg",
            "image_caption": ["Test image"],
            "page_idx": 1,
        },
    ]
    json_path = doc_dir / "sample_doc_content_list.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(content_list, f)

    md_path = doc_dir / "sample_doc.md"
    md_path.write_text("# Sample Document\n\nThis is markdown text.", encoding="utf-8")

    images_dir = doc_dir / "images"
    images_dir.mkdir()
    (images_dir / "test.jpg").write_bytes(b"dummy image bytes")

    return doc_dir


@pytest.fixture
def temp_batch_mineru_dir(tmp_path):
    """Create a mock batch MinerU output directory with multiple document subfolders."""
    base_dir = tmp_path / "batch_docs"
    base_dir.mkdir()

    for name in ["doc_alpha", "doc_beta"]:
        doc_dir = base_dir / name
        doc_dir.mkdir()
        content_list = [{"type": "text", "text": f"Content for {name}", "page_idx": 0}]
        with open(doc_dir / f"{name}_content_list.json", "w", encoding="utf-8") as f:
            json.dump(content_list, f)
        (doc_dir / f"{name}.md").write_text(f"# {name}", encoding="utf-8")

    return base_dir


@pytest.mark.asyncio
async def test_process_preprocessed_output_success(temp_mineru_output):
    """Test process_preprocessed_output successfully reads preprocessed output and inserts it."""
    config = RAGAnythingConfig(
        working_dir=str(temp_mineru_output.parent / "rag_storage"),
        enable_image_processing=False,
        enable_table_processing=False,
        enable_equation_processing=False,
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=AsyncMock(return_value="mock answer"),
        embedding_func=AsyncMock(return_value=[0.1] * 1536),
    )

    with (
        patch.object(
            rag, "insert_content_list", new=AsyncMock(return_value="doc-test-123")
        ) as mock_insert,
        patch("raganything.parser.MineruParser._run_mineru_command") as mock_run_cmd,
    ):
        content_list, doc_id = await rag.process_preprocessed_output(
            output_dir=temp_mineru_output,
            file_stem="sample_doc",
        )

        assert len(content_list) == 2
        assert content_list[0]["text"] == "This is preprocessed document content."
        assert doc_id is not None
        mock_insert.assert_awaited_once()
        # Verify parser command was never invoked
        mock_run_cmd.assert_not_called()


@pytest.mark.asyncio
async def test_process_preprocessed_output_auto_stem(temp_mineru_output):
    """Test process_preprocessed_output automatically detects file_stem if omitted."""
    config = RAGAnythingConfig(
        working_dir=str(temp_mineru_output.parent / "rag_storage"),
        enable_image_processing=False,
    )
    rag = RAGAnything(
        config=config,
        llm_model_func=AsyncMock(return_value="mock answer"),
        embedding_func=AsyncMock(return_value=[0.1] * 1536),
    )

    with patch.object(
        rag, "insert_content_list", new=AsyncMock(return_value="doc-auto-123")
    ):
        content_list, doc_id = await rag.process_preprocessed_output(
            output_dir=temp_mineru_output
        )
        assert len(content_list) == 2
        assert doc_id is not None


@pytest.mark.asyncio
async def test_process_preprocessed_output_not_found(tmp_path):
    """Test process_preprocessed_output raises FileNotFoundError for nonexistent dir."""
    config = RAGAnythingConfig(working_dir=str(tmp_path / "rag_storage"))
    rag = RAGAnything(config=config)

    with pytest.raises(FileNotFoundError, match="Output directory does not exist"):
        await rag.process_preprocessed_output(output_dir=tmp_path / "nonexistent_dir")


@pytest.mark.asyncio
async def test_process_preprocessed_directory_batch(temp_batch_mineru_dir):
    """Test process_preprocessed_directory ingests all document folders in a directory."""
    config = RAGAnythingConfig(
        working_dir=str(temp_batch_mineru_dir.parent / "rag_storage"),
        enable_image_processing=False,
    )
    rag = RAGAnything(
        config=config,
        llm_model_func=AsyncMock(return_value="mock answer"),
        embedding_func=AsyncMock(return_value=[0.1] * 1536),
    )

    with patch.object(
        rag, "insert_content_list", new=AsyncMock(return_value="doc-batch-id")
    ) as mock_insert:
        results = await rag.process_preprocessed_directory(
            base_dir=temp_batch_mineru_dir
        )

        assert len(results) == 2
        names = [name for name, _ in results]
        assert "doc_alpha" in names
        assert "doc_beta" in names
        assert mock_insert.await_count == 2
