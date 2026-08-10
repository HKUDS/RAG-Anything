import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from raganything.routers import knowledge


@pytest.fixture(autouse=True)
def _isolate_document_delete_side_effects(monkeypatch):
    """Lifecycle tests use in-memory LightRAG stores, not a PostgreSQL pool."""
    monkeypatch.setattr(knowledge, "delete_document_tags", AsyncMock())
    monkeypatch.setattr(
        knowledge, "pg_release_upload_for_deleted_document", AsyncMock(return_value=True)
    )


class _Store:
    def __init__(self):
        self.deleted = []
        self.index_done = 0

    async def delete(self, ids):
        self.deleted.extend(ids)

    async def index_done_callback(self):
        self.index_done += 1


class _VisionRepo:
    def __init__(self, orphan_ids=None):
        self.doc_ids = []
        self.deleted_ids = []
        self.orphan_inputs = []
        self.flushes = 0
        self._orphan_ids = orphan_ids or []

    async def delete_by_doc_id(self, doc_id):
        self.doc_ids.append(doc_id)
        return 1

    async def get_orphan_ids(self, valid_doc_ids):
        self.orphan_inputs.append(set(valid_doc_ids))
        return list(self._orphan_ids)

    async def delete_by_ids(self, ids):
        self.deleted_ids.extend(ids)
        return len(ids)

    async def flush(self):
        self.flushes += 1


class _Result:
    def __init__(self, status, message="ok"):
        self.status = status
        self.message = message


class _OperationCache:
    def __init__(self, pinned=()):
        self._pinned = set(pinned)
        self.pin_calls = []
        self.unpin_calls = []

    def is_pinned(self, name):
        return name in self._pinned

    def pin(self, name):
        self.pin_calls.append(name)
        self._pinned.add(name)

    def unpin(self, name):
        self.unpin_calls.append(name)
        self._pinned.discard(name)


class _LightRAG:
    def __init__(self, statuses):
        self.result = _Result("success")
        self.deleted_doc_ids = []
        self.finalize_count = 0
        self.doc_status = _Store()
        self.image_vision_repo = _VisionRepo()
        self.full_entities = _Store()
        self.full_relations = _Store()
        self.full_docs = _Store()
        self._statuses = statuses

    async def adelete_by_doc_id(self, doc_id, delete_llm_cache=True):
        assert delete_llm_cache is True
        self.deleted_doc_ids.append(doc_id)
        return self.result

    async def finalize_storages(self):
        self.finalize_count += 1


def _install_query_cache(monkeypatch):
    cache = SimpleNamespace(invalidate=Mock())
    import raganything.query_cache as query_cache

    monkeypatch.setattr(query_cache, "get_query_cache", lambda: cache)
    return cache


@pytest.mark.asyncio
async def test_lightrag_document_deletion_is_serialized_per_kb(monkeypatch):
    class ConcurrentLightRAG:
        def __init__(self):
            self.doc_status = _Store()
            self.active = 0
            self.max_active = 0
            self.deleted = []

        async def adelete_by_doc_id(self, doc_id, delete_llm_cache=True):
            assert delete_llm_cache is True
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.deleted.append(doc_id)
            self.active -= 1
            return _Result("success")

    monkeypatch.setattr(knowledge, "_document_delete_locks", {})
    lightrag = ConcurrentLightRAG()

    first, second = await asyncio.gather(
        knowledge._delete_lightrag_document(lightrag, "demo", "doc-one"),
        knowledge._delete_lightrag_document(lightrag, "demo", "doc-two"),
    )

    assert [first.status, second.status] == ["success", "success"]
    assert lightrag.max_active == 1
    assert lightrag.deleted == ["doc-one", "doc-two"]


