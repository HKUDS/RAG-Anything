# -*- coding: utf-8 -*-
"""
Embedding Cache — local persistent cache for text embedding vectors.

Avoids redundant API calls by storing (text_hash → embedding_vector) in a
JSON file under the working directory. Uses atomic writes to prevent
corruption on abrupt shutdown.

Feature-gated: disabled when ``EMBEDDING_CACHE_ENABLED`` is "false".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np

__all__ = ["EmbeddingCache", "make_cached_embed_func"]

logger = logging.getLogger("rag_server.embedding_cache")

# Maximum number of cached embedding entries before eviction kicks in.
# Each entry is approximately 8 KB (1024-dim float32 → JSON). At 50 000
# entries the cache file is ~400 MB, which is about the practical limit
# for single-pass json.load on a machine with 2 GB free RAM.
_MAX_CACHE_ENTRIES = int(os.getenv("EMBEDDING_CACHE_MAX_ENTRIES", "50000"))


class EmbeddingCache:
    """Persistent key-value cache for text embedding vectors.

    Keys are MD5 hashes of ``(text, model_name)``.
    Values are ``list[float]`` for JSON serialization.

    Capped at ``EMBEDDING_CACHE_MAX_ENTRIES`` (default 50 000) to prevent
    unbounded growth and MemoryError on save/load.
    """

    __slots__ = ("_cache_path", "_model", "_enabled", "_data",
                 "_loaded", "_dirty", "_max_entries")

    def __init__(self, working_dir: str, model: str, enabled: bool = True) -> None:
        self._cache_path = Path(working_dir) / ".embedding_cache.json"
        self._model = model
        self._enabled = enabled
        self._data: dict[str, list[float]] = {}
        self._loaded = False
        self._dirty = False
        self._max_entries = _MAX_CACHE_ENTRIES

    # ── public API ─────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """Return cache statistics for diagnostics."""
        return {
            "path": str(self._cache_path),
            "entries": len(self._data),
            "size_bytes": self._cache_path.stat().st_size if self._cache_path.exists() else 0,
            "enabled": self._enabled,
            "model": self._model,
        }

    def get(self, text: str) -> Optional[list[float]]:
        """Look up a cached embedding by text content.

        Returns ``None`` on miss.
        """
        if not self._enabled:
            return None
        self._ensure_loaded()
        key = self._key(text)
        return self._data.get(key)

    def put(self, text: str, embedding: list[float]) -> None:
        """Store an embedding in the cache and persist immediately.

        If the cache exceeds ``_max_entries``, the oldest entries are
        evicted first (Python 3.7+ dicts preserve insertion order).
        """
        if not self._enabled:
            return
        self._ensure_loaded()
        key = self._key(text)
        self._data[key] = embedding
        self._dirty = True

        # Evict oldest entries if over the cap
        excess = len(self._data) - self._max_entries
        if excess > 0:
            victims = list(self._data.keys())[:excess]
            for k in victims:
                del self._data[k]
            logger.info(
                "Embedding cache evicted %d oldest entries "
                "(now %d/%d)", excess, len(self._data), self._max_entries,
            )

        self._save()

    def flush(self) -> None:
        """Persist cache to disk (no-op if not dirty)."""
        if self._dirty:
            self._save()

    def clear(self) -> None:
        """Clear all cached entries."""
        self._data.clear()
        self._dirty = True
        self._save()

    # ── internal helpers ───────────────────────────────────────

    def _key(self, text: str) -> str:
        """Derive a stable cache key from text content + model name."""
        raw = f"{text}||{self._model}".encode("utf-8")
        return hashlib.md5(raw, usedforsecurity=False).hexdigest()

    def _ensure_loaded(self) -> None:
        """Lazy-load cache from disk on first access."""
        if self._loaded:
            return
        self._loaded = True
        if not self._cache_path.exists():
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
            logger.debug("Embedding cache loaded: %d entries from %s",
                         len(self._data), self._cache_path)
        except MemoryError:
            logger.warning(
                "Embedding cache file too large to load (%s), "
                "starting fresh.  Consider reducing MAX_CACHE_ENTRIES.",
                self._cache_path.stat().st_size if self._cache_path.exists() else 0,
            )
            self._data = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Embedding cache file corrupt (%s), starting fresh", exc
            )
            self._data = {}

    def _save(self) -> None:
        """Atomically write cache to disk (tmp → rename).

        Uses atomic-write pattern: write to .tmp, then os.replace().
        No verification load — that would double memory pressure and
        cause MemoryError on large caches.  If json.dump succeeds the
        output is valid JSON; the only failure mode is a disk-full or
        kernel crash mid-write, which would leave the stale-but-valid
        original file untouched.
        """
        tmp_path = self._cache_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, self._cache_path)
            self._dirty = False
        except (OSError, MemoryError, json.JSONDecodeError) as exc:
            logger.error("Failed to save embedding cache: %s", exc)
            # Don't leave a corrupt tmp file behind
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def make_cached_embed_func(
    raw_embed_func: Callable,
    working_dir: str,
    model: str,
) -> Callable:
    """Wrap an async embedding function with local persistent caching.

    Args:
        raw_embed_func: The underlying embedding function
            (``openai_embed.func`` wrapped with ``partial``).
        working_dir: KB working directory where the cache file will live.
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
        """Embed texts with local cache.

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
        # Pedantic: if all texts were empty strings, we might get empty
        return out

    # Attach cache reference so callers can inspect/flush
    cached_embed.cache = cache  # type: ignore[attr-defined]
    return cached_embed
