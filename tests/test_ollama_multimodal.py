"""Tests for Ollama multimodal VLM integration (#57, #71, #72, #44).

Ensures that:
- ollama_vision_model_func constructs valid messages with image_url and MIME types for base64 strings
- ollama_vision_model_func handles local image file paths transparently
- ollama_vision_model_func forwards pre-constructed messages directly for VLM enhanced queries
- ollama_vision_model_func falls back to text LLM when no image or messages are provided
- OllamaRAGIntegration enables vision model wiring when enable_vision=True
"""

import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Ensure examples directory is importable
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from examples.ollama_integration_example import (
    OllamaRAGIntegration,
    ollama_vision_model_func,
)


@pytest.mark.asyncio
async def test_ollama_vision_model_func_with_base64_image_data():
    """ollama_vision_model_func must format base64 image_data into an image_url message."""
    # 1x1 PNG in base64
    sample_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    with patch(
        "examples.ollama_integration_example.openai_complete_if_cache",
        new_callable=AsyncMock,
    ) as mock_complete:
        mock_complete.return_value = '{"detailed_description": "A single dot", "entity_info": {"entity_name": "dot", "entity_type": "image", "summary": "test dot"}}'

        result = await ollama_vision_model_func(
            prompt="Analyze this diagram",
            system_prompt="You are an expert",
            image_data=sample_png_b64,
        )

        assert "A single dot" in result
        mock_complete.assert_called_once()
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["model"] == "llama3.2-vision"
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "You are an expert"}
        user_msg = messages[1]
        assert user_msg["role"] == "user"
        content_items = user_msg["content"]
        assert content_items[0] == {"type": "text", "text": "Analyze this diagram"}
        assert content_items[1]["type"] == "image_url"
        assert content_items[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_ollama_vision_model_func_with_image_path(tmp_path):
    """ollama_vision_model_func must load and base64-encode local image file paths."""
    sample_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img_file = tmp_path / "diagram.png"
    img_file.write_bytes(sample_png)

    with patch(
        "examples.ollama_integration_example.openai_complete_if_cache",
        new_callable=AsyncMock,
    ) as mock_complete:
        mock_complete.return_value = "Parsed image description"

        result = await ollama_vision_model_func(
            prompt="Describe this chart",
            image_data=str(img_file),
        )

        assert result == "Parsed image description"
        call_kwargs = mock_complete.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_ollama_vision_model_func_with_messages_forwarding():
    """ollama_vision_model_func must pass pre-constructed messages directly for VLM queries."""
    input_messages = [
        {"role": "system", "content": "System prompt"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Query text"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,1234"},
                },
            ],
        },
    ]

    with patch(
        "examples.ollama_integration_example.openai_complete_if_cache",
        new_callable=AsyncMock,
    ) as mock_complete:
        mock_complete.return_value = "Query answer based on image"

        result = await ollama_vision_model_func(
            prompt="",
            messages=input_messages,
        )

        assert result == "Query answer based on image"
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["messages"] == input_messages


@pytest.mark.asyncio
async def test_ollama_vision_model_func_text_fallback():
    """ollama_vision_model_func falls back to text LLM function when no image or messages are passed."""
    with patch(
        "examples.ollama_integration_example.openai_complete_if_cache",
        new_callable=AsyncMock,
    ) as mock_complete:
        mock_complete.return_value = "Text answer"

        result = await ollama_vision_model_func(prompt="Hello Ollama")

        assert result == "Text answer"
        call_kwargs = mock_complete.call_args[1]
        assert call_kwargs["prompt"] == "Hello Ollama"


def test_ollama_rag_integration_multimodal_wiring():
    """OllamaRAGIntegration must configure enable_image_processing based on enable_vision."""
    integration_text = OllamaRAGIntegration(enable_vision=False)
    assert integration_text.config.enable_image_processing is False

    integration_vision = OllamaRAGIntegration(enable_vision=True)
    assert integration_vision.config.enable_image_processing is True