@pytest.mark.asyncio
async def test_single_delete_rejects_an_active_processing_task(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({"other": {}}))
    active_task = {"status": "processing", "file": "report.docx", "kb": "demo"}
    delete_task = AsyncMock()

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=active_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    _install_query_cache(monkeypatch)

    with pytest.raises(knowledge.HTTPException) as exc_info:
        await knowledge.delete_document(
            "task-active", kb="demo", _perm=None, current_user={"id": 1}
        )

    assert exc_info.value.status_code == 409
    delete_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_delete_cleans_a_stalled_parsing_task_without_worker(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({"other": {}}))
    stalled_task = {
        "status": "processing",
        "phase": "parsing",
        "updated_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "file": "report.docx",
        "kb": "demo",
    }
    delete_task = AsyncMock()

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=stalled_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "_kb_worker_procs", {})
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    _install_query_cache(monkeypatch)

    result = await knowledge.delete_document(
        "task-stalled", kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "deleted"
    delete_task.assert_awaited_once_with("task-stalled")


@pytest.mark.asyncio
async def test_single_delete_keeps_stalled_parsing_task_with_live_worker(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({"other": {}}))
    active_task = {
        "status": "processing",
        "phase": "parsing",
        "updated_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "file": "report.docx",
        "kb": "demo",
    }
    delete_task = AsyncMock()
    worker = SimpleNamespace(returncode=None)

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=active_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "_kb_worker_procs", {"demo": [(worker, "task-active")]})
    _install_query_cache(monkeypatch)

    with pytest.raises(knowledge.HTTPException) as exc_info:
        await knowledge.delete_document(
            "task-active", kb="demo", _perm=None, current_user={"id": 1}
        )

    assert exc_info.value.status_code == 409
    delete_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_delete_does_not_cross_kb_match_processing_task(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({"other": {}}))
    other_kb_task = {
        "status": "processing",
        "phase": "parsing",
        "updated_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "file": "report.docx",
        "kb": "other",
    }
    delete_task = AsyncMock()

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=other_kb_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    _install_query_cache(monkeypatch)

    with pytest.raises(knowledge.HTTPException) as exc_info:
        await knowledge.delete_document(
            "task-other-kb", kb="demo", _perm=None, current_user={"id": 1}
        )

    assert exc_info.value.status_code == 404
    delete_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_delete_cleans_an_orphaned_post_parse_task(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({"other": {}}))
    orphan_task = {
        "status": "processing",
        "phase": "entity-extraction",
        "file": "report.docx",
        "kb": "demo",
    }
    delete_task = AsyncMock()
    release_upload = AsyncMock(return_value=True)

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=orphan_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "pg_release_upload_for_deleted_document", release_upload)
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    _install_query_cache(monkeypatch)

    result = await knowledge.delete_document(
        "task-orphan", kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "deleted"
    delete_task.assert_awaited_once_with("task-orphan")
    release_upload.assert_awaited_once_with("demo", "report.docx")


@pytest.mark.asyncio
async def test_batch_delete_keeps_an_active_processing_task(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({"other": {}}))
    active_task = {"status": "processing", "file": "report.docx", "kb": "demo"}
    delete_task = AsyncMock()

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={"other": {}}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=active_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=["task-active"]),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["deleted"] == []
    assert result["errors"] == [
        {"doc_id": "task-active", "error": "文档仍在处理中，不能删除活动任务"}
    ]
    delete_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_delete_cleans_a_stalled_parsing_task_without_worker(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({}))
    stalled_task = {
        "status": "processing",
        "phase": "parsing",
        "updated_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "file": "report.docx",
        "kb": "demo",
    }
    delete_task = AsyncMock()
    release_upload = AsyncMock(return_value=True)

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=stalled_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "pg_release_upload_for_deleted_document", release_upload)
    monkeypatch.setattr(knowledge, "_kb_worker_procs", {})
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=["task-stalled"]),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["deleted"] == ["task-stalled"]
    delete_task.assert_awaited_once_with("task-stalled")
    release_upload.assert_awaited_once_with("demo", "report.docx")


