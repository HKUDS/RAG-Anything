"""VLM queries must preserve LightRAG's context-only and prompt-only contract."""

import base64
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lightrag import QueryParam

import raganything.query as query_module
from raganything.query import QueryMixin


class _QueryHarness(QueryMixin):
    def __init__(self, image_path):
        self.logger = logging.getLogger(__name__)
        self.config = SimpleNamespace(
            working_dir=str(image_path.parent),
            parser_output_dir=str(image_path.parent),
        )
        self.context = f"Retrieved context\nImage Path: {image_path}"
        self.prompt = f"Answer using this context:\n{self.context}"
        self.query_calls = []
        self.vision_calls = []
        self.lightrag = SimpleNamespace(aquery=self._retrieve)
        self.vision_model_func = self._vision

    async def _ensure_lightrag_initialized(self):
        return {"success": True}

    async def _retrieve(self, query, param, system_prompt=None):
        assert isinstance(param, QueryParam)
        self.query_calls.append((query, param, system_prompt))
        # LightRAG gives only_need_prompt precedence when both flags are true.
        if param.only_need_prompt:
            return self.prompt
        if param.only_need_context:
            return self.context
        return "text answer"

    async def _vision(self, prompt, **kwargs):
        self.vision_calls.append((prompt, kwargs))
        return "vision answer"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        )
    )
    result = _QueryHarness(image_path)
    result.encode_image = Mock(wraps=query_module.encode_image_to_base64)
    monkeypatch.setattr(query_module, "encode_image_to_base64", result.encode_image)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["aquery", "aquery_vlm_enhanced"])
@pytest.mark.parametrize(
    "flags",
    [
        {"only_need_context": True},
        {"only_need_prompt": True},
        {"only_need_context": True, "only_need_prompt": True},
    ],
)
async def test_retrieval_only_returns_unmodified_lightrag_result(
    harness, entrypoint, flags
):
    result = await getattr(harness, entrypoint)(
        "Describe the figure",
        mode="hybrid",
        system_prompt="Use the supplied context: {context_data}",
        top_k=7,
        **flags,
    )

    expected = harness.prompt if flags.get("only_need_prompt") else harness.context
    assert result == expected
    assert len(harness.query_calls) == 1
    query, param, system_prompt = harness.query_calls[0]
    assert query == "Describe the figure"
    assert param.mode == "hybrid"
    assert param.top_k == 7
    assert param.only_need_context == flags.get("only_need_context", False)
    assert param.only_need_prompt == flags.get("only_need_prompt", False)
    assert system_prompt == "Use the supplied context: {context_data}"
    harness.encode_image.assert_not_called()
    assert harness.vision_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["aquery", "aquery_vlm_enhanced"])
@pytest.mark.parametrize(
    "flags",
    [{}, {"only_need_prompt": False, "only_need_context": False}],
)
async def test_answer_queries_still_send_retrieved_images_to_vision(
    harness, entrypoint, flags
):
    result = await getattr(harness, entrypoint)("Describe the figure", **flags)

    assert result == "vision answer"
    assert len(harness.query_calls) == 1
    assert harness.query_calls[0][1].only_need_prompt is True
    harness.encode_image.assert_called_once()
    assert len(harness.vision_calls) == 1
    messages = harness.vision_calls[0][1]["messages"]
    assert any(part["type"] == "image_url" for part in messages[1]["content"])


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["aquery", "aquery_vlm_enhanced"])
async def test_explicit_false_flags_preserve_text_fallback(harness, entrypoint):
    harness.prompt = "Retrieved prompt without images"

    result = await getattr(harness, entrypoint)(
        "Describe the document",
        only_need_prompt=False,
        only_need_context=False,
        system_prompt="Use the supplied context: {context_data}",
    )

    assert result == "text answer"
    assert len(harness.query_calls) == 2
    assert harness.query_calls[0][1].only_need_prompt is True
    _, final_param, system_prompt = harness.query_calls[1]
    assert final_param.only_need_prompt is False
    assert final_param.only_need_context is False
    assert system_prompt == "Use the supplied context: {context_data}"
    harness.encode_image.assert_not_called()
    assert harness.vision_calls == []
