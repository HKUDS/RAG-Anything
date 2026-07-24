import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from raganything.permissions import Permission
from raganything.processor.chunk_processor import compute_chunk_id
from raganything.routers import knowledge


class MemoryStore:
    def __init__(self, data=None, *, fail_upsert_once=False):
        self.data = deepcopy(data or {})
        self.fail_upsert_once = fail_upsert_once
        self.flushes = 0

    async def get_by_id(self, item_id):
        value = self.data.get(item_id)
        return deepcopy(value) if value is not None else None

    async def get_by_ids(self, item_ids):
        return [deepcopy(self.data.get(item_id)) for item_id in item_ids]

    async def upsert(self, values):
        if self.fail_upsert_once:
            self.fail_upsert_once = False
            raise RuntimeError("injected upsert failure")
        for item_id, value in values.items():
            self.data[item_id] = deepcopy(value)

    async def delete(self, item_ids):
        for item_id in item_ids:
            self.data.pop(item_id, None)

    async def index_done_callback(self):
        self.flushes += 1


class FailingPGDB:
    def __init__(self, *, fail_execute=False, fail_query=False):
        self.fail_execute = fail_execute
        self.fail_query = fail_query

    async def execute(self, _sql, _params):
        if self.fail_execute:
            raise RuntimeError("database delete failed")

    async def query(self, _sql, _params):
        if self.fail_query:
            raise RuntimeError("database verification failed")
        return None


class PGStoreDouble:
    __module__ = "lightrag.kg.postgres_impl"

    def __init__(self, db, *, table_name="LIGHTRAG_VDB_CHUNKS", namespace=None):
        self.db = db
        self.table_name = table_name
        self.namespace = namespace
        self.workspace = "kb-workspace"

    async def delete(self, _ids):
        # Mirrors the production public methods that swallow DB failures.
        return None

    async def get_by_id(self, _item_id):
        return None


def _chunk(chunk_id, content, order, *, tokens=2):
    return {
        "id": chunk_id,
        "chunk_id": chunk_id,
        "content": content,
        "tokens": tokens,
        "chunk_order_index": order,
        "full_doc_id": "doc-1",
        "file_path": "manual.pdf",
    }


def _status(chunk_ids=("chunk-a", "chunk-b")):
    return {
        "status": "processed",
        "content_summary": "summary",
        "content_length": 20,
        "chunks_count": len(chunk_ids),
        "chunks_list": list(chunk_ids),
        "file_path": "manual.pdf",
        "created_at": "2026-01-01T00:00:00+08:00",
        "updated_at": "2026-01-02T00:00:00+08:00",
        "metadata": {"chunking_strategy": "recursive"},
    }


def _instance(*, status=None, chunks=None, vector_fail_once=False):
    status_value = status or _status()
    chunk_values = chunks or {
        "chunk-a": _chunk("chunk-a", "alpha", 0, tokens=2),
        "chunk-b": _chunk("chunk-b", "beta", 1, tokens=3),
    }
    lg = SimpleNamespace(
        text_chunks=MemoryStore(chunk_values),
        chunks_vdb=MemoryStore(chunk_values, fail_upsert_once=vector_fail_once),
        doc_status=MemoryStore({"doc-1": status_value}),
        tokenizer=SimpleNamespace(encode=lambda value: list(value)),
    )
    return SimpleNamespace(lightrag=lg)


