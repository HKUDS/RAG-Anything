import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raganything.routers import admin
from raganything.query_cache import get_query_cache


@pytest.fixture(autouse=True)
def isolate_runtime_settings_file(monkeypatch, tmp_path):
    runtime_file = tmp_path / 'runtime_settings.json'
    monkeypatch.setenv('RUNTIME_SETTINGS_FILE', str(runtime_file))
    monkeypatch.setattr(admin.runtime_settings, '_BOOTSTRAP_DONE', True)
    monkeypatch.setattr(
        admin.runtime_settings,
        '_BOOT_DEFAULTS',
        admin.runtime_settings.snapshot_current_settings(),
    )
    yield runtime_file
    monkeypatch.setattr(admin.runtime_settings, '_BOOT_DEFAULTS', None)
    monkeypatch.setattr(admin.runtime_settings, '_BOOTSTRAP_DONE', False)


@pytest.mark.asyncio
async def test_legacy_settings_mutations_are_disabled_without_side_effects(monkeypatch):
    cache = get_query_cache()
    cache.invalidate()
    cache.set("cached question", {"answer": "old"})
    kb_instance = object()
    monkeypatch.setattr(admin.shared, "kb_instances", {"demo": kb_instance})
    monkeypatch.setenv("LLM_MODEL", "unchanged-model")

    with pytest.raises(admin.HTTPException) as update_error:
        await admin.update_settings(
            admin.SettingsUpdate(llm_model="new-model", rrf_k=80),
            current_user={"id": 1},
        )
    with pytest.raises(admin.HTTPException) as reset_error:
        await admin.reset_settings(current_user={"id": 1})

    assert update_error.value.status_code == 410
    assert update_error.value.detail["code"] == "settings_write_deprecated"
    assert reset_error.value.status_code == 410
    assert reset_error.value.detail["code"] == "settings_reset_deprecated"
    assert os.environ["LLM_MODEL"] == "unchanged-model"
    assert admin.shared.kb_instances == {"demo": kb_instance}
    assert cache.get("cached question") == {"answer": "old"}


def test_serialize_settings_uses_default_for_blank_bm25_tokenizer(monkeypatch):
    monkeypatch.setenv("BM25_TOKENIZER", "")

    settings = admin._serialize_settings()

    assert settings["rrf"]["bm25_tokenizer"] == "jieba"


def test_runtime_settings_persist_across_restart(monkeypatch, tmp_path):
    runtime_file = tmp_path / 'runtime_settings.json'
    monkeypatch.setenv('RUNTIME_SETTINGS_FILE', str(runtime_file))
    monkeypatch.setenv('LLM_MODEL', 'boot-model')
    monkeypatch.setenv('MAX_ASYNC', '4')
    monkeypatch.setenv('RRF_K', '60')

    admin.runtime_settings._BOOT_DEFAULTS = {
        'parser': 'docling',
        'entity_types': '',
        'entity_extraction_min_degree': 0,
        'llm_model': 'boot-model',
        'chunk_size': 800,
        'chunking_strategy': 'recursive',
        'max_async': 4,
        'llm_timeout': 180,
        'enable_image': True,
        'enable_table': True,
        'enable_equation': True,
        'enable_video': False,
        'rrf': {
            'rrf_k': 60,
            'bm25_top_k': 50,
            'vector_top_k': 100,
            'graph_top_k': 30,
            'graph_depth': 2,
            'bm25_k1': 1.5,
            'bm25_b': 0.75,
            'bm25_tokenizer': 'jieba',
            'rrf_channel_timeout': 0.15,
            'enabled_channels': 'bm25,vector,graph',
        },
    }
    admin.runtime_settings._BOOTSTRAP_DONE = True

    os.environ['LLM_MODEL'] = 'persisted-model'
    os.environ['MAX_ASYNC'] = '9'
    os.environ['RRF_K'] = '77'
    overrides = admin.runtime_settings.sync_persisted_settings_from_env()

    assert overrides['llm_model'] == 'persisted-model'
    assert overrides['max_async'] == 9
    assert overrides['rrf']['rrf_k'] == 77
    assert runtime_file.exists()

    os.environ['LLM_MODEL'] = 'boot-model'
    os.environ['MAX_ASYNC'] = '4'
    os.environ['RRF_K'] = '60'
    admin.runtime_settings.apply_persisted_settings()

    assert os.environ['LLM_MODEL'] == 'persisted-model'
    assert os.environ['MAX_ASYNC'] == '9'
    assert os.environ['RRF_K'] == '77'


def test_runtime_settings_clear_file_when_restored_to_boot_defaults(monkeypatch, tmp_path):
    runtime_file = tmp_path / 'runtime_settings.json'
    monkeypatch.setenv('RUNTIME_SETTINGS_FILE', str(runtime_file))
    admin.runtime_settings._BOOT_DEFAULTS = {
        'parser': 'docling',
        'entity_types': '',
        'entity_extraction_min_degree': 0,
        'llm_model': 'boot-model',
        'chunk_size': 800,
        'chunking_strategy': 'recursive',
        'max_async': 4,
        'llm_timeout': 180,
        'enable_image': True,
        'enable_table': True,
        'enable_equation': True,
        'enable_video': False,
        'rrf': {
            'rrf_k': 60,
            'bm25_top_k': 50,
            'vector_top_k': 100,
            'graph_top_k': 30,
            'graph_depth': 2,
            'bm25_k1': 1.5,
            'bm25_b': 0.75,
            'bm25_tokenizer': 'jieba',
            'rrf_channel_timeout': 0.15,
            'enabled_channels': 'bm25,vector,graph',
        },
    }
    admin.runtime_settings._BOOTSTRAP_DONE = True

    monkeypatch.setenv('LLM_MODEL', 'custom-model')
    admin.runtime_settings.sync_persisted_settings_from_env()
    assert runtime_file.exists()

    for path, env_key, kind, default in admin.runtime_settings._FIELD_SPECS:
        exists, raw_value = admin.runtime_settings._read_nested(admin.runtime_settings._BOOT_DEFAULTS, path)
        if exists:
            monkeypatch.setenv(env_key, admin.runtime_settings._stringify(raw_value))
    overrides = admin.runtime_settings.sync_persisted_settings_from_env()

    assert overrides == {}
    assert not runtime_file.exists()


