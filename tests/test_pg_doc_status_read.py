from types import SimpleNamespace

import pytest

from raganything.services import kb_service


class _Cache(dict):
    """Small dict-compatible cache for exercising cache recovery."""


class _PagedDocStatus:
    def __init__(self, docs, *, full_docs=None, db=object()):
        self.db = db
        self._docs = docs
        self.calls = []
        self.full_docs = full_docs or {
            doc_id: _record_from_status(status) for doc_id, status in docs
        }
        self.by_ids_calls = []
        self.by_id_calls = []

    async def get_docs_paginated(self, **kwargs):
        self.calls.append(kwargs)
        page = kwargs["page"]
        page_size = kwargs["page_size"]
        start = (page - 1) * page_size
        return self._docs[start : start + page_size], len(self._docs)

    async def get_by_ids(self, doc_ids):
        self.by_ids_calls.append(doc_ids)
        return [self.full_docs.get(doc_id) for doc_id in doc_ids]

    async def get_by_id(self, doc_id):
        self.by_id_calls.append(doc_id)
        return self.full_docs.get(doc_id)


def _document_status(status, *, chunks_list=None):
    return SimpleNamespace(
        file_path="manual.pdf",
        status=status,
        content_summary="summary",
        content_length=7,
        chunks_count=2,
        chunks_list=["chunk-1", "chunk-2"] if chunks_list is None else chunks_list,
        metadata={},
        error_msg=None,
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
        track_id=None,
    )


def _record_from_status(status):
    return {
        "file_path": status.file_path,
        "status": status.status,
        "content_summary": status.content_summary,
        "content_length": status.content_length,
        "chunks_count": status.chunks_count,
        "chunks_list": list(status.chunks_list),
        "metadata": dict(status.metadata),
        "error_msg": status.error_msg,
        "created_at": status.created_at,
        "updated_at": status.updated_at,
        "track_id": status.track_id,
    }


@pytest.mark.asyncio
async def test_pg_doc_status_read_rebuilds_finalized_cache_and_keeps_unknown_status(monkeypatch):
    stale = SimpleNamespace(lightrag=SimpleNamespace(doc_status=_PagedDocStatus([], db=None)))
    fresh_store = _PagedDocStatus([("doc-1", _document_status("archived"))])
    fresh = SimpleNamespace(lightrag=SimpleNamespace(doc_status=fresh_store))
    cache = _Cache({"demo": stale})

    monkeypatch.setattr(kb_service, "kb_instances", cache)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    async def get_kb(name):
        assert name == "demo"
        cache[name] = fresh
        return fresh

    monkeypatch.setattr(kb_service, "get_kb", get_kb)

    result = await kb_service._load_doc_status_json("demo")

    assert result["doc-1"]["status"] == "archived"
    assert fresh_store.calls == [
        {"status_filter": None, "page": 1, "page_size": 200}
    ]
    assert fresh_store.by_ids_calls == [["doc-1"]]


@pytest.mark.asyncio
async def test_pg_doc_status_summary_read_does_not_hydrate_chunk_lists(monkeypatch):
    summary = _document_status("processed", chunks_list=[])
    store = _PagedDocStatus(
        [("doc-1", summary)],
        full_docs={"doc-1": _record_from_status(_document_status("processed"))},
    )
    instance = SimpleNamespace(lightrag=SimpleNamespace(doc_status=store))

    monkeypatch.setattr(kb_service, "kb_instances", _Cache({"demo": instance}))
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    result = await kb_service._load_doc_status_summaries("demo")

    assert result["doc-1"]["chunks_count"] == 2
    assert "chunks_list" not in result["doc-1"]
    assert store.by_ids_calls == []


@pytest.mark.asyncio
async def test_pg_doc_status_read_hydrates_chunks_omitted_from_page_summary(monkeypatch):
    summary = _document_status("processed", chunks_list=[])
    full = _record_from_status(_document_status("processed"))
    store = _PagedDocStatus([("doc-1", summary)], full_docs={"doc-1": full})

    monkeypatch.setattr(
        kb_service,
        "kb_instances",
        _Cache({"demo": SimpleNamespace(lightrag=SimpleNamespace(doc_status=store))}),
    )
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    result = await kb_service._load_doc_status_json("demo")

    assert result["doc-1"]["chunks_list"] == ["chunk-1", "chunk-2"]
    assert result["doc-1"]["chunks_count"] == 2
    assert store.by_ids_calls == [["doc-1"]]


