from unittest.mock import AsyncMock

import pytest

from raganything.config import RAGAnythingConfig
from raganything.prompt_manager import (
    get_prompt,
    get_prompt_language,
    reset_prompts,
    update_prompts,
)
from raganything.raganything import RAGAnything


@pytest.fixture(autouse=True)
def clean_prompts():
    """Ensure prompts are reset to defaults after each test."""
    yield
    reset_prompts()


def test_update_prompts_direct():
    """Test updating prompts directly via update_prompts."""
    original_vision = get_prompt("vision_prompt")
    assert original_vision is not None

    custom = "Analyze this custom image: {entity_name}"
    update_prompts({"vision_prompt": custom})
    assert get_prompt("vision_prompt") == custom

    reset_prompts()
    assert get_prompt("vision_prompt") == original_vision


def test_update_prompts_invalid_type():
    """Test update_prompts raises TypeError for non-dict input."""
    with pytest.raises(TypeError, match="custom_prompts must be a dict"):
        update_prompts("not a dict")


def test_raganything_config_custom_prompts(tmp_path):
    """Test RAGAnything initializes with custom_prompts from config."""
    custom_vision = "Domain-specific medical prompt: {entity_name}"
    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag_storage"),
        custom_prompts={"vision_prompt": custom_vision},
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=AsyncMock(return_value="mock answer"),
        embedding_func=AsyncMock(return_value=[0.1] * 1536),
    )

    assert rag.get_prompt("vision_prompt") == custom_vision

    # Test runtime update via instance method
    custom_table = "Domain-specific table prompt: {entity_name}"
    rag.update_prompts({"table_prompt": custom_table})
    assert rag.get_prompt("table_prompt") == custom_table


def test_raganything_config_prompt_language(tmp_path):
    """Test RAGAnything sets prompt language from config."""
    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag_storage"),
        prompt_language="zh",
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=AsyncMock(return_value="mock answer"),
        embedding_func=AsyncMock(return_value=[0.1] * 1536),
    )

    assert rag.config.prompt_language == "zh"
    assert get_prompt_language() == "zh"