@pytest.mark.asyncio
async def test_batch_delete_cleans_an_orphaned_post_parse_task(monkeypatch):
    instance = SimpleNamespace(lightrag=_LightRAG({}))
    orphan_task = {
        "status": "processing",
        "phase": "graph-building",
        "file": "report.docx",
        "kb": "demo",
    }
    delete_task = AsyncMock()
    release_upload = AsyncMock(return_value=True)

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge, "get_task_status", AsyncMock(return_value=orphan_task))
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "pg_release_upload_for_deleted_document", release_upload)
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=["task-orphan"]),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["deleted"] == ["task-orphan"]
    delete_task.assert_awaited_once_with("task-orphan")
    release_upload.assert_awaited_once_with("demo", "report.docx")


@pytest.mark.asyncio
async def test_successful_single_delete_keeps_cached_storages_open(monkeypatch):
    statuses = {"doc-full": {"file_path": "report.docx"}}
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    purge = AsyncMock()

    async def get_kb(_kb):
        return instance

    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "_purge_all_orphans", purge)
    release_upload = AsyncMock(return_value=True)
    monkeypatch.setattr(knowledge, "pg_release_upload_for_deleted_document", release_upload)
    cache = _install_query_cache(monkeypatch)

    result = await knowledge.delete_document(
        "doc", kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "deleted"
    assert lightrag.deleted_doc_ids == ["doc-full"]
    assert lightrag.image_vision_repo.doc_ids == ["doc-full"]
    assert lightrag.image_vision_repo.flushes == 1
    assert lightrag.finalize_count == 0
    purge.assert_not_awaited()
    cache.invalidate.assert_called_once()
    release_upload.assert_awaited_once_with("demo", "report.docx")


@pytest.mark.asyncio
async def test_single_delete_removes_matching_persisted_processing_task(monkeypatch):
    statuses = {"doc-full": {"file_path": "a1b2c3d4_report.docx"}}
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    stale_task_id = "stale-task"
    stale_task = {
        "kb": "demo",
        "file": "report.docx",
        "status": "processing",
    }
    delete_task = AsyncMock()

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "processing_tasks", {stale_task_id: stale_task})
    _install_query_cache(monkeypatch)

    result = await knowledge.delete_document(
        "doc", kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "deleted"
    delete_task.assert_awaited_once_with(stale_task_id)


@pytest.mark.asyncio
async def test_batch_delete_removes_matching_persisted_processing_task(monkeypatch):
    statuses = {"doc-full": {"file_path": "a1b2c3d4_report.docx"}}
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    stale_task_id = "stale-task"
    stale_task = {
        "kb": "demo",
        "file_path": "report.docx",
        "status": "processing",
    }
    delete_task = AsyncMock()

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "delete_task", delete_task)
    monkeypatch.setattr(knowledge, "processing_tasks", {stale_task_id: stale_task})
    _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=["doc"]),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["deleted"] == ["doc"]
    delete_task.assert_awaited_once_with(stale_task_id)


@pytest.mark.asyncio
async def test_single_delete_leases_kb_cache_until_operation_finishes(monkeypatch):
    statuses = {"doc-full": {"file_path": "report.docx"}}
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    operation_cache = _OperationCache()

    async def get_kb(_kb):
        return instance

    async def delete_by_doc_id(doc_id, delete_llm_cache=True):
        assert operation_cache.is_pinned("demo")
        return _Result("success")

    lightrag.adelete_by_doc_id = delete_by_doc_id
    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "kb_instances", operation_cache)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    _install_query_cache(monkeypatch)

    result = await knowledge.delete_document(
        "doc", kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "deleted"
    assert operation_cache.pin_calls == ["demo"]
    assert operation_cache.unpin_calls == ["demo"]
    assert operation_cache.is_pinned("demo") is False


@pytest.mark.asyncio
async def test_batch_delete_releases_only_its_temporary_cache_lease(monkeypatch):
    statuses = {"doc-full": {"file_path": "report.docx"}}
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    operation_cache = _OperationCache(pinned=("demo",))

    async def get_kb(_kb):
        return instance

    async def delete_by_doc_id(doc_id, delete_llm_cache=True):
        assert operation_cache.is_pinned("demo")
        return _Result("success")

    lightrag.adelete_by_doc_id = delete_by_doc_id
    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "kb_instances", operation_cache)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=["doc"]),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["total_deleted"] == 1
    assert operation_cache.pin_calls == []
    assert operation_cache.unpin_calls == []
    assert operation_cache.is_pinned("demo") is True