@pytest.mark.asyncio
async def test_pg_doc_status_read_rejects_missing_full_record(monkeypatch):
    summary = _document_status("processed", chunks_list=[])
    store = _PagedDocStatus([("doc-1", summary)], full_docs={"other": {}})

    monkeypatch.setattr(
        kb_service,
        "kb_instances",
        _Cache({"demo": SimpleNamespace(lightrag=SimpleNamespace(doc_status=store))}),
    )
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await kb_service._load_doc_status_json("demo")


@pytest.mark.asyncio
async def test_pg_doc_status_read_rejects_inconsistent_full_record(monkeypatch):
    summary = _document_status("processed", chunks_list=[])
    inconsistent = _record_from_status(_document_status("processed"))
    inconsistent["chunks_list"] = ["chunk-1"]
    store = _PagedDocStatus(
        [("doc-1", summary)], full_docs={"doc-1": inconsistent},
    )

    monkeypatch.setattr(
        kb_service,
        "kb_instances",
        _Cache({"demo": SimpleNamespace(lightrag=SimpleNamespace(doc_status=store))}),
    )
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    with pytest.raises(RuntimeError, match="chunk declaration is inconsistent"):
        await kb_service._load_doc_status_json("demo")


@pytest.mark.asyncio
async def test_pg_doc_status_read_hydrates_every_page(monkeypatch):
    docs = []
    full_docs = {}
    for index in range(201):
        doc_id = f"doc-{index}"
        summary = _document_status("processed", chunks_list=[])
        full = _record_from_status(_document_status("processed"))
        docs.append((doc_id, summary))
        full_docs[doc_id] = full
    store = _PagedDocStatus(docs, full_docs=full_docs)

    monkeypatch.setattr(
        kb_service,
        "kb_instances",
        _Cache({"demo": SimpleNamespace(lightrag=SimpleNamespace(doc_status=store))}),
    )
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    result = await kb_service._load_doc_status_json("demo")

    assert len(result) == 201
    assert [len(batch) for batch in store.by_ids_calls] == [200, 1]
    assert result["doc-200"]["chunks_list"] == ["chunk-1", "chunk-2"]


@pytest.mark.asyncio
async def test_pg_doc_status_read_by_id_uses_full_record(monkeypatch):
    summary = _document_status("processed", chunks_list=[])
    full = _record_from_status(_document_status("processed"))
    store = _PagedDocStatus([("doc-1", summary)], full_docs={"doc-1": full})

    monkeypatch.setattr(
        kb_service,
        "kb_instances",
        _Cache({"demo": SimpleNamespace(lightrag=SimpleNamespace(doc_status=store))}),
    )
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)

    result = await kb_service._load_doc_status_by_id("demo", "doc-1")

    assert result["chunks_list"] == ["chunk-1", "chunk-2"]
    assert store.by_id_calls == ["doc-1"]
    assert store.calls == []


@pytest.mark.asyncio
async def test_pg_doc_status_read_does_not_fallback_to_json_after_recovery_fails(
    monkeypatch, tmp_path
):
    stale = SimpleNamespace(lightrag=SimpleNamespace(doc_status=_PagedDocStatus([], db=None)))
    cache = _Cache({"demo": stale})
    (tmp_path / "kv_store_doc_status.json").write_text(
        '{"legacy-doc": {"status": "processed"}}', encoding="utf-8"
    )

    monkeypatch.setattr(kb_service, "kb_instances", cache)
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)
    monkeypatch.setattr(kb_service, "kb_dir", lambda _name: str(tmp_path))

    async def get_kb(_name):
        return SimpleNamespace(
            lightrag=SimpleNamespace(doc_status=_PagedDocStatus([], db=None))
        )

    monkeypatch.setattr(kb_service, "get_kb", get_kb)

    with pytest.raises(RuntimeError, match="PG doc_status storage is unavailable"):
        await kb_service._load_doc_status_json("demo")


@pytest.mark.asyncio
async def test_pg_doc_status_read_does_not_fallback_to_json_when_initialization_fails(
    monkeypatch, tmp_path
):
    (tmp_path / "kv_store_doc_status.json").write_text(
        '{"legacy-doc": {"status": "processed"}}', encoding="utf-8"
    )

    monkeypatch.setattr(kb_service, "kb_instances", _Cache())
    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)
    monkeypatch.setattr(kb_service, "kb_dir", lambda _name: str(tmp_path))

    async def get_kb(_name):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(kb_service, "get_kb", get_kb)

    with pytest.raises(RuntimeError, match="PG doc_status initialization failed"):
        await kb_service._load_doc_status_json("demo")
