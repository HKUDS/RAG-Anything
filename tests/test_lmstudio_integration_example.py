from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path


def _load_example(monkeypatch):
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None

    openai = types.ModuleType("openai")
    openai.AsyncOpenAI = object

    raganything = types.ModuleType("raganything")
    raganything.RAGAnything = object
    raganything.RAGAnythingConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)

    lightrag = types.ModuleType("lightrag")
    lightrag_utils = types.ModuleType("lightrag.utils")
    lightrag_utils.EmbeddingFunc = object
    lightrag_llm = types.ModuleType("lightrag.llm")
    lightrag_openai = types.ModuleType("lightrag.llm.openai")
    lightrag_openai.openai_complete_if_cache = object()

    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "openai", openai)
    monkeypatch.setitem(sys.modules, "raganything", raganything)
    monkeypatch.setitem(sys.modules, "lightrag", lightrag)
    monkeypatch.setitem(sys.modules, "lightrag.utils", lightrag_utils)
    monkeypatch.setitem(sys.modules, "lightrag.llm", lightrag_llm)
    monkeypatch.setitem(sys.modules, "lightrag.llm.openai", lightrag_openai)

    module_path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "lmstudio_integration_example.py"
    )
    spec = importlib.util.spec_from_file_location(
        "lmstudio_integration_example", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_model_discovery_failure_does_not_skip_chat_health_check(monkeypatch, capsys):
    module = _load_example(monkeypatch)

    class Models:
        async def list(self):
            raise RuntimeError("/models is unavailable")

    class Client:
        instances = []

        def __init__(self, **kwargs):
            self.models = Models()
            self.closed = False
            self.kwargs = kwargs
            self.instances.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(module, "AsyncOpenAI", Client)
    integration = module.LMStudioRAGIntegration()

    assert asyncio.run(integration.test_connection()) is True
    assert Client.instances[0].closed is True
    output = capsys.readouterr().out
    assert "Model discovery unavailable" in output
    assert "chat completion will verify" in output