async def _wire(monkeypatch, instance, status=None):
    status_data = {"doc-1": status or await instance.lightrag.doc_status.get_by_id("doc-1")}

    async def fake_get_kb(_kb):
        return instance

    async def fake_status(_kb):
        current = await instance.lightrag.doc_status.get_by_id("doc-1")
        return {"doc-1": current} if current else status_data

    refreshes = []
    audit = []

    async def fake_refresh(_instance, _kb):
        current = await instance.lightrag.doc_status.get_by_id("doc-1")
        refreshes.append(list(current.get("chunks_list", [])))

    async def fake_log(**kwargs):
        audit.append(kwargs)

    async def fake_tags(_kb, _doc_id, chunk_ids):
        return {str(chunk_id): [] for chunk_id in chunk_ids}

    async def fake_move_tags(*_args, **_kwargs):
        return None

    async def fake_delete_tags(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge, "get_kb", fake_get_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", fake_status)
    monkeypatch.setattr(knowledge, "_refresh_chunk_search", fake_refresh)
    monkeypatch.setattr(knowledge, "_log_chunk_mutation", fake_log)
    monkeypatch.setattr(knowledge, "get_tags_for_chunks", fake_tags)
    monkeypatch.setattr(knowledge, "move_chunk_tags", fake_move_tags)
    monkeypatch.setattr(knowledge, "delete_chunk_tags", fake_delete_tags)
    knowledge._chunk_document_locks.clear()
    return refreshes, audit


@pytest.mark.asyncio
async def test_extended_chunks_contract_is_reloadable(monkeypatch):
    instance = _instance()
    await _wire(monkeypatch, instance)

    result = await knowledge.get_document_chunks(
        "doc-1", kb="kb-1", current_user={"id": 7}
    )

    assert result["doc_id"] == "doc-1"
    assert result["document"] == {
        "id": "doc-1",
        "file": "manual.pdf",
        "status": "processed",
        "content_summary": "summary",
        "content_length": 20,
        "chunking_strategy": "recursive",
        "created": "2026-01-01T00:00:00+08:00",
        "updated": "2026-01-02T00:00:00+08:00",
        "tag_status": "unavailable",
        "tag_raw_status": "unavailable",
        "tagged_chunks": 0,
        "eligible_tag_chunks": 0,
        "tag_not_applicable_chunks": 0,
        "unique_auto_tag_count": 0,
        "auto_tag_assignment_count": 0,
        "avg_auto_tags_per_tagged_chunk": 0.0,
        "tag_error_message": "标签状态暂时不可用",
        "tag_retryable": True,
    }
    assert result["total"] == 2
    assert result["total_tokens"] == 5
    assert result["graph_sync_state"] == "synced"


@pytest.mark.asyncio
async def test_get_document_chunk_returns_only_the_requested_chunk(monkeypatch):
    status = _status()
    status["metadata"]["multimodal_chunks"] = {
        "chunk-b": {"is_multimodal": True, "original_type": "image", "page_idx": 4}
    }
    instance = _instance(status=status)
    await _wire(monkeypatch, instance)

    async def fake_tags(_kb, _doc_id, chunk_ids):
        return {str(chunk_id): [{"id": "tag-1", "name": "医学影像"}] for chunk_id in chunk_ids}

    monkeypatch.setattr(knowledge, "get_tags_for_chunks", fake_tags)

    result = await knowledge.get_document_chunk(
        "doc-1", "chunk-b", kb="kb-1", current_user={"id": 7}
    )

    assert result["doc_id"] == "doc-1"
    assert result["document"]["file"] == "manual.pdf"
    assert result["chunk"]["chunk_id"] == "chunk-b"
    assert result["chunk"]["content"] == "beta"
    assert result["chunk"]["tokens"] == 3
    assert result["chunk"]["original_type"] == "image"
    assert result["chunk"]["page_idx"] == 4
    assert result["chunk"]["tags"] == [{"id": "tag-1", "name": "医学影像"}]
    assert result["total"] == 2
    assert result["graph_sync_state"] == "synced"


@pytest.mark.asyncio
async def test_get_document_chunk_rejects_chunk_outside_document(monkeypatch):
    instance = _instance(status=_status(("chunk-a",)))
    await _wire(monkeypatch, instance)

    with pytest.raises(HTTPException) as exc_info:
        await knowledge.get_document_chunk(
            "doc-1", "chunk-b", kb="kb-1", current_user={"id": 7}
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_document_chunk_supports_legacy_document_without_chunks_list(monkeypatch):
    status = _status(())
    status["chunks_count"] = 1
    instance = _instance(status=status)
    await _wire(monkeypatch, instance)

    result = await knowledge.get_document_chunk(
        "doc-1", "chunk-a", kb="kb-1", current_user={"id": 7}
    )

    assert result["chunk"]["chunk_id"] == "chunk-a"
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_regenerate_document_tags_uses_canonical_id_and_returns_recovery(monkeypatch):
    instance = _instance()
    _, audit = await _wire(monkeypatch, instance)
    generated = []

    async def fake_generate(kb, document_id, *, filename, user_id):
        generated.append((kb, document_id, filename, user_id))
        return {
            "assigned": 4,
            "skipped": 0,
            "document_tags": 2,
            "chunk_tags": 2,
            "chunk_count": 2,
            "status_retries": 2,
            "status_repaired": True,
            "chunk_source": "postgres",
        }

    monkeypatch.setattr(knowledge, "_generate_uploaded_document_tags", fake_generate)

    result = await knowledge.regenerate_document_automatic_tags(
        "doc", kb="kb-1", _perm=None, current_user={"id": 7},
    )

    assert result["status"] == "generated"
    assert result["doc_id"] == "doc-1"
    assert result["chunk_count"] == 2
    assert generated == [("kb-1", "doc-1", "manual.pdf", 7)]
    assert audit[-1]["action"] == "document_tags_regenerate"


@pytest.mark.asyncio
async def test_regenerate_document_tags_rejects_processing_document(monkeypatch):
    status = _status()
    status["status"] = "processing"
    instance = _instance(status=status)
    await _wire(monkeypatch, instance)

    with pytest.raises(HTTPException) as exc_info:
        await knowledge.regenerate_document_automatic_tags(
            "doc-1", kb="kb-1", _perm=None, current_user={"id": 7},
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_regenerate_document_tags_rejects_unknown_document(monkeypatch):
    instance = _instance()
    await _wire(monkeypatch, instance)

    with pytest.raises(HTTPException) as exc_info:
        await knowledge.regenerate_document_automatic_tags(
            "unknown", kb="kb-1", _perm=None, current_user={"id": 7},
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_replaces_id_preserves_order_and_multimodal_metadata(monkeypatch):
    status = _status()
    status["metadata"]["multimodal_chunks"] = {
        "chunk-a": {"is_multimodal": True, "original_type": "image", "page_idx": 4}
    }
    instance = _instance(status=status)
    refreshes, audit = await _wire(monkeypatch, instance)
    content = "replacement content"
    new_id = compute_chunk_id(content)

    result = await knowledge.update_document_chunk(
        "doc-1", "chunk-a", knowledge.ChunkContentUpdate(content=content),
        kb="kb-1", _perm=None, current_user={"id": 7},
    )

    assert result["status"] == "updated"
    assert result["old_chunk_id"] == "chunk-a"
    assert result["new_chunk_id"] == new_id
    assert result["chunk"]["is_multimodal"] is True
    assert result["total_tokens"] == len(content) + 3
    assert "chunk-a" not in instance.lightrag.text_chunks.data
    assert "chunk-a" not in instance.lightrag.chunks_vdb.data
    saved_status = instance.lightrag.doc_status.data["doc-1"]
    assert saved_status["chunks_list"] == [new_id, "chunk-b"]
    assert saved_status["metadata"]["graph_sync_state"] == "stale"
    assert saved_status["metadata"]["multimodal_chunks"][new_id]["page_idx"] == 4
    assert refreshes[-1] == [new_id, "chunk-b"]
    assert audit[-1]["before_hash"]
    assert audit[-1]["after_hash"]
    assert "content" not in audit[-1]


@pytest.mark.asyncio
async def test_update_rejects_duplicate_content_id(monkeypatch):
    instance = _instance()
    duplicate_id = compute_chunk_id("beta")
    duplicate = _chunk(duplicate_id, "beta", 2)
    instance.lightrag.text_chunks.data[duplicate_id] = duplicate
    instance.lightrag.chunks_vdb.data[duplicate_id] = duplicate
    await _wire(monkeypatch, instance)

    with pytest.raises(HTTPException) as exc:
        await knowledge.update_document_chunk(
            "doc-1", "chunk-a", knowledge.ChunkContentUpdate(content="beta"),
            kb="kb-1", _perm=None, current_user={"id": 7},
        )

    assert exc.value.status_code == 409
    assert instance.lightrag.doc_status.data["doc-1"]["chunks_list"] == ["chunk-a", "chunk-b"]


@pytest.mark.asyncio
async def test_update_compensates_vector_failure(monkeypatch):
    instance = _instance(vector_fail_once=True)
    refreshes, _ = await _wire(monkeypatch, instance)
    new_id = compute_chunk_id("changed")

    with pytest.raises(HTTPException) as exc:
        await knowledge.update_document_chunk(
            "doc-1", "chunk-a", knowledge.ChunkContentUpdate(content="changed"),
            kb="kb-1", _perm=None, current_user={"id": 7},
        )

    assert exc.value.status_code == 500
    assert instance.lightrag.text_chunks.data["chunk-a"]["content"] == "alpha"
    assert new_id not in instance.lightrag.text_chunks.data
    assert instance.lightrag.doc_status.data["doc-1"]["chunks_list"] == ["chunk-a", "chunk-b"]
    assert refreshes[-1] == ["chunk-a", "chunk-b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_store", ["text_chunks", "doc_status"])
async def test_update_compensates_other_store_failures(monkeypatch, failing_store):
    instance = _instance()
    refreshes, _ = await _wire(monkeypatch, instance)
    getattr(instance.lightrag, failing_store).fail_upsert_once = True
    new_id = compute_chunk_id("changed again")

    with pytest.raises(HTTPException) as exc:
        await knowledge.update_document_chunk(
            "doc-1", "chunk-a", knowledge.ChunkContentUpdate(content="changed again"),
            kb="kb-1", _perm=None, current_user={"id": 7},
        )

    assert exc.value.status_code == 500
    assert instance.lightrag.text_chunks.data["chunk-a"]["content"] == "alpha"
    assert new_id not in instance.lightrag.text_chunks.data
    assert instance.lightrag.doc_status.data["doc-1"]["chunks_list"] == ["chunk-a", "chunk-b"]
    assert refreshes[-1] == ["chunk-a", "chunk-b"]


@pytest.mark.asyncio
async def test_delete_updates_all_stores_and_statistics(monkeypatch):
    instance = _instance()
    refreshes, _ = await _wire(monkeypatch, instance)

    result = await knowledge.delete_document_chunk(
        "doc-1", "chunk-a", kb="kb-1", _perm=None, current_user={"id": 7}
    )

    assert result == {
        "status": "deleted",
        "doc_id": "doc-1",
        "deleted_chunk_id": "chunk-a",
        "total": 1,
        "total_tokens": 3,
        "graph_sync_state": "stale",
    }
    assert "chunk-a" not in instance.lightrag.text_chunks.data
    assert "chunk-a" not in instance.lightrag.chunks_vdb.data
    assert instance.lightrag.doc_status.data["doc-1"]["chunks_list"] == ["chunk-b"]
    assert refreshes[-1] == ["chunk-b"]


@pytest.mark.asyncio
async def test_delete_rejects_final_chunk(monkeypatch):
    status = _status(("chunk-a",))
    instance = _instance(
        status=status, chunks={"chunk-a": _chunk("chunk-a", "alpha", 0)}
    )
    await _wire(monkeypatch, instance)

    with pytest.raises(HTTPException) as exc:
        await knowledge.delete_document_chunk(
            "doc-1", "chunk-a", kb="kb-1", _perm=None, current_user={"id": 7}
        )

    assert exc.value.status_code == 409
    assert "delete the document" in exc.value.detail


@pytest.mark.asyncio
async def test_mutations_reject_processing_document(monkeypatch):
    status = _status()
    status["status"] = "processing"
    instance = _instance(status=status)
    await _wire(monkeypatch, instance)

    with pytest.raises(HTTPException) as exc:
        await knowledge.update_document_chunk(
            "doc-1", "chunk-a", knowledge.ChunkContentUpdate(content="changed"),
            kb="kb-1", _perm=None, current_user={"id": 7},
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_legacy_empty_chunk_list_is_materialized_during_update(monkeypatch):
    status = _status()
    status["chunks_list"] = []
    instance = _instance(status=status)
    await _wire(monkeypatch, instance)

    async def fallback(_lg, _doc_id, _kb):
        return [
            deepcopy(instance.lightrag.text_chunks.data["chunk-a"]),
            deepcopy(instance.lightrag.text_chunks.data["chunk-b"]),
        ]

    monkeypatch.setattr(knowledge, "_query_chunks_by_doc_id", fallback)
    new_id = compute_chunk_id("legacy replacement")

    await knowledge.update_document_chunk(
        "doc", "chunk-a", knowledge.ChunkContentUpdate(content="legacy replacement"),
        kb="kb-1", _perm=None, current_user={"id": 7},
    )

    assert instance.lightrag.doc_status.data["doc-1"]["chunks_list"] == [new_id, "chunk-b"]
    assert ("kb-1", "doc-1") in knowledge._chunk_document_locks
    assert ("kb-1", "doc") not in knowledge._chunk_document_locks


@pytest.mark.asyncio
async def test_bm25_refresh_rebuilds_the_complete_kb(monkeypatch):
    chunks = {
        "chunk-a": _chunk("chunk-a", "alpha", 0),
        "chunk-b": _chunk("chunk-b", "beta", 1),
        "chunk-c": {**_chunk("chunk-c", "gamma", 0), "full_doc_id": "doc-2"},
    }
    instance = _instance(chunks=chunks)
    rebuilt = []

    async def build(records):
        rebuilt.append({knowledge._stored_chunk_id(value) for value in records})

    instance.hybrid_search_engine = SimpleNamespace(build_bm25_index=build)

    async def all_status(_kb):
        return {
            "doc-1": _status(),
            "doc-2": {**_status(("chunk-c",)), "file_path": "other.pdf"},
        }

    monkeypatch.setattr(knowledge, "_load_doc_status_json", all_status)
    await knowledge._refresh_chunk_search(instance, "kb-1")

    assert rebuilt == [{"chunk-a", "chunk-b", "chunk-c"}]


@pytest.mark.asyncio
async def test_bm25_replacement_rebuilds_are_serialized_per_kb(monkeypatch):
    instance = _instance()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    calls = 0

    async def build(_records):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()

    instance.hybrid_search_engine = SimpleNamespace(build_bm25_index=build)

    async def all_status(_kb):
        return {"doc-1": _status()}

    monkeypatch.setattr(knowledge, "_load_doc_status_json", all_status)
    knowledge._chunk_bm25_locks.clear()
    first = asyncio.create_task(knowledge._refresh_chunk_search(instance, "kb-1"))
    await first_started.wait()
    second = asyncio.create_task(knowledge._refresh_chunk_search(instance, "kb-1"))
    await asyncio.sleep(0)
    assert second_started.is_set() is False
    release_first.set()
    await asyncio.gather(first, second)
    assert second_started.is_set() is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["execute", "query"])
async def test_pg_vector_delete_cannot_hide_database_failures(failure):
    store = PGStoreDouble(
        FailingPGDB(
            fail_execute=failure == "execute",
            fail_query=failure == "query",
        )
    )

    with pytest.raises(RuntimeError):
        await knowledge._delete_chunk_vectors(store, ["chunk-a"])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["execute", "query"])
async def test_pg_text_delete_cannot_hide_database_failures(failure):
    store = PGStoreDouble(
        FailingPGDB(
            fail_execute=failure == "execute",
            fail_query=failure == "query",
        ),
        table_name="LIGHTRAG_DOC_CHUNKS",
    )

    with pytest.raises(RuntimeError):
        await knowledge._delete_chunk_text(store, ["chunk-a"])


def test_chunk_write_routes_require_kb_write_permission():
    routes = {
        (method, route.path): route
        for route in knowledge.router.routes
        for method in getattr(route, "methods", set())
    }
    for key in (
        ("PATCH", "/knowledge/documents/{doc_id}/chunks/{chunk_id}"),
        ("DELETE", "/knowledge/documents/{doc_id}/chunks/{chunk_id}"),
    ):
        dependency_names = {
            getattr(dependency.call, "__name__", "")
            for dependency in routes[key].dependant.dependencies
        }
        assert "verify_kb_access" in dependency_names
        assert "require_kb_write" in dependency_names
        assert Permission.KB_WRITE == "kb:write"


def test_extended_chunk_get_route_is_registered_once():
    matching = [
        route
        for route in knowledge.router.routes
        if route.path == "/knowledge/documents/{doc_id}/chunks"
        and "GET" in getattr(route, "methods", set())
    ]
    assert len(matching) == 1
    assert matching[0].endpoint is knowledge.get_document_chunks
