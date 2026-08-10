# -*- coding: utf-8 -*-
"""PostgreSQL-backed, best-effort cache for text embedding vectors."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Callable, Optional

import numpy as np

__all__ = ["EmbeddingCache", "make_cached_embed_func"]

logger = logging.getLogger("rag_server.embedding_cache")


def _cache_pg_ready() -> bool:
    try:
        from raganything.services.pg_state_repo import get_pg_pool

        get_pg_pool()
        return True
    except RuntimeError:
        return False


class EmbeddingCache:
    """PG-backed key-value cache for text embedding vectors.

    Async methods use the embedding caller's event loop. Synchronous methods
    intentionally degrade to miss/no-op because they cannot safely drive the
    shared asyncpg pool from another loop or thread.
    """

    __slots__ = ("_model", "_enabled", "_use_pg", "_warned_operations")

    def __init__(self, working_dir: str, model: str, enabled: bool = True) -> None:
        self._model = model
        self._enabled = enabled
        self._use_pg: bool | None = None
        self._warned_operations: set[str] = set()

    def _pg_ready(self) -> bool:
        if self._use_pg is True:
            return True
        ready = _cache_pg_ready()
        if ready:
            self._use_pg = True
        return ready

    def _warn_degraded(self, operation: str, exc: Exception) -> None:
        if operation not in self._warned_operations:
            self._warned_operations.add(operation)
            logger.warning(
                "Embedding cache %s degraded (%s)", operation, type(exc).__name__
            )

    @property
    def stats(self) -> dict:
        """Return cache statistics for diagnostics."""
        if not self._enabled:
            backend = "disabled"
        else:
            backend = "postgresql" if self._pg_ready() else "unavailable"
        return {
            "backend": backend,
            "entries": "N/A (PG-backed)",
            "enabled": self._enabled,
            "model": self._model,
        }

    def get(self, text: str) -> Optional[list[float]]:
        """Synchronous compatibility lookup; safely degrades to a miss."""
        return None

    async def get_async(self, text: str) -> Optional[list[float]]:
        """Look up a cached embedding on the caller's active event loop."""
        if not self._enabled or not self._pg_ready():
            return None
        try:
            return await self._pg_get_async(self._key(text))
        except Exception as exc:
            self._warn_degraded("read", exc)
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
        """Synchronous compatibility write; intentionally a safe no-op."""

    async def put_async(self, text: str, embedding: list[float]) -> None:
        """Store an embedding on the caller's active event loop."""
        if not self._enabled or not self._pg_ready():
            return
        try:
            await self._pg_put_async(self._key(text), embedding)
        except Exception as exc:
            self._warn_degraded("write", exc)

    async def _pg_put_async(self, key: str, embedding: list[float]) -> None:
        from raganything.services.pg_state_repo import get_pg_pool

        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.fetchval(
                "SELECT embedding_cache_upsert($1,$2,$3::double precision[])",
                key,
                self._model,
                embedding,
            )

    def flush(self) -> None:
        """No-op: async writes are immediately attempted."""

    def clear(self) -> None:
        """Synchronous compatibility clear; intentionally a safe no-op."""

    async def clear_async(self) -> None:
        """Clear this model's cached entries on the caller's active loop."""
        if not self._enabled or not self._pg_ready():
            return
        try:
            await self._pg_clear_async()
        except Exception as exc:
            self._warn_degraded("clear", exc)

    async def _pg_clear_async(self) -> None:
        from raganything.services.pg_state_repo import get_pg_pool

        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM embedding_cache WHERE model=$1", self._model
            )

    def _key(self, text: str) -> str:
        """Derive a stable cache key from text content and model name."""
        raw = f"{text}||{self._model}".encode("utf-8")
        return hashlib.md5(raw, usedforsecurity=False).hexdigest()


def make_cached_embed_func(
    raw_embed_func: Callable,
    working_dir: str,
    model: str,
) -> Callable:
    """Wrap an async embedding function with PG-backed caching."""
    enabled = os.getenv("EMBEDDING_CACHE_ENABLED", "true").lower() == "true"
    cache = EmbeddingCache(working_dir, model, enabled=enabled)

    logger.info(
        "Embedding cache: %s model=%s dir=%s%s",
        "ENABLED" if enabled else "DISABLED",
        model,
        working_dir,
        "" if enabled else " (DISABLED via EMBEDDING_CACHE_ENABLED=false)",
    )

    async def cached_embed(texts: list[str], **kwargs) -> np.ndarray:
        """Embed texts while treating cache failures as provider pass-through."""
        if not enabled or not texts:
            return await raw_embed_func(texts, **kwargs)

        results: list[Optional[np.ndarray]] = [None] * len(texts)
        missed_indices: list[int] = []
        missed_texts: list[str] = []
        hits = 0

        for index, text in enumerate(texts):
            cached = await cache.get_async(text)
            if cached is not None:
                results[index] = np.array(cached, dtype=np.float32)
                hits += 1
            else:
                missed_indices.append(index)
                missed_texts.append(text)

        if hits:
            logger.debug(
                "Embedding cache: %d/%d hits, %d API calls needed",
                hits,
                len(texts),
                len(missed_texts),
            )

        if missed_texts:
            api_results = await raw_embed_func(missed_texts, **kwargs)
            for index, embedding in zip(missed_indices, api_results):
                results[index] = embedding
                vector = (
                    embedding.tolist()
                    if isinstance(embedding, np.ndarray)
                    else list(embedding)
                )
                await cache.put_async(texts[index], vector)

        return np.stack([result for result in results if result is not None])

    cached_embed.cache = cache  # type: ignore[attr-defined]
    return cached_embed
