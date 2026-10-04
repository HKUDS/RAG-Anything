"""
Unit tests for the Cheaper Inference integration example.

Tests verify:
- Default configuration values
- Base URL and model name handling
- LLM function parameter passing

These tests are self-contained and do not require lightrag or raganything
to be installed — heavy dependencies are mocked at the sys.modules level.
"""

import os
import sys
import types
import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Lightweight stubs so we can import the example without heavy deps
# ---------------------------------------------------------------------------


def _make_stub_modules():
    """Create minimal stub modules for lightrag and raganything."""
    # lightrag stub
    lightrag_mod = types.ModuleType("lightrag")
    lightrag_llm = types.ModuleType("lightrag.llm")
    lightrag_llm_openai = types.ModuleType("lightrag.llm.openai")
    lightrag_llm_openai.openai_complete_if_cache = AsyncMock(return_value="stub")
    lightrag_llm_openai.openai_embed = AsyncMock(return_value=[[0.1, 0.2]])
    lightrag_utils = types.ModuleType("lightrag.utils")

    class _EmbeddingFunc:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    lightrag_utils.EmbeddingFunc = _EmbeddingFunc
    lightrag_mod.llm = lightrag_llm
    lightrag_mod.utils = lightrag_utils

    # raganything stub
    rag_mod = types.ModuleType("raganything")

    class _RAGAnythingConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _RAGAnything:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    rag_mod.RAGAnything = _RAGAnything
    rag_mod.RAGAnythingConfig = _RAGAnythingConfig

    return {
        "lightrag": lightrag_mod,
        "lightrag.llm": lightrag_llm,
        "lightrag.llm.openai": lightrag_llm_openai,
        "lightrag.utils": lightrag_utils,
        "raganything": rag_mod,
    }


def _load_example(extra_env=None):
    """Load the example module with stubs injected and optional env overrides."""
    import importlib.util
    from pathlib import Path

    module_path = (
        Path(__file__).parent.parent
        / "examples"
        / "cheaperinference_integration_example.py"
    )

    env = {
        "CHEAPER_INFERENCE_API_KEY": "test-key",
        "CHEAPER_INFERENCE_BASE_URL": "https://api.cheaperinference.com/v1",
        "CHEAPER_INFERENCE_LLM_MODEL": "gpt-5.4-mini",
        "EMBEDDING_BINDING_HOST": "https://api.openai.com/v1",
        "EMBEDDING_BINDING_API_KEY": "test-embed-key",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_DIM": "1536",
    }
    if extra_env:
        env.update(extra_env)

    stubs = _make_stub_modules()

    # Remove cached module if present
    for key in list(sys.modules.keys()):
        if key == "cheaperinference_integration_example":
            del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        "cheaperinference_integration_example", module_path
    )
    mod = importlib.util.module_from_spec(spec)

    with (
        patch.dict(os.environ, env, clear=False),
        patch.dict(sys.modules, stubs, clear=False),
        patch("dotenv.load_dotenv"),
    ):
        spec.loader.exec_module(mod)

    return mod, stubs


# ---------------------------------------------------------------------------
# Module-level constant tests
# ---------------------------------------------------------------------------


class TestCheaperInferenceConstants:
    """Verify module-level defaults resolve correctly from environment."""

    def test_default_base_url(self):
        # os.getenv default is used only when the var is absent, not when it is ""
        env = {
            k: v
            for k, v in {
                "CHEAPER_INFERENCE_API_KEY": "test-key",
                "CHEAPER_INFERENCE_LLM_MODEL": "gpt-5.4-mini",
                "EMBEDDING_BINDING_HOST": "https://api.openai.com/v1",
                "EMBEDDING_BINDING_API_KEY": "test-embed-key",
                "EMBEDDING_MODEL": "text-embedding-3-small",
                "EMBEDDING_DIM": "1536",
            }.items()
        }
        with patch.dict(os.environ, env, clear=True):
            mod, _ = _load_example()
        assert mod.CHEAPER_INFERENCE_BASE_URL == "https://api.cheaperinference.com/v1"

    def test_default_model(self):
        env = {
            k: v
            for k, v in {
                "CHEAPER_INFERENCE_API_KEY": "test-key",
                "CHEAPER_INFERENCE_BASE_URL": "https://api.cheaperinference.com/v1",
                "EMBEDDING_BINDING_HOST": "https://api.openai.com/v1",
                "EMBEDDING_BINDING_API_KEY": "test-embed-key",
                "EMBEDDING_MODEL": "text-embedding-3-small",
                "EMBEDDING_DIM": "1536",
            }.items()
        }
        with patch.dict(os.environ, env, clear=True):
            mod, _ = _load_example()
        assert mod.CHEAPER_INFERENCE_LLM_MODEL == "gpt-5.4-mini"

    def test_custom_model_env(self):
        mod, _ = _load_example({"CHEAPER_INFERENCE_LLM_MODEL": "claude-sonnet-5"})
        assert mod.CHEAPER_INFERENCE_LLM_MODEL == "claude-sonnet-5"

    def test_api_key_read_from_env(self):
        mod, _ = _load_example({"CHEAPER_INFERENCE_API_KEY": "sk-custom-123"})
        assert mod.CHEAPER_INFERENCE_API_KEY == "sk-custom-123"

    def test_embedding_dim_read_from_env(self):
        mod, _ = _load_example({"EMBEDDING_DIM": "3072"})
        assert mod.EMBEDDING_DIM == 3072


