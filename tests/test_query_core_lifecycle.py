import pytest

import raganything.services.kb_service as kb_service
from raganything.services.kb_service import KBCache, KBInstanceKey


class _Core:
    __hash__ = None

    def __init__(self):
        self.finalize_calls = 0
        self.finalize_kwargs = []

    async def finalize_storages(self, **kwargs):
        self.finalize_calls += 1
        self.finalize_kwargs.append(kwargs)


def _key(revision: str) -> KBInstanceKey:
    return KBInstanceKey("kb", "workspace", revision, "vision-fingerprint")


@pytest.mark.asyncio
async def test_revision_replacement_retires_a_leased_core_until_release():
    cache = KBCache(max_size=1)
    old_core = _Core()
    next_core = _Core()

    await cache.put_and_evict("kb", old_core, 1.0, key=_key("revision-1"))
    cache.acquire_query_lease("kb", old_core)

    await cache.put_and_evict("kb", next_core, 2.0, key=_key("revision-2"))

    assert cache.get("kb") is next_core
    assert old_core.finalize_calls == 0
    assert cache.get_stats()["retiring_query_cores"] == 1

    await cache.release_query_lease("kb", old_core)

    assert old_core.finalize_calls == 1
    assert next_core.finalize_calls == 0
    assert cache.get_stats()["retiring_query_cores"] == 0


@pytest.mark.asyncio
async def test_deletion_gate_rejects_new_leases_and_waits_for_active_lease():
    cache = KBCache(max_size=1)
    core = _Core()
    await cache.put_and_evict("kb", core, 1.0, key=_key("revision-1"))
    cache.acquire_query_lease("kb", core)

    cache.begin_deletion("kb")
    with pytest.raises(RuntimeError, match="kb_query_deleting"):
        cache.acquire_query_lease("kb", core)
    assert not await cache.wait_for_no_query_leases("kb", 0.01)

    await cache.release_query_lease("kb", core)
    assert await cache.wait_for_no_query_leases("kb", 0.1)
    cache.cancel_deletion("kb")


@pytest.mark.asyncio
async def test_worker_cache_retirement_discards_file_vdb_persistence():
    cache = KBCache(max_size=1)
    core = _Core()
    await cache.put_and_evict("kb", core, 1.0, key=_key("revision-1"))

    await cache.retire("kb", persist_vector_stores=False)

    assert core.finalize_kwargs == [{"persist_vector_stores": False}]


@pytest.mark.asyncio
async def test_normal_cache_retirement_keeps_default_persistence():
    cache = KBCache(max_size=1)
    core = _Core()
    await cache.put_and_evict("kb", core, 1.0, key=_key("revision-1"))

    await cache.retire("kb")

    assert core.finalize_kwargs == [{}]


@pytest.mark.asyncio
async def test_acquire_query_kb_forwards_refreshed_corpus_revision(monkeypatch):
    replacement = _Core()
    captured = {}

    async def get_kb(name, **kwargs):
        captured["name"] = name
        captured.update(kwargs)
        return replacement

    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(kb_service, "active_kb", "default")
    monkeypatch.setattr(
        kb_service.kb_instances,
        "get_instance_key",
        lambda _name: _key("revision-2"),
    )

    lease = await kb_service.acquire_query_kb("kb", corpus_revision="revision-2")

    assert lease.instance is replacement
    assert lease.key == _key("revision-2")
    assert lease.cache_status == "hit"
    assert captured == {
        "name": "kb",
        "corpus_revision": "revision-2",
        "acquire_query_lease": True,
    }


@pytest.mark.asyncio
async def test_acquire_query_kb_records_a_miss_when_it_publishes_a_new_key(monkeypatch):
    replacement = _Core()
    keys = [None, _key("revision-3")]

    async def get_kb(*_args, **_kwargs):
        return replacement

    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(
        kb_service.kb_instances,
        "get_instance_key",
        lambda _name: keys.pop(0),
    )

    lease = await kb_service.acquire_query_kb("kb", corpus_revision="revision-3")

    assert lease.cache_status == "miss"


@pytest.mark.asyncio
async def test_task_bound_ingestion_keeps_uncached_instance_lifecycle(monkeypatch):
    created = []

    class TaskCore(_Core):
        async def _ensure_lightrag_initialized(self):
            return {"success": True}

    async def create_rag(**kwargs):
        created.append(kwargs)
        return TaskCore()

    monkeypatch.setattr(kb_service, "create_rag", create_rag)
    monkeypatch.setattr(kb_service, "kb_dir", lambda _name: "workspace")
    async def load_meta():
        return {}

    monkeypatch.setattr(kb_service, "load_kb_meta", load_meta)

    first = await kb_service.get_kb("kb", task_settings={"revision": 1})
    second = await kb_service.get_kb("kb", task_settings={"revision": 1})

    assert first is not second
    assert len(created) == 2
    assert "kb" not in kb_service.kb_instances
