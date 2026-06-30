# -*- coding: utf-8 -*-
"""
Image Vector Repository — PG-backed (Phase 2 migration).

Primary: PostgreSQL ``image_vision_vectors`` table with native
          ``double precision[]`` array vectors + ``array_cosine_similarity()``.
Fallback: NanoVectorDB JSON file (``vdb_image_vision.json``) when PG is
          not configured or pg pool is not initialized.

The public API (``initialize``, ``upsert``, ``query``, ``delete_by_doc_id``,
``count``, ``reload``, ``flush``, ``close``, ``compute_image_hash``) is
unchanged so existing callers in ``image.py`` and ``knowledge.py`` continue
to work without modification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _pg_available() -> bool:
    """Check if PG pool is initialized and ready."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False


# ── PG Query Templates (pgvector, cosine distance via <=>) ──

_PG_UPSERT_SQL = """
INSERT INTO image_vision_vectors
    (id, image_hash, doc_id, entity_name, entity_type, image_path,
     file_path, description, vision_model, embedding, created_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::vector,$11)
ON CONFLICT (id) DO UPDATE SET
    entity_name   = EXCLUDED.entity_name,
    image_path    = EXCLUDED.image_path,
    doc_id        = EXCLUDED.doc_id,
    file_path     = EXCLUDED.file_path,
    description   = EXCLUDED.description,
    vision_model  = EXCLUDED.vision_model,
    embedding     = EXCLUDED.embedding,
    created_at    = EXCLUDED.created_at
"""

_PG_SEARCH_SQL = """
SELECT id, image_hash, doc_id, entity_name, entity_type,
       image_path, file_path, description, vision_model,
       created_at,
       1 - (embedding <=> $1::vector) AS score
FROM image_vision_vectors
ORDER BY embedding <=> $1::vector
LIMIT $2
"""