# ---------------------------------------------------------------------------
# LLM function parameter tests
# ---------------------------------------------------------------------------


class TestCheaperInferenceLLMFunc:
    """Verify correct parameters are passed to openai_complete_if_cache."""

    @pytest.mark.asyncio
    async def test_correct_base_url(self):
        mod, _ = _load_example()
        captured = {}

        async def mock_complete(model, prompt, **kwargs):
            captured.update(kwargs)
            return "response"

        mod.openai_complete_if_cache = mock_complete
        await mod.cheaperinference_llm_model_func("test")
        assert captured["base_url"] == "https://api.cheaperinference.com/v1"

    @pytest.mark.asyncio
    async def test_correct_model_name(self):
        mod, _ = _load_example()
        captured = {}

        async def mock_complete(model, prompt, **kwargs):
            captured["model"] = model
            return "response"

        mod.openai_complete_if_cache = mock_complete
        await mod.cheaperinference_llm_model_func("test")
        assert captured["model"] == "gpt-5.4-mini"

    @pytest.mark.asyncio
    async def test_system_prompt_passed_through(self):
        mod, _ = _load_example()
        captured = {}

        async def mock_complete(model, prompt, **kwargs):
            captured.update(kwargs)
            return "response"

        mod.openai_complete_if_cache = mock_complete
        await mod.cheaperinference_llm_model_func(
            "user msg", system_prompt="Be concise."
        )
        assert captured["system_prompt"] == "Be concise."

    @pytest.mark.asyncio
    async def test_history_messages_defaults_to_empty(self):
        mod, _ = _load_example()
        captured = {}

        async def mock_complete(model, prompt, **kwargs):
            captured.update(kwargs)
            return "response"

        mod.openai_complete_if_cache = mock_complete
        await mod.cheaperinference_llm_model_func("test")
        assert captured["history_messages"] == []

    @pytest.mark.asyncio
    async def test_api_key_passed(self):
        mod, _ = _load_example({"CHEAPER_INFERENCE_API_KEY": "sk-secret"})
        captured = {}

        async def mock_complete(model, prompt, **kwargs):
            captured.update(kwargs)
            return "response"

        mod.openai_complete_if_cache = mock_complete
        mod.CHEAPER_INFERENCE_API_KEY = "sk-secret"
        await mod.cheaperinference_llm_model_func("test")
        assert captured["api_key"] == "sk-secret"

    @pytest.mark.asyncio
    async def test_missing_cheaperinference_api_key_raises_before_openai_fallback(self):
        mod, _ = _load_example({"CHEAPER_INFERENCE_API_KEY": ""})
        mod.openai_complete_if_cache = AsyncMock()

        with pytest.raises(ValueError, match="CHEAPER_INFERENCE_API_KEY is required"):
            await mod.cheaperinference_llm_model_func("test")

        mod.openai_complete_if_cache.assert_not_awaited()


# ---------------------------------------------------------------------------
# Integration class tests
# ---------------------------------------------------------------------------


class TestCheaperInferenceRAGIntegration:
    """Tests for the CheaperInferenceRAGIntegration helper class."""

    def test_default_model_name(self):
        mod, _ = _load_example()
        integration = mod.CheaperInferenceRAGIntegration()
        assert integration.model_name == "gpt-5.4-mini"

    def test_default_base_url(self):
        mod, _ = _load_example()
        integration = mod.CheaperInferenceRAGIntegration()
        assert integration.base_url == "https://api.cheaperinference.com/v1"

    def test_config_is_created(self):
        mod, _ = _load_example()
        integration = mod.CheaperInferenceRAGIntegration()
        assert integration.config is not None

    def test_rag_starts_as_none(self):
        mod, _ = _load_example()
        integration = mod.CheaperInferenceRAGIntegration()
        assert integration.rag is None

    @pytest.mark.asyncio
    async def test_connection_fails_without_api_key(self):
        mod, _ = _load_example()
        integration = mod.CheaperInferenceRAGIntegration()
        integration.api_key = ""
        result = await integration.test_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_succeeds_when_models_endpoint_is_missing(self):
        mod, _ = _load_example()

        class _Models:
            async def list(self):
                raise RuntimeError("models endpoint unavailable")

        class _AsyncOpenAI:
            def __init__(self, base_url, api_key):
                self.base_url = base_url
                self.api_key = api_key
                self.models = _Models()
                self.closed = False

            async def close(self):
                self.closed = True

        openai_mod = types.ModuleType("openai")
        openai_mod.AsyncOpenAI = _AsyncOpenAI

        with patch.dict(sys.modules, {"openai": openai_mod}):
            integration = mod.CheaperInferenceRAGIntegration()
            result = await integration.test_connection()

        assert result is True
