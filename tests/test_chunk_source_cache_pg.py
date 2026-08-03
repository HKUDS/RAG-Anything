"""Tests for the PG-backed chunk-source cache rebuild.

Covers fix-citation-docnames-and-media-recall: PG reconstruction with
three-state chunks_list parsing, failure retry, TTL refresh, and the
JSON-storage regression path.
"""

import asyncio
from types import SimpleNamespace

import pytest

import raganything.processor.chunk_processor as chunk_processor_module
from raganything.processor.chunk_processor import ChunkProcessorMixin


class _FakeDB:
    def __init__(self, rows, *, fail_first=False):
        self.rows = list(rows)
        self.fail_first = fail_first
        self.attempts = 0
        self.calls = []

    async def query(self, sql, params=None, multirows=False):
        self.attempts += 1
        self.calls.append((sql, params, multirows))
        if self.fail_first and self.attempts == 1:
            raise RuntimeError("db unavailable")
        return list(self.rows)


class _PGStore:
    def __init__(self, rows, *, workspace="ws", fail_first=False):
        self.db = _FakeDB(rows, fail_first=fail_first)
        self.workspace = workspace


def _make_processor(store, *, use_full_path=False):
    processor = object.__new__(ChunkProcessorMixin)
    processor.config = SimpleNamespace(use_full_path=use_full_path)
    processor.lightrag = SimpleNamespace(doc_status=store)
    return processor


@pytest.mark.asyncio
async def test_pg_rebuild_populates_cache_with_three_state_chunks_list():
    rows = [
        {"file_path": "/data/manual.pdf", "chunks_list": '["chunk-a", "chunk-b"]'},
        {"file_path": "/data/slides.pptx", "chunks_list": ["chunk-c"]},
        {"file_path": "/data/no-chunks.pdf", "chunks_list": None},
        {"file_path": "/data/corrupt.json", "chunks_list": "{broken"},
        {"file_path": "/data/odd.json", "chunks_list": {"not": "a list"}},
        {"file_path": "", "chunks_list": ["chunk-skipped"]},
    ]
    store = _PGStore(rows)
    processor = _make_processor(store)

    await processor._ensure_chunk_source_cache()

    assert processor._chunk_source_cache["chunk-a"] == {
        "file_path": "/data/manual.pdf",
        "document_name": "manual.pdf",
    }
    assert processor._chunk_source_cache["chunk-b"]["document_name"] == "manual.pdf"
    assert processor._chunk_source_cache["chunk-c"]["document_name"] == "slides.pptx"
    assert "chunk-skipped" not in processor._chunk_source_cache
    assert processor._chunk_source_cache_built_at > 0

    sql, params, multirows = store.db.calls[0]
    assert "LIGHTRAG_DOC_STATUS" in sql
    assert "workspace=$1" in sql
    assert "chunks_list IS NOT NULL" in sql
    assert params == ["ws"]
    assert multirows is True


@pytest.mark.asyncio
async def test_pg_rebuild_failure_is_not_marked_fresh_and_retries():
    rows = [{"file_path": "/data/manual.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows, fail_first=True)
    processor = _make_processor(store)

    await processor._ensure_chunk_source_cache()
    assert getattr(processor, "_chunk_source_cache_built_at", 0.0) == 0.0
    assert store.db.attempts == 1

    await processor._ensure_chunk_source_cache()
    assert processor._chunk_source_cache_built_at > 0
    assert processor._chunk_source_cache["chunk-a"]["document_name"] == "manual.pdf"
    assert store.db.attempts == 2


@pytest.mark.asyncio
async def test_fresh_cache_skips_rebuild_query():
    rows = [{"file_path": "/data/manual.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows)
    processor = _make_processor(store)

    await processor._ensure_chunk_source_cache()
    await processor._ensure_chunk_source_cache()

    assert store.db.attempts == 1


@pytest.mark.asyncio
async def test_expired_ttl_triggers_rebuild(monkeypatch):
    monkeypatch.setattr(chunk_processor_module, "_CHUNK_SOURCE_CACHE_TTL_SECONDS", 0.01)
    rows = [{"file_path": "/data/manual.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows)
    processor = _make_processor(store)

    await processor._ensure_chunk_source_cache()
    await asyncio.sleep(0.02)
    await processor._ensure_chunk_source_cache()

    assert store.db.attempts == 2


@pytest.mark.asyncio
async def test_json_store_uses_memory_path():
    class _JsonStore:
        def __init__(self):
            self._data = {
                "doc-1": {
                    "file_path": "/data/manual.pdf",
                    "chunks_list": ["chunk-a", "chunk-b"],
                },
                "doc-2": {"file_path": "/data/notes.md", "chunks_list": ["chunk-c"]},
            }
            self._storage_lock = asyncio.Lock()

    store = _JsonStore()
    processor = _make_processor(store)

    await processor._ensure_chunk_source_cache()

    assert processor._chunk_source_cache["chunk-a"]["document_name"] == "manual.pdf"
    assert processor._chunk_source_cache["chunk-b"]["document_name"] == "manual.pdf"
    assert processor._chunk_source_cache["chunk-c"]["document_name"] == "notes.md"
    assert processor._chunk_source_cache_built_at > 0


@pytest.mark.asyncio
async def test_pg_rebuild_honors_use_full_path():
    rows = [{"file_path": "/data/manual.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows)
    processor = _make_processor(store, use_full_path=True)

    await processor._ensure_chunk_source_cache()

    assert processor._chunk_source_cache["chunk-a"] == {
        "file_path": "/data/manual.pdf",
        "document_name": "/data/manual.pdf",
    }


@pytest.mark.asyncio
async def test_rebuild_does_not_overwrite_processing_time_registration():
    rows = [{"file_path": "/data/pg.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows)
    processor = _make_processor(store)
    processor._register_chunk_sources("doc-1", "/data/registered.pdf", ["chunk-a"])

    await processor._ensure_chunk_source_cache()

    assert processor._chunk_source_cache["chunk-a"] == {
        "file_path": "/data/registered.pdf",
        "document_name": "registered.pdf",
    }


@pytest.mark.asyncio
async def test_batch_get_doc_source_info_async_triggers_pg_rebuild():
    rows = [{"file_path": "/data/manual.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows)
    processor = _make_processor(store)

    result = await processor.batch_get_doc_source_info_async(["chunk-a"])

    assert result["chunk-a"]["document_name"] == "manual.pdf"
    assert store.db.attempts == 1


@pytest.mark.asyncio
async def test_concurrent_ensure_rebuilds_only_once():
    rows = [{"file_path": "/data/manual.pdf", "chunks_list": ["chunk-a"]}]
    store = _PGStore(rows)
    processor = _make_processor(store)

    await asyncio.gather(
        processor._ensure_chunk_source_cache(),
        processor._ensure_chunk_source_cache(),
        processor._ensure_chunk_source_cache(),
    )

    assert store.db.attempts == 1
    assert processor._chunk_source_cache_built_at > 0