@pytest.mark.asyncio
async def test_not_found_delete_runs_one_deep_orphan_repair(monkeypatch):
    statuses = {"doc-full": {"file_path": "report.docx"}}
    lightrag = _LightRAG(statuses)
    lightrag.result = _Result("not_found")
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    purge = AsyncMock(return_value={})
    force_cleanup = AsyncMock(return_value=["docs"])

    async def get_kb(_kb):
        return instance

    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "_force_cleanup_lightrag_orphans", force_cleanup)
    monkeypatch.setattr(knowledge, "_purge_all_orphans", purge)
    _install_query_cache(monkeypatch)

    result = await knowledge.delete_document(
        "doc", kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "deleted"
    assert lightrag.doc_status.deleted == ["doc-full"]
    force_cleanup.assert_awaited_once_with(instance, "doc-full")
    purge.assert_awaited_once_with(instance, "demo", deep_scan=True)
    assert lightrag.image_vision_repo.doc_ids == ["doc-full"]


@pytest.mark.asyncio
async def test_successful_batch_delete_keeps_cached_storages_open(monkeypatch):
    statuses = {
        f"doc-{index}": {"file_path": f"report-{index}.docx"}
        for index in range(3)
    }
    doc_ids = list(statuses)
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    purge = AsyncMock()

    async def get_kb(_kb):
        return instance

    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "_purge_all_orphans", purge)
    cache = _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=doc_ids),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["total_deleted"] == 3
    assert lightrag.deleted_doc_ids == doc_ids
    assert lightrag.image_vision_repo.doc_ids == doc_ids
    assert lightrag.image_vision_repo.flushes == 1
    assert lightrag.finalize_count == 0
    assert instance.multimodal_status_cache.deleted == doc_ids
    purge.assert_not_awaited()
    cache.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_mixed_batch_delete_runs_one_repair_for_not_found_records(monkeypatch):
    statuses = {
        "doc-success": {"file_path": "success.docx"},
        "doc-missing": {"file_path": "missing.docx"},
    }
    lightrag = _LightRAG(statuses)
    instance = SimpleNamespace(lightrag=lightrag, multimodal_status_cache=_Store())
    purge = AsyncMock(return_value={})
    force_cleanup = AsyncMock(return_value=[])

    async def delete_by_doc_id(doc_id, delete_llm_cache=True):
        lightrag.deleted_doc_ids.append(doc_id)
        return _Result("not_found" if doc_id == "doc-missing" else "success")

    async def get_kb(_kb):
        return instance

    lightrag.adelete_by_doc_id = delete_by_doc_id
    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", AsyncMock(return_value=statuses))
    monkeypatch.setattr(knowledge, "_cleanup_document_files", lambda *args: None)
    monkeypatch.setattr(knowledge, "add_event", AsyncMock())
    monkeypatch.setattr(knowledge, "_force_cleanup_lightrag_orphans", force_cleanup)
    monkeypatch.setattr(knowledge, "_purge_all_orphans", purge)
    _install_query_cache(monkeypatch)

    result = await knowledge.batch_delete_documents(
        knowledge.BatchDeleteRequest(doc_ids=["doc-success", "doc-missing"]),
        kb="demo",
        _perm=None,
        current_user={"id": 1},
    )

    assert result["total_deleted"] == 2
    force_cleanup.assert_awaited_once_with(instance, "doc-missing")
    purge.assert_awaited_once_with(instance, "demo", deep_scan=True)


