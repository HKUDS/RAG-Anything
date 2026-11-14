from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raganything.config import RAGAnythingConfig
from raganything.raganything import RAGAnything


def test_extract_multimodal_citations():
    """Test extracting image and table image citations from context text."""
    config = RAGAnythingConfig()
    rag = RAGAnything(config=config)

    text = """
    Here is an analysis:
    Image Path: /workspace/images/chart.png
    Some explanation here.
    Table Image Path: /workspace/images/table1.png
    Image Path: /workspace/images/chart.png  # duplicate should be deduplicated
    image_path: /workspace/images/photo.jpg
    """

    citations = rag.extract_multimodal_citations(text)
    assert len(citations) == 3
    paths = [c["path"] for c in citations]
    assert "/workspace/images/chart.png" in paths
    assert "/workspace/images/table1.png" in paths
    assert "/workspace/images/photo.jpg" in paths

    types = {c["path"]: c["type"] for c in citations}
    assert types["/workspace/images/chart.png"] == "image"
    assert types["/workspace/images/table1.png"] == "table_image"


@pytest.mark.asyncio
async def test_aquery_default_returns_string(tmp_path):
    """Test that default return_multimodal_context=False returns plain string."""
    config = RAGAnythingConfig(working_dir=str(tmp_path / "rag_storage"))
    mock_lightrag = MagicMock()
    mock_lightrag.aquery = AsyncMock(return_value="Plain text answer.")

    rag = RAGAnything(
        config=config,
        lightrag=mock_lightrag,
        llm_model_func=AsyncMock(return_value="mock answer"),
    )
    rag.finalize_storages = AsyncMock()
    rag.vision_model_func = None  # disable VLM path

    result = await rag.aquery("What is the revenue?")
    assert isinstance(result, str)
    assert result == "Plain text answer."


@pytest.mark.asyncio
async def test_aquery_return_multimodal_context(tmp_path):
    """Test that return_multimodal_context=True returns dictionary with response and citations."""
    config = RAGAnythingConfig(working_dir=str(tmp_path / "rag_storage"))
    mock_lightrag = MagicMock()
    answer_text = "Revenue grew 20% as shown in Image Path: /data/output/growth.png"
    mock_lightrag.aquery = AsyncMock(return_value=answer_text)

    rag = RAGAnything(
        config=config,
        lightrag=mock_lightrag,
        llm_model_func=AsyncMock(return_value="mock answer"),
    )
    rag.finalize_storages = AsyncMock()
    rag.vision_model_func = None  # disable VLM path

    result = await rag.aquery("What is the revenue?", return_multimodal_context=True)
    assert isinstance(result, dict)
    assert result["response"] == answer_text
    assert len(result["multimodal_context"]) == 1
    assert result["multimodal_context"][0]["path"] == "/data/output/growth.png"
    assert result["multimodal_context"][0]["type"] == "image"


@pytest.mark.asyncio
async def test_aquery_vlm_enhanced_return_multimodal_context(tmp_path):
    """Test that aquery_vlm_enhanced with return_multimodal_context=True returns images."""
    config = RAGAnythingConfig(working_dir=str(tmp_path / "rag_storage"))
    mock_lightrag = MagicMock()

    rag = RAGAnything(
        config=config,
        lightrag=mock_lightrag,
        llm_model_func=AsyncMock(return_value="mock answer"),
        vision_model_func=AsyncMock(return_value="VLM answer about the chart."),
    )
    rag.finalize_storages = AsyncMock()

    async def mock_process_images(*args, **kwargs):
        rag._current_retrieved_images = ["/safe/img1.png"]
        return ("Prompt with [VLM_IMAGE_1]", 1)

    with (
        patch.object(
            rag, "_ensure_lightrag_initialized", return_value={"success": True}
        ),
        patch.object(
            mock_lightrag,
            "aquery",
            new=AsyncMock(return_value="Context with Image Path: /safe/img1.png"),
        ),
        patch.object(
            rag,
            "_process_image_paths_for_vlm",
            side_effect=mock_process_images,
        ),
        patch.object(
            rag,
            "_build_vlm_messages_with_images",
            return_value=[{"role": "user", "content": "..."}],
        ),
        patch.object(
            rag,
            "_call_vlm_with_multimodal_content",
            new=AsyncMock(return_value="VLM answer about the chart."),
        ),
    ):
        result = await rag.aquery_vlm_enhanced(
            "Explain chart",
            return_multimodal_context=True,
        )

        assert isinstance(result, dict)
        assert result["response"] == "VLM answer about the chart."
        assert len(result["multimodal_context"]) == 1
        assert result["multimodal_context"][0]["path"] == "/safe/img1.png"
