import pytest
from types import SimpleNamespace

import raganything.raganything as rag_module
from raganything.services import kb_service


class _InitializationFailure:
    lightrag = None

    def __init__(self):
        self.finalized = False

    async def _ensure_lightrag_initialized(self):
        return {"success": False, "error": "storage setup failed"}

    async def finalize_storages(self):
        self.finalized = True


@pytest.mark.asyncio
async def test_get_kb_does_not_cache_a_partially_initialized_instance(monkeypatch, tmp_path):
    instance = _InitializationFailure()
    cache = kb_service.KBCache()

    async def create_rag(*_args, **_kwargs):
        return instance

    monkeypatch.setattr(kb_service, "kb_instances", cache)
    monkeypatch.setattr(kb_service, "_kb_locks", {})
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: False)
    monkeypatch.setattr(kb_service, "kb_dir", lambda _name: str(tmp_path))
    monkeypatch.setattr(kb_service, "create_rag", create_rag)

    with pytest.raises(RuntimeError, match="storage setup failed"):
        await kb_service.get_kb("broken")

    assert "broken" not in cache
    assert instance.finalized is True


@pytest.mark.asyncio
async def test_query_core_initialization_defers_bm25_preparation(monkeypatch):
    class Engine:
        def __init__(self, **_kwargs):
            pass

        async def ensure_bm25_index(self):
            raise AssertionError("query-core initialization must not build BM25")

    async def init_vision_repo():
        return None

    rag = object.__new__(rag_module.RAGAnything)
    rag._parser_installation_checked = True
    rag.lightrag = SimpleNamespace(
        _storages_status=SimpleNamespace(name="INITIALIZED"),
        llm_model_func=object(),
        embedding_func=object(),
    )
    rag.llm_model_func = object()
    rag.embedding_func = object()
    rag.parse_cache = object()
    rag.multimodal_status_cache = object()
    rag.modal_processors = [object()]
    rag.hybrid_search_engine = None
    rag.vision_embed_func = None
    rag.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)
    rag._init_vision_repo = init_vision_repo
    monkeypatch.setattr(rag_module, "HybridSearchEngine", Engine)

    result = await rag._ensure_lightrag_initialized()

    assert result == {"success": True}
    assert isinstance(rag.hybrid_search_engine, Engine)