@pytest.mark.asyncio
async def test_cache_stats_contract(monkeypatch):
    class FakeKBCache:
        def get_stats(self):
            return {
                "total_cached": 1,
                "max_size": 8,
                "pinned": ["course-a"],
                "pinned_count": 1,
                "hits": 3,
                "misses": 1,
                "evictions": 2,
                "total_loads": 4,
                "cached_kbs": ["course-a"],
                "hit_rate": 0.75,
            }

    monkeypatch.setattr(admin.shared, "kb_instances", FakeKBCache())

    result = await admin.cache_stats(_perm=None, current_user={"id": 1})

    assert result["cached_kbs"] == ["course-a"]
    assert result["pinned_count"] == 1
    assert result["hit_rate"] == 0.75


@pytest.mark.asyncio
async def test_cache_pin_unpin_contract(monkeypatch):
    class FakeKBCache:
        def __init__(self):
            self.pinned = set()

        def pin(self, name):
            self.pinned.add(name)

        def unpin(self, name):
            self.pinned.discard(name)

    fake_cache = FakeKBCache()
    add_event_mock = AsyncMock()
    monkeypatch.setattr(admin.shared, "kb_instances", fake_cache)
    monkeypatch.setattr(admin.shared, "add_event", add_event_mock)

    pinned = await admin.cache_pin("course-a", _perm=None, current_user={"id": 1})
    unpinned = await admin.cache_unpin("course-a", _perm=None, current_user={"id": 1})

    assert pinned == {"status": "ok", "message": "知识库“course-a”已固定到缓存"}
    assert unpinned == {"status": "ok", "message": "知识库“course-a”已取消固定"}
    assert "course-a" not in fake_cache.pinned
    assert add_event_mock.await_count == 2
    add_event_mock.assert_any_await("kb_cache_pin", kb="course-a", user_id=1)
    add_event_mock.assert_any_await("kb_cache_unpin", kb="course-a", user_id=1)


@pytest.mark.asyncio
async def test_reload_kb_clears_cache_and_logs_event(monkeypatch):
    class FakeKB:
        async def finalize_storages(self):
            return None

    class FakeCache(dict):
        pass

    fake_cache = FakeCache({"course-a": FakeKB()})
    add_event_mock = AsyncMock()

    monkeypatch.setattr(admin.shared, "kb_instances", fake_cache)
    monkeypatch.setattr(admin.shared, "add_event", add_event_mock)

    result = await admin.reload_kb("course-a", current_user={"id": 9})

    assert result == {"status": "ok", "message": "知识库“course-a”缓存已清除，下次查询将重新加载"}
    assert "course-a" not in fake_cache
    add_event_mock.assert_awaited_once_with("kb_cache_reload", kb="course-a", user_id=9)


@pytest.mark.asyncio
async def test_health_contract(monkeypatch):
    async def fake_load_kb_meta():
        return {"course-a": {"name": "Course A"}}

    class FakeConn:
        async def fetchval(self, query):
            if "system_data_epoch" in query:
                return "epoch-test"
            return 1

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    monkeypatch.setattr(admin.shared, "active_kb", "course-a")
    monkeypatch.setattr(admin.shared, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: FakePool())

    result = await admin.health()

    assert result["status"] == "ok"
    assert result["version"]
    assert result["system_data_epoch"] == "epoch-test"
    assert result["components"]["server"] == "ok"
    assert result["components"]["active_kb"] == "course-a"
    assert result["components"]["kb_count"] == 1
    assert result["components"]["monitor_logs"] == "ok"


@pytest.mark.asyncio
async def test_monitor_logs_uses_persistent_event_store(monkeypatch):
    expected = [
        {"time": "2026-07-09T10:31:46+08:00", "event": "upload_complete", "user_id": 7},
    ]

    async def fake_get_monitor_events(limit, user_id=None, is_admin=False):
        assert limit == 12
        assert user_id == 7
        assert is_admin is False
        return expected

    monkeypatch.setattr(admin.shared, "get_monitor_events", fake_get_monitor_events)

    result = await admin.monitor_logs(
        limit=12,
        _perm=None,
        current_user={"id": 7, "is_admin": False},
    )

    assert result == {"events": expected}


@pytest.mark.asyncio
async def test_monitor_status_reads_admin_events_from_store(monkeypatch):
    expected = [
        {"time": "2026-07-09T10:29:41+08:00", "event": "upload_start", "user_id": 0},
    ]

    async def fake_get_monitor_events(limit, user_id=None, is_admin=False):
        assert limit == 20
        assert user_id is None
        assert is_admin is True
        return expected

    monkeypatch.setattr(admin.shared, "get_monitor_events", fake_get_monitor_events)
    monkeypatch.setattr(admin.shared, "processing_tasks", {"task-1": {"id": "task-1", "user_id": 1}})
    monkeypatch.setattr(admin.shared, "query_history", [{"id": "q-1"}, {"id": "q-2"}])

    result = await admin.monitor_status(
        _perm=None,
        current_user={"id": 1, "is_admin": True},
    )

    assert result["events"] == expected
    assert result["tasks"] == [{"id": "task-1", "user_id": 1}]
    assert result["cache_size"] == 2
