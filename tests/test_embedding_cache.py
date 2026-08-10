import asyncio

import numpy as np
import pytest

from raganything.embedding import embedding_cache


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        self._pool.assert_owner_loop()
        return self._pool.connection

    async def __aexit__(self, exc_type, exc, traceback):
        self._pool.assert_owner_loop()


class _LoopBoundConnection:
    def __init__(self, pool, rows=None, read_error=None, write_error=None):
        self._pool = pool
        self._rows = rows or {}
        self._read_error = read_error
        self._write_error = write_error
        self.writes = []

    async def fetchrow(self, query, key):
        self._pool.assert_owner_loop()
        if self._read_error:
            raise self._read_error
        vector = self._rows.get(key)
        return {"embedding": vector} if vector is not None else None

    async def fetchval(self, query, key, model, vector):
        self._pool.assert_owner_loop()
        self.writes.append((key, model, vector))
        if self._write_error:
            raise self._write_error

    async def execute(self, query, model):
        self._pool.assert_owner_loop()


class _LoopBoundPool:
    def __init__(self, owner_loop, **connection_kwargs):
        self.owner_loop = owner_loop
        self.connection = _LoopBoundConnection(self, **connection_kwargs)

    def assert_owner_loop(self):
        assert asyncio.get_running_loop() is self.owner_loop

    def acquire(self):
        self.assert_owner_loop()
        return _Acquire(self)


def _install_pool(monkeypatch, pool):
    async def get_async(self, key):
        async with pool.acquire() as conn:
            row = await conn.fetchrow("cache read", key)
        return list(row["embedding"]) if row else None

    async def put_async(self, key, vector):
        async with pool.acquire() as conn:
            await conn.fetchval("cache write", key, self._model, vector)

    monkeypatch.setenv("EMBEDDING_CACHE_ENABLED", "true")
    monkeypatch.setattr(embedding_cache, "_cache_pg_ready", lambda: True)
    monkeypatch.setattr(embedding_cache.EmbeddingCache, "_pg_get_async", get_async)
    monkeypatch.setattr(embedding_cache.EmbeddingCache, "_pg_put_async", put_async)


@pytest.mark.asyncio
async def test_cached_embed_uses_active_loop_for_cache_hits_and_misses(monkeypatch):
    owner_loop = asyncio.get_running_loop()
    cache = embedding_cache.EmbeddingCache("unused", "model")
    hit_key = cache._key("hit")
    pool = _LoopBoundPool(owner_loop, rows={hit_key: [1.0, 2.0]})
    _install_pool(monkeypatch, pool)

    raw_calls = []

    async def raw_embed(texts, **kwargs):
        raw_calls.append(texts)
        return np.array([[3.0, 4.0]], dtype=np.float32)

    wrapped = embedding_cache.make_cached_embed_func(raw_embed, "unused", "model")
    result = await wrapped(["hit", "miss"])

    assert raw_calls == [["miss"]]
    assert result.tolist() == [[1.0, 2.0], [3.0, 4.0]]
    assert len(pool.connection.writes) == 1
    assert pool.connection.writes[0][1:] == ("model", [3.0, 4.0])


@pytest.mark.asyncio
async def test_cached_embed_passes_through_cache_read_failure(monkeypatch, caplog):
    pool = _LoopBoundPool(asyncio.get_running_loop(), read_error=RuntimeError("secret-text"))
    _install_pool(monkeypatch, pool)

    raw_calls = []

    async def raw_embed(texts, **kwargs):
        raw_calls.append(texts)
        return np.array([[1.0], [2.0]], dtype=np.float32)

    wrapped = embedding_cache.make_cached_embed_func(raw_embed, "unused", "model")
    result = await wrapped(["first", "second"])

    assert raw_calls == [["first", "second"]]
    assert result.tolist() == [[1.0], [2.0]]
    assert "Embedding cache read degraded (RuntimeError)" in caplog.text
    assert "secret-text" not in caplog.text


@pytest.mark.asyncio
async def test_cached_embed_passes_through_cache_write_failure(monkeypatch, caplog):
    pool = _LoopBoundPool(asyncio.get_running_loop(), write_error=RuntimeError("secret-text"))
    _install_pool(monkeypatch, pool)

    raw_calls = []

    async def raw_embed(texts, **kwargs):
        raw_calls.append(texts)
        return np.array([[5.0]], dtype=np.float32)

    wrapped = embedding_cache.make_cached_embed_func(raw_embed, "unused", "model")
    result = await wrapped(["only"])

    assert raw_calls == [["only"]]
    assert result.tolist() == [[5.0]]
    assert len(pool.connection.writes) == 1
    assert "Embedding cache write degraded (RuntimeError)" in caplog.text
    assert "secret-text" not in caplog.text


def test_synchronous_compatibility_methods_do_not_access_pg(monkeypatch):
    cache = embedding_cache.EmbeddingCache("unused", "model")
    monkeypatch.setattr(
        embedding_cache,
        "_cache_pg_ready",
        lambda: (_ for _ in ()).throw(AssertionError("pool must not be used")),
    )

    assert cache.get("text") is None
    assert cache.put("text", [1.0]) is None
    assert cache.clear() is None