class ImageVectorRepository:
    """Persistent vision embedding storage — PG-first with NanoVectorDB fallback.

    Each KB gets its own data via the PG table (shared across workers).
    When PG is unavailable, falls back to ``vdb_image_vision.json``.

    Usage::

        repo = ImageVectorRepository(working_dir="./rag_storage")
        await repo.initialize(embedding_dim=2048)
        await repo.upsert("img-hash123", vector, metadata)
        results = await repo.query(query_vector, top_k=10)
    """

    # ── VDB field constants (for NanoVectorDB fallback) ──────
    _F_ID = "__id__"
    _F_VECTOR = "__vector__"
    _METRIC = "cosine"

    def __init__(self, working_dir: str):
        self._working_dir = working_dir
        self._db_path = os.path.join(working_dir, "vdb_image_vision.json")
        self._bak_path = self._db_path + ".bak"
        self._vdb = None  # NanoVectorDB instance (fallback only)
        self._dim: int = 0
        self._lock = asyncio.Lock()
        self._use_pg: bool | None = None  # None = not yet detected

    # ── Lifecycle ─────────────────────────────────────────

    async def initialize(self, embedding_dim: int) -> None:
        """Create or load storage. PG auto-creates table. NVDB loads from disk."""
        async with self._lock:
            if self._dim != 0:
                if self._dim != embedding_dim:
                    raise ValueError(
                        f"ImageVectorRepository dimension mismatch: "
                        f"initialized with {self._dim}, requested {embedding_dim}"
                    )
                return

            self._dim = embedding_dim
            self._use_pg = _pg_available()

            if self._use_pg:
                logger.info(
                    "[vision-repo] PG backend active (dim=%d)", embedding_dim
                )
            else:
                # Fallback: NanoVectorDB
                from nano_vectordb import NanoVectorDB

                storage_ok = self._probe_nvdb_storage(embedding_dim)
                if not storage_ok:
                    logger.warning("[vision-repo] Primary VDB unreadable, trying backup")
                    if os.path.exists(self._bak_path):
                        try:
                            os.replace(self._bak_path, self._db_path)
                            storage_ok = self._probe_nvdb_storage(embedding_dim)
                        except OSError:
                            pass

                self._vdb = NanoVectorDB(
                    embedding_dim=embedding_dim,
                    storage_file=self._db_path,
                    metric=self._METRIC,
                )
                logger.info(
                    "[vision-repo] NanoVectorDB fallback active dim=%d count=%d",
                    embedding_dim, len(self._vdb),
                )

    def _probe_nvdb_storage(self, embedding_dim: int) -> bool:
        """Check if on-disk NVDB file is loadable and dimension-compatible."""
        if not os.path.exists(self._db_path):
            return True
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                storage = json.load(f)
            if storage.get("embedding_dim") != embedding_dim:
                logger.warning(
                    "[vision-repo] Dimension changed %d->%d — reinitializing",
                    storage.get("embedding_dim"), embedding_dim,
                )
                return False
            return True
        except (json.JSONDecodeError, KeyError, OSError):
            return False

    async def close(self) -> None:
        """Flush and release resources."""
        await self.flush()

    # ── CRUD ─────────────────────────────────────────────

    @staticmethod
    def _vec_to_pg(vector: np.ndarray) -> str:
        """Convert numpy vector to pgvector string format '[x1,x2,...]'."""
        arr = vector.astype(np.float32).ravel()
        return "[" + ",".join(str(float(x)) for x in arr) + "]"

    async def upsert(
        self,
        image_hash: str,
        vector: np.ndarray,
        metadata: dict,
    ) -> None:
        """Insert or update a vision vector (PG direct or NVDB upsert).

        Args:
            image_hash: SHA-256 content hash (first 16 hex chars).
            vector: Float32 numpy array of shape (dim,).
            metadata: Dict with entity_name, image_path, doc_id, etc.
        """
        record_id = f"img-{image_hash}"
        entity_name = metadata.get("entity_name", "")
        entity_type = metadata.get("entity_type", "image")
        image_path = metadata.get("image_path", "")
        doc_id = metadata.get("doc_id", "")
        file_path = metadata.get("file_path", "")
        description = (metadata.get("description", "") or "")[:500]
        vision_model = metadata.get("vision_model", "")
        created_at = int(time.time())

        if self._use_pg:
            from raganything.services.pg_state_repo import get_pg_pool

            pool = get_pg_pool()
            vec_str = self._vec_to_pg(vector)
            async with pool.acquire() as conn:
                await conn.execute(
                    _PG_UPSERT_SQL,
                    record_id, image_hash, doc_id, entity_name, entity_type,
                    image_path, file_path, description, vision_model,
                    vec_str, created_at,
                )
        else:
            if self._vdb is None:
                raise RuntimeError("ImageVectorRepository not initialized")
            entry = {
                self._F_ID: record_id,
                self._F_VECTOR: vector.astype(np.float32),
                "entity_name": entity_name,
                "entity_type": entity_type,
                "image_path": image_path,
                "doc_id": doc_id,
                "file_path": file_path,
                "description": description,
                "vision_model": vision_model,
                "image_hash": image_hash,
                "created_at": created_at,
            }
            async with self._lock:
                self._vdb.upsert([entry])

    async def query(
        self, vector: np.ndarray, top_k: int = 10
    ) -> list[dict]:
        """Find top_k most similar images by cosine distance.

        Returns list of metadata dicts with added ``_score`` field.
        """
        if self._use_pg:
            from raganything.services.pg_state_repo import get_pg_pool

            pool = get_pg_pool()
            vec_str = self._vec_to_pg(vector)
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    _PG_SEARCH_SQL, vec_str, top_k
                )
            return [dict(r) for r in rows]

        # Fallback: NanoVectorDB
        if self._vdb is None:
            return []

        async with self._lock:
            count = len(self._vdb)
            if count == 0:
                return []
            results = self._vdb.query(
                vector.astype(np.float32),
                top_k=min(top_k, count),
            )

        enriched = []
        for r in results:
            score = r.get("__metrics__", 0)
            if isinstance(score, (np.floating, np.integer)):
                score = float(score)
            r["_score"] = float(score) if score else 0.0
            enriched.append(r)
        return enriched

    async def delete_by_doc_id(self, doc_id: str) -> int:
        """Remove all vision vectors belonging to a document.

        Returns the number of entries deleted.
        """
        if self._use_pg:
            from raganything.services.pg_state_repo import get_pg_pool

            pool = get_pg_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM image_vision_vectors WHERE doc_id = $1",
                    doc_id,
                )
            # asyncpg returns "DELETE N", parse N
            deleted = 0
            if result:
                parts = result.split()
                if parts:
                    try:
                        deleted = int(parts[-1])
                    except ValueError:
                        pass
            if deleted > 0:
                logger.info(
                    "[vision-repo] PG: deleted %d vectors for doc_id=%s",
                    deleted, doc_id,
                )
            return deleted

        # Fallback: NanoVectorDB
        if self._vdb is None:
            return 0

        async with self._lock:
            ids_to_delete = [
                d[self._F_ID] for d in self._vdb._NanoVectorDB__storage["data"]
                if d.get("doc_id") == doc_id
            ]
            if ids_to_delete:
                self._vdb.delete(ids_to_delete)
                logger.info(
                    "[vision-repo] NVDB: deleted %d vectors for doc_id=%s",
                    len(ids_to_delete), doc_id,
                )
            return len(ids_to_delete)

    def count(self) -> int:
        """Number of stored vectors.

        Note: PG count is approximate (not locked). Use for monitoring only.
        """
        if self._use_pg:
            # Synchronous PG count — used in startup logging, not hot path
            import asyncio as _syncio
            try:
                loop = _syncio.get_running_loop()
            except RuntimeError:
                return 0  # No running loop, can't query

            async def _pg_count():
                from raganything.services.pg_state_repo import get_pg_pool
                pool = get_pg_pool()
                async with pool.acquire() as conn:
                    return await conn.fetchval(
                        "SELECT count(*) FROM image_vision_vectors"
                    )

            future = _syncio.run_coroutine_threadsafe(_pg_count(), loop)
            try:
                return future.result(timeout=3)
            except Exception:
                return 0

        if self._vdb is None:
            return 0
        return len(self._vdb)

    async def reload(self) -> None:
        """PG: no-op (always consistent). NVDB: reload from disk.

        NVDB reload is needed because worker subprocesses write to the shared
        VDB file but the server's in-memory instance was loaded before those writes.
        """
        if self._use_pg:
            return  # PG handles consistency automatically

        if self._vdb is None:
            return

        loop = asyncio.get_running_loop()

        async with self._lock:
            if not os.path.exists(self._db_path):
                return
            try:
                def _read_storage():
                    with open(self._db_path, "r", encoding="utf-8") as f:
                        return json.load(f)

                storage = await loop.run_in_executor(None, _read_storage)
                new_data = storage.get("data", [])
                current_count = len(self._vdb)
                if len(new_data) > current_count:
                    from nano_vectordb import NanoVectorDB
                    self._vdb = NanoVectorDB(
                        embedding_dim=self._dim,
                        storage_file=self._db_path,
                        metric=self._METRIC,
                    )
                    logger.info(
                        "[vision-repo] Reloaded VDB from disk: %d -> %d entries",
                        current_count, len(self._vdb),
                    )
            except Exception as e:
                logger.warning("[vision-repo] Reload failed: %s", e)

    async def flush(self) -> None:
        """PG: no-op (writes are immediate). NVDB: atomic disk persist."""
        if self._use_pg:
            return  # PG writes are immediate, no flush needed

        if self._vdb is None:
            return

        loop = asyncio.get_running_loop()

        async with self._lock:
            tmp_path = self._db_path + ".tmp"
            self._vdb.storage_file = tmp_path
            try:
                await loop.run_in_executor(None, self._vdb.save)
            finally:
                self._vdb.storage_file = self._db_path

            def _validate():
                with open(tmp_path, "r", encoding="utf-8") as f:
                    storage = json.load(f)
                assert storage.get("embedding_dim") == self._dim, \
                    f"Dimension mismatch: {storage.get('embedding_dim')}"
                return storage

            try:
                await loop.run_in_executor(None, _validate)
            except Exception as e:
                logger.error("[vision-repo] Temp file validation failed: %s", e)
                raise

            def _rotate():
                if os.path.exists(self._db_path):
                    try:
                        os.replace(self._db_path, self._bak_path)
                    except OSError as e:
                        logger.warning("[vision-repo] Backup rotation failed: %s", e)
                os.replace(tmp_path, self._db_path)

            await loop.run_in_executor(None, _rotate)

            count = len(self._vdb)
            fsize = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0
            logger.debug("[vision-repo] Flushed %d vectors, file=%d bytes", count, fsize)

    # ── Utility ──────────────────────────────────────────

    async def get_orphan_ids(self, valid_doc_ids: set[str]) -> list[str]:
        """Return IDs of vectors whose ``doc_id`` is NOT in *valid_doc_ids*.

        Replaces direct ``_NanoVectorDB__storage`` scans in knowledge.py.
        Used by orphan cleanup: removes vision vectors for deleted documents.

        Args:
            valid_doc_ids: Set of document IDs that should have vectors.

        Returns:
            List of ``"img-{hash}"`` IDs to delete.
        """
        if self._use_pg:
            from raganything.services.pg_state_repo import get_pg_pool

            if not valid_doc_ids:
                # All vectors are orphans if no valid docs exist
                pool = get_pg_pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch("SELECT id FROM image_vision_vectors")
                return [r["id"] for r in rows]

            pool = get_pg_pool()
            async with pool.acquire() as conn:
                # Single scan: fetch all (id, doc_id) pairs, filter in Python.
                # For typical KB scale (hundreds of images), this is fine.
                rows = await conn.fetch(
                    "SELECT id, doc_id FROM image_vision_vectors"
                )
            return [r["id"] for r in rows if r["doc_id"] not in valid_doc_ids]

        # Fallback: NanoVectorDB
        if self._vdb is None:
            return []
        async with self._lock:
            return [
                d[self._F_ID]
                for d in self._vdb._NanoVectorDB__storage.get("data", [])
                if d.get("doc_id") not in valid_doc_ids
            ]

    async def delete_by_ids(self, ids: list[str]) -> int:
        """Delete multiple vectors by their IDs. Returns count deleted."""
        if not ids:
            return 0

        if self._use_pg:
            from raganything.services.pg_state_repo import get_pg_pool

            pool = get_pg_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM image_vision_vectors WHERE id = ANY($1)",
                    ids,
                )
            deleted = 0
            if result:
                parts = result.split()
                if parts:
                    try:
                        deleted = int(parts[-1])
                    except ValueError:
                        pass
            return deleted

        # Fallback: NanoVectorDB
        if self._vdb is None:
            return 0
        async with self._lock:
            self._vdb.delete(ids)
        return len(ids)

    @staticmethod
    def compute_image_hash(image_path: str) -> str:
        """SHA-256 of raw image bytes (first 64 KiB for speed)."""
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            h.update(f.read(65536))
        return h.hexdigest()[:16]


__all__ = ["ImageVectorRepository"]
