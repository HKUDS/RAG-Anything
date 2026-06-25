# -*- coding: utf-8 -*-
"""
Image Vector Repository.

Layer: Infrastructure
Primary Responsibility: Manage the ``image_vision_vdb`` NanoVectorDB —
    upsert, query, delete, and atomic persistence of vision embedding vectors.
Key Dependencies: nano_vectordb, numpy

Security note: This repository writes to disk with atomic rename (tmp + replace)
to prevent JSON corruption on mid-write crashes. A backup file (``.bak``) is
kept for disaster recovery.
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
from nano_vectordb import NanoVectorDB

logger = logging.getLogger(__name__)

# ── VDB field constants (matching NanoVectorDB internals) ──
_F_ID = "__id__"
_F_VECTOR = "__vector__"
_METRIC = "cosine"


class ImageVectorRepository:
    """Persistent vision embedding storage with atomic writes.

    Each KB gets its own ``vdb_image_vision.json`` file inside its
    storage directory. The repository manages the NanoVectorDB lifecycle
    and provides high-level CRUD operations.

    Usage::

        repo = ImageVectorRepository(working_dir="./rag_storage")
        await repo.initialize(embedding_dim=2048)
        await repo.upsert("img-hash123", vector, metadata)
        results = await repo.query(query_vector, top_k=10)
    """

    def __init__(self, working_dir: str):
        self._working_dir = working_dir
        self._db_path = os.path.join(working_dir, "vdb_image_vision.json")
        self._bak_path = self._db_path + ".bak"
        self._vdb: Optional[NanoVectorDB] = None
        self._dim: int = 0
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────

    async def initialize(self, embedding_dim: int) -> None:
        """Create or load the NanoVectorDB instance.

        Must be called once before any CRUD operations. Safe to call
        multiple times — subsequent calls are no-ops if already initialized.
        """
        async with self._lock:
            if self._vdb is not None:
                if self._dim != embedding_dim:
                    raise ValueError(
                        f"ImageVectorRepository dimension mismatch: "
                        f"initialized with {self._dim}, requested {embedding_dim}"
                    )
                return

            # Try loading from disk; if it fails (corruption), try backup
            storage_ok = self._probe_storage(embedding_dim)
            if not storage_ok:
                logger.warning(
                    "[vision-repo] Primary VDB unreadable, trying backup"
                )
                if os.path.exists(self._bak_path):
                    try:
                        os.replace(self._bak_path, self._db_path)
                        storage_ok = self._probe_storage(embedding_dim)
                    except OSError:
                        pass

            self._dim = embedding_dim
            self._vdb = NanoVectorDB(
                embedding_dim=embedding_dim,
                storage_file=self._db_path,
                metric=_METRIC,
            )
            count = len(self._vdb)
            logger.info(
                "[vision-repo] Initialized dim=%d path=%s count=%d",
                embedding_dim, self._db_path, count,
            )

    def _probe_storage(self, embedding_dim: int) -> bool:
        """Check if the on-disk file is loadable and dimension-compatible."""
        if not os.path.exists(self._db_path):
            return True  # fresh start, no file yet
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                storage = json.load(f)
            if storage.get("embedding_dim") != embedding_dim:
                logger.warning(
                    "[vision-repo] Dimension changed %d→%d — reinitializing",
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

    async def upsert(
        self,
        image_hash: str,
        vector: np.ndarray,
        metadata: dict,
    ) -> None:
        """Insert or update a vision vector.

        Args:
            image_hash: SHA-256 content hash (used as primary key).
            vector: Float32 numpy array of shape (dim,).
            metadata: Dict with at least ``entity_name``, ``image_path``,
                ``doc_id``. Stored alongside the vector for retrieval.
        """
        if self._vdb is None:
            raise RuntimeError("ImageVectorRepository not initialized")

        # Build NanoVectorDB entry
        # The VDB uses __id__ as primary key; upsert on same key replaces.
        record_id = f"img-{image_hash}"
        entry = {
            _F_ID: record_id,
            _F_VECTOR: vector.astype(np.float32),
            "entity_name": metadata.get("entity_name", ""),
            "entity_type": metadata.get("entity_type", "image"),
            "image_path": metadata.get("image_path", ""),
            "doc_id": metadata.get("doc_id", ""),
            "file_path": metadata.get("file_path", ""),
            "description": metadata.get("description", "")[:500],
            "vision_model": metadata.get("vision_model", ""),
            "image_hash": image_hash,
            "created_at": int(time.time()),
        }

        async with self._lock:
            self._vdb.upsert([entry])

    async def query(
        self, vector: np.ndarray, top_k: int = 10
    ) -> list[dict]:
        """Find the *top_k* most similar images to *vector*.

        Returns a list of metadata dicts, each with an added ``_score``
        field (cosine similarity, higher = more similar).
        """
        if self._vdb is None:
            return []

        async with self._lock:
            results = self._vdb.query(
                vector.astype(np.float32),
                top_k=min(top_k, len(self._vdb)),
            )

        # NanoVectorDB stores similarity as __metrics__ (line 190 of dbs.py)
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
        if self._vdb is None:
            return 0

        async with self._lock:
            ids_to_delete = [
                d[_F_ID] for d in self._vdb._NanoVectorDB__storage["data"]
                if d.get("doc_id") == doc_id
            ]
            if ids_to_delete:
                self._vdb.delete(ids_to_delete)
                logger.info(
                    "[vision-repo] Deleted %d vectors for doc_id=%s",
                    len(ids_to_delete), doc_id,
                )
            return len(ids_to_delete)

    def count(self) -> int:
        """Number of stored vectors (0 if not initialized)."""
        if self._vdb is None:
            return 0
        return len(self._vdb)

    async def reload(self) -> None:
        """Reload the VDB from disk if it has been modified by another process.

        This is necessary because the worker subprocess writes vision embeddings
        to the shared VDB file, but the server's in-memory NanoVectorDB instance
        was loaded before those writes.
        """
        if self._vdb is None:
            return
        async with self._lock:
            if not os.path.exists(self._db_path):
                return
            try:
                with open(self._db_path, "r", encoding="utf-8") as f:
                    storage = json.load(f)
                new_data = storage.get("data", [])
                current_count = len(self._vdb)
                if len(new_data) > current_count:
                    # Re-instantiate VDB to pick up new entries
                    self._vdb = NanoVectorDB(
                        embedding_dim=self._dim,
                        storage_file=self._db_path,
                        metric=_METRIC,
                    )
                    logger.info(
                        "[vision-repo] Reloaded VDB from disk: %d -> %d entries",
                        current_count, len(self._vdb),
                    )
            except Exception as e:
                logger.warning("[vision-repo] Reload failed: %s", e)

    # ── Persistence ──────────────────────────────────────

    async def flush(self) -> None:
        """Persist in-memory state to disk atomically.

        Uses write-to-tmp + validate + rename pattern to prevent
        truncation/corruption on mid-write crashes.
        """
        if self._vdb is None:
            return

        async with self._lock:
            # 1. Save to temp file
            tmp_path = self._db_path + ".tmp"
            self._vdb.storage_file = tmp_path
            try:
                self._vdb.save()
            finally:
                self._vdb.storage_file = self._db_path

            # 2. Validate temp file is loadable
            try:
                with open(tmp_path, "r", encoding="utf-8") as f:
                    storage = json.load(f)
                assert storage.get("embedding_dim") == self._dim, \
                    f"Dimension mismatch in saved file: {storage.get('embedding_dim')}"
            except Exception as e:
                logger.error("[vision-repo] Temp file validation failed: %s", e)
                raise

            # 3. Rotate: current → .bak, tmp → current
            if os.path.exists(self._db_path):
                try:
                    os.replace(self._db_path, self._bak_path)
                except OSError as e:
                    logger.warning("[vision-repo] Backup rotation failed: %s", e)
            os.replace(tmp_path, self._db_path)

            count = len(self._vdb)
            fsize = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0
            logger.debug(
                "[vision-repo] Flushed %d vectors, file=%d bytes",
                count, fsize,
            )

    # ── Utility ──────────────────────────────────────────

    @staticmethod
    def compute_image_hash(image_path: str) -> str:
        """SHA-256 of raw image bytes (first 64 KiB for speed)."""
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            h.update(f.read(65536))
        return h.hexdigest()[:16]


__all__ = ["ImageVectorRepository"]
