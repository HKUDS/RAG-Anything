"""Exercise real RAGAnything initialization with controlled storage backends."""

import asyncio
import sys
import types
from collections import Counter

import pytest

import raganything.raganything as rag_module
from raganything.config import RAGAnythingConfig


def _make_rag(monkeypatch, tmp_path, *, preprovided, gate=None, failure=None):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = Counter()
    failures = [] if failure is None else [failure]
    instances = []

    async def initialize(namespace):
        calls[namespace] += 1
        if namespace == gate:
            entered.set()
            await release.wait()
        if failures and failures[0][0] == namespace:
            _namespace, exception = failures.pop()
            raise exception

    class Storage:
        def __init__(self, namespace, **kwargs):
            self.namespace = namespace
            self.ready = False
            instances.append(self)

        async def initialize(self):
            await initialize(self.namespace)
            self.ready = True

        async def get_by_id(self, key):
            if not self.ready:
                raise RuntimeError("storage used before initialization")
            return {"id": key}

    class LightRAG:
        def __init__(self, **kwargs):
            self.workspace = "test"
            self.llm_model_func = kwargs.get("llm_model_func", lambda: None)
            self.embedding_func = kwargs.get("embedding_func", lambda: None)
            self._storages_status = types.SimpleNamespace(name="CREATED")
            self.key_string_value_json_storage_cls = Storage

        async def initialize_storages(self):
            await initialize("lightrag")
            self._storages_status.name = "INITIALIZED"

    async def initialize_pipeline_status():
        pass

    shared_storage = types.ModuleType("lightrag.kg.shared_storage")
    shared_storage.initialize_pipeline_status = initialize_pipeline_status
    monkeypatch.setitem(sys.modules, "lightrag.kg.shared_storage", shared_storage)
    monkeypatch.setattr(rag_module, "LightRAG", LightRAG)
    monkeypatch.setattr(
        rag_module,
        "get_parser",
        lambda _name: types.SimpleNamespace(check_installation=lambda: True),
    )
    monkeypatch.setattr(rag_module.atexit, "register", lambda *args: None)

    def initialize_processors(self):
        calls["processors"] += 1
        self.modal_processors = {"test": object()}

    monkeypatch.setattr(
        rag_module.RAGAnything, "_initialize_processors", initialize_processors
    )
    rag = rag_module.RAGAnything(
        config=RAGAnythingConfig(working_dir=str(tmp_path / "rag")),
        lightrag=LightRAG() if preprovided else None,
        llm_model_func=lambda: None,
        embedding_func=lambda: None,
    )
    return rag, entered, release, calls, instances


@pytest.mark.asyncio
@pytest.mark.parametrize("preprovided", [False, True])
@pytest.mark.parametrize("gate", ["lightrag", "parse_cache", "multimodal_status"])
async def test_concurrent_initialization_waits_for_ready_storages(
    monkeypatch, tmp_path, preprovided, gate
):
    rag, entered, release, calls, instances = _make_rag(
        monkeypatch, tmp_path, preprovided=preprovided, gate=gate
    )
    first = asyncio.create_task(rag._ensure_lightrag_initialized())
    await asyncio.wait_for(entered.wait(), timeout=1)
    second = asyncio.create_task(rag._ensure_lightrag_initialized())
    try:
        # Let the second caller reach the initialization boundary while the
        # backend is still blocked; no wall-clock sleeps or timing race needed.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert (
            not second.done()
        ), "a concurrent caller returned before storage was ready"
    finally:
        release.set()
        results = await asyncio.gather(first, second)

    assert results == [{"success": True}, {"success": True}]
    assert calls == Counter(
        lightrag=1, parse_cache=1, multimodal_status=1, processors=1
    )
    assert len(instances) == 2
    assert await rag.parse_cache.get_by_id("test") == {"id": "test"}
    assert await rag.multimodal_status_cache.get_by_id("test") == {"id": "test"}


@pytest.mark.asyncio
@pytest.mark.parametrize("preprovided", [False, True])
@pytest.mark.parametrize("namespace", ["parse_cache", "multimodal_status"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_cache_initialization_is_retried(
    monkeypatch, tmp_path, preprovided, namespace, cancelled
):
    exception = asyncio.CancelledError() if cancelled else RuntimeError("backend down")
    rag, _entered, _release, calls, instances = _make_rag(
        monkeypatch,
        tmp_path,
        preprovided=preprovided,
        failure=(namespace, exception),
    )

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await rag._ensure_lightrag_initialized()
    else:
        result = await rag._ensure_lightrag_initialized()
        assert result["success"] is False
        assert "backend down" in result["error"]

    result = await rag._ensure_lightrag_initialized()
    assert result == {"success": True}
    assert calls[namespace] == 2
    assert sum(not instance.ready for instance in instances) == 1
    assert await rag.parse_cache.get_by_id("test") == {"id": "test"}
    assert await rag.multimodal_status_cache.get_by_id("test") == {"id": "test"}
    # Repeated calls after recovery must reuse both initialized caches.
    assert await rag._ensure_lightrag_initialized() == {"success": True}
    assert calls[namespace] == 2
    assert calls["processors"] == 1