@pytest.mark.asyncio
async def test_empty_kb_repair_uses_shared_strict_reconciliation(monkeypatch):
    instance = SimpleNamespace(lightrag=object())
    purge = AsyncMock(return_value={"docs": 1})

    async def get_kb(_kb):
        return instance

    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "_purge_all_orphans", purge)
    cache = _install_query_cache(monkeypatch)

    result = await knowledge.repair_kb_orphans(
        kb="demo", _perm=None, current_user={"id": 1}
    )

    assert result["status"] == "repaired"
    purge.assert_awaited_once_with(instance, "demo", deep_scan=True, strict=True)
    cache.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_empty_doc_whitelist_purges_persisted_residue(monkeypatch):
    lightrag = SimpleNamespace(
        full_entities=_Store(),
        full_relations=_Store(),
        full_docs=_Store(),
        image_vision_repo=_VisionRepo(orphan_ids=["img-orphan"]),
        entities_vdb=None,
        relationships_vdb=None,
    )
    instance = SimpleNamespace(lightrag=lightrag)

    monkeypatch.setattr(knowledge, "_pg_fetch_doc_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        knowledge,
        "_pg_fetch_graph_entities",
        AsyncMock(return_value={"old-doc": {"entity_names": ["stale"]}}),
    )
    monkeypatch.setattr(
        knowledge,
        "_pg_fetch_graph_relations",
        AsyncMock(return_value={"old-doc": {"relation_pairs": [["a", "b"]]}}),
    )
    monkeypatch.setattr(
        knowledge, "_pg_fetch_full_doc_ids", AsyncMock(return_value={"old-doc"})
    )

    report = await knowledge._purge_all_orphans(instance, "demo")

    assert report == {"entities": 1, "relations": 1, "docs": 1, "vision_vectors": 1}
    assert lightrag.full_entities.deleted == ["old-doc"]
    assert lightrag.full_relations.deleted == ["old-doc"]
    assert lightrag.full_docs.deleted == ["old-doc"]
    assert lightrag.image_vision_repo.orphan_inputs == [set()]
    assert lightrag.image_vision_repo.deleted_ids == ["img-orphan"]


@pytest.mark.asyncio
async def test_strict_repair_does_not_delete_when_doc_lookup_fails(monkeypatch):
    lightrag = SimpleNamespace(
        full_entities=_Store(),
        full_relations=_Store(),
        full_docs=_Store(),
        image_vision_repo=None,
    )
    instance = SimpleNamespace(lightrag=lightrag)

    async def unavailable(_workspace):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(knowledge, "_pg_fetch_doc_ids", unavailable)

    with pytest.raises(RuntimeError, match="authoritative doc-status"):
        await knowledge._purge_all_orphans(instance, "demo", strict=True)

    assert lightrag.full_entities.deleted == []


@pytest.mark.asyncio
async def test_deep_scan_keeps_valid_vectors_and_cleans_async_graph_nodes():
    class Vdb:
        def __init__(self):
            self._NanoVectorDB__storage = {
                "data": [
                    {"__id__": "ent-valid-hash", "entity_name": "valid"},
                    {"__id__": "ent-stale-hash", "entity_name": "stale"},
                ]
            }
            self.deleted = []

        async def delete(self, ids):
            self.deleted.extend(ids)

        async def index_done_callback(self):
            return None

    class Graph:
        def __init__(self):
            self.deleted = []
            self.persisted = 0

        async def get_all_nodes(self):
            return [{"id": "valid"}, {"entity_id": "stale"}]

        async def delete_node(self, node_id):
            self.deleted.append(node_id)

        async def index_done_callback(self):
            self.persisted += 1

    vdb = Vdb()
    graph = Graph()
    lightrag = SimpleNamespace(
        entities_vdb=vdb,
        relationships_vdb=None,
        chunk_entity_relation_graph=graph,
    )

    report = await knowledge._purge_orphan_vdb_entries(
        lightrag,
        {"current": {"entity_names": ["valid"]}},
        {},
    )

    assert report == {"entities_vdb": 1, "graph_nodes": 1}
    assert vdb.deleted == ["ent-stale-hash"]
    assert "ent-valid-hash" not in vdb.deleted
    assert graph.deleted == ["stale"]
    assert graph.persisted == 1
