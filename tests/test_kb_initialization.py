import pytest

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
