# -*- coding: utf-8 -*-
"""
Embedding Cache — PG-backed persistent cache for text embedding vectors.

Avoids redundant API calls by storing (text_hash → embedding_vector) in the
``embedding_cache`` PostgreSQL table (cross-worker shared, LRU-evicted).

Feature-gated: disabled when ``EMBEDDING_CACHE_ENABLED`` is "false".
PG-unavailable: cache misses silently (fallback is to call the embedding API).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Callable, Optional

import numpy as np

__all__ = ["EmbeddingCache", "make_cached_embed_func"]

logger = logging.getLogger("rag_server.embedding_cache")


def _run_async_from_sync(coro):
    """Safely run an async coroutine from synchronous code.

    Unlike ``asyncio.run()``, this works even when called from within
    a running event loop (e.g. inside an ``async def`` function). It
    spawns a daemon thread with its own event loop to execute the
    coroutine.

    Args:
        coro: An awaitable (coroutine object).

    Returns:
        The coroutine's return value, or raises its exception.
    """
    import asyncio as _asyncio

    result = None
    exc: Optional[Exception] = None

    def _target() -> None:
        nonlocal result, exc
        loop = None
        try:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
        except Exception as e:
            exc = e
        finally:
            if loop is not None:
                loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()

    if exc is not None:
        raise exc
    return result


def _cache_pg_ready() -> bool:
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False


class EmbeddingCache:
    """PG-backed key-value cache for text embedding vectors.

    Keys are MD5 hashes of ``(text, model_name)``.
    Values are ``double precision[]`` vectors stored in PostgreSQL.

    When PG is unavailable, ``get()`` returns ``None`` (cache miss → API call)
    and ``put()`` is a silent no-op.  No JSON-file or in-memory fallback.
    """

    __slots__ = ("_model", "_enabled", "_use_pg")

    def __init__(self, working_dir: str, model: str, enabled: bool = True) -> None:
        self._model = model
        self._enabled = enabled
        self._use_pg: bool | None = None

    def _pg_ready(self) -> bool:
        if self._use_pg is None:
            self._use_pg = _cache_pg_ready()
        return self._use_pg

    # ── public API ─────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """Return cache statistics for diagnostics."""
        return {
            "backend": "postgresql" if self._pg_ready() else "unavailable",
            "entries": "N/A (PG-backed)",
            "enabled": self._enabled,
            "model": self._model,
        }

    def get(self, text: str) -> Optional[list[float]]:
        """Look up a cached embedding by text content.

        Returns ``None`` on miss or if PG is unavailable (cache-passthrough).
        """
        if not self._enabled:
            return None
        key = self._key(text)

        if self._pg_ready():
            try:
                return self._pg_get(key)
            except Exception:
                return None
        return None

    def _pg_get(self, key: str) -> Optional[list[float]]:
        """Synchronous PG lookup (runs in a dedicated thread)."""
        try:
            return _run_async_from_sync(self._pg_get_async(key))
        except Exception:
            return None

    async def _pg_get_async(self, key: str) -> Optional[list[float]]:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT embedding FROM embedding_cache WHERE cache_key=$1",
                key,
            )
        return list(row["embedding"]) if row else None

    def put(self, text: str, embedding: list[float]) -> None:
        """Store an embedding in PG. Silent no-op if PG is unavailable."""
        if not self._enabled:
            return
        key = self._key(text)

        if self._pg_ready():
            try:
                self._pg_put(key, embedding)
            except Exception:
                pass  # PG write failure → cache miss on next get()

    def _pg_put(self, key: str, embedding: list[float]) -> None:
        """Write to PG — best-effort."""
        try:
            _run_async_from_sync(self._pg_put_async(key, embedding))
        except Exception:
            pass  # PG write failure → cache miss on next get()

    async def _pg_put_async(self, key: str, embedding: list[float]) -> None:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval(
                "SELECT embedding_cache_upsert($1,$2,$3::double precision[])",
                key, self._model, embedding,
            )

    def flush(self) -> None:
        """No-op: PG writes are synchronous (no local buffer to flush)."""

    def clear(self) -> None:
        """Clear all cached entries for this model from PG."""
        if self._pg_ready():
            try:
                _run_async_from_sync(self._pg_clear_async())
            except Exception:
                pass

    async def _pg_clear_async(self) -> None:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM embedding_cache WHERE model=$1",
                self._model,
            )

    # ── internal helpers ───────────────────────────────────────

    def _key(self, text: str) -> str:
        """Derive a stable cache key from text content + model name."""
        raw = f"{text}||{self._model}".encode("utf-8")
        return hashlib.md5(raw, usedforsecurity=False).hexdigest()


def make_cached_embed_func(
    raw_embed_func: Callable,
    working_dir: str,
    model: str,
) -> Callable:
    """Wrap an async embedding function with PG-backed caching.

    Args:
        raw_embed_func: The underlying embedding function
            (``openai_embed.func`` wrapped with ``partial``).
        working_dir: KB working directory (unused — kept for API compatibility).
        model: Embedding model name (used to namespace cache keys).

    Returns:
        An async function with the same signature that checks cache
        before calling the API. Only uncached texts are sent to the API;
        hits are returned immediately.

    Feature gate:
        Set ``EMBEDDING_CACHE_ENABLED=false`` to disable caching at runtime.
    """
    enabled = os.getenv("EMBEDDING_CACHE_ENABLED", "true").lower() == "true"
    cache = EmbeddingCache(working_dir, model, enabled=enabled)

    log_prefix = "" if enabled else " (DISABLED via EMBEDDING_CACHE_ENABLED=false)"
    logger.info(
        "Embedding cache: %s model=%s dir=%s%s",
        "ENABLED" if enabled else "DISABLED",
        model,
        working_dir,
        log_prefix,
    )

    async def cached_embed(texts: list[str], **kwargs) -> np.ndarray:
        """Embed texts with PG cache.

        For each text, check cache → return hit immediately.
        Batch API call for misses only.
        """
        if not enabled or not texts:
            return await raw_embed_func(texts, **kwargs)

        results: list[Optional[np.ndarray]] = [None] * len(texts)
        missed_indices: list[int] = []
        missed_texts: list[str] = []
        hits = 0

        for i, text in enumerate(texts):
            cached = cache.get(text)
            if cached is not None:
                results[i] = np.array(cached, dtype=np.float32)
                hits += 1
            else:
                missed_indices.append(i)
                missed_texts.append(text)

        if hits:
            logger.debug(
                "Embedding cache: %d/%d hits, %d API calls needed",
                hits, len(texts), len(missed_texts),
            )

        if missed_texts:
            api_results = await raw_embed_func(missed_texts, **kwargs)
            for j, (idx, emb) in enumerate(zip(missed_indices, api_results)):
                results[idx] = emb
                # Cache the result
                vec = emb.tolist() if isinstance(emb, np.ndarray) else list(emb)
                cache.put(missed_texts[j], vec)

        # Assembly: results should never have None at this point
        out = np.stack([r for r in results if r is not None])
        return out

    # Attach cache reference so callers can inspect/flush
    cached_embed.cache = cache  # type: ignore[attr-defined]
    return cached_embed
