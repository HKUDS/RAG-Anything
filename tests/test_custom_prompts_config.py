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

    with pytest.raises(
        ValueError, match="Prompt template key must be a non-empty string"
    ):
        update_prompts({"": "value"})

    with pytest.raises(TypeError, match="must be a string"):
        update_prompts({"valid_key": 12345})  # type: ignore


def test_instance_prompt_priority_over_global_reset(tmp_path):
    """Test instance-scoped prompts retain custom configuration even after global reset."""
    custom_vision = "Instance private prompt: {entity_name}"
    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag_storage"),
        custom_prompts={"vision_prompt": custom_vision},
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=AsyncMock(return_value="mock answer"),
        embedding_func=AsyncMock(return_value=[0.1] * 1536),
    )

    # Reset global prompts
    reset_prompts()

    # Instance should still return its instance-scoped custom prompt
    assert rag.get_prompt("vision_prompt") == custom_vision


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
    assert get_prompt_language() == "en"
    from raganything.prompts_zh import PROMPTS_ZH

    assert rag.get_prompt("vision_prompt") == PROMPTS_ZH["vision_prompt"]


@pytest.mark.asyncio
async def test_private_prompts_reach_real_processors_without_global_leakage(tmp_path):
    import asyncio
    from unittest.mock import MagicMock
    from raganything.prompt import PROMPTS

    global_prompt = PROMPTS["table_prompt"]
    instances = []
    for tenant in ("A", "B"):
        model = AsyncMock(
            return_value='{"detailed_description":"table","entity_info":{"entity_name":"sales","entity_type":"table","summary":"sales"}}'
        )
        rag = RAGAnything(
            config=RAGAnythingConfig(
                working_dir=str(tmp_path / tenant),
                custom_prompts={"table_prompt": tenant + " {table_body}"},
            ),
            lightrag=MagicMock(),
            llm_model_func=model,
        )
        rag.finalize_storages = AsyncMock()
        rag._initialize_processors()
        instances.append((rag, model))
    await asyncio.gather(
        *(
            rag.modal_processors["table"].generate_description_only(
                {"table_body": "Revenue 42"}, "table"
            )
            for rag, _ in instances
        )
    )
    for tenant, (rag, model) in zip(("A", "B"), instances):
        assert model.call_args.args[0] == tenant + " Revenue 42"
        assert rag._prompt_templates["table_prompt"] == tenant + " {table_body}"
    instances[0][0].update_prompts({"table_prompt": "UPDATED {table_body}"})
    assert (
        instances[0][0].modal_processors["table"]._prompt_templates["table_prompt"]
        == "UPDATED {table_body}"
    )
    assert instances[1][0].get_prompt("table_prompt") == "B {table_body}"
    assert PROMPTS["table_prompt"] == global_prompt
