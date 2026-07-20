# -*- coding: utf-8 -*-
"""
RAG-Anything Knowledge Base (KB) Service.

Layer: Service
Primary Responsibility: KB instance lifecycle — create, retrieve, delete,
    metadata persistence, RAGAnything factory.
Key Dependencies: raganything (RAGAnything, RAGAnythingConfig), lightrag

Extracted from routers/shared.py. All KB instance management is centralized here.
"""

from __future__ import annotations

import json
import hashlib
from typing import Any, Optional
import os
import sys
import re
import asyncio
import logging
from contextlib import asynccontextmanager
from collections import OrderedDict
from datetime import datetime
from functools import partial
from pathlib import Path
from raganything.services.runtime_settings import bootstrap_runtime_settings

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

bootstrap_runtime_settings()

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from raganything.base import DocStatus
from raganything.embedding import (
    DoubaoEmbeddingAdapter,
    create_vision_embed_func,
    make_cached_embed_func,
)
from raganything.chunking import (
    recursive_chunking,
    sentence_chunking,
    structure_chunking,
    make_semantic_chunking,
    make_agentic_chunking,
)
from raganything.utils import is_multimodal_processed

# ── Configuration ─────────────────────────────────────────
API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
WORKING_DIR = os.getenv("WORKING_DIR", "./rag_storage")
CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "recursive")
MAX_CACHED_KBS = int(os.getenv("MAX_CACHED_KBS", "16"))
_VLM_IMAGE_MIME_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}

# ── KB State ──────────────────────────────────────────────
_kb_locks: dict[str, asyncio.Lock] = {}
_recovery_local_lock = asyncio.Lock()
_RECOVERY_LOCK_NOT_ACQUIRED = object()


class KBCache:
    """LRU-evicting cache for RAGAnything KB instances.

    Replaces the plain ``kb_instances`` dict.  Follows the QueryCache
    pattern (OrderedDict + LRU) from ``raganything/query_cache.py``,
    adapted for async eviction of heavyweight (~2 GB) KB instances.

    Dict-like interface preserved for backward compatibility with
    existing callers in ``admin.py``, ``server.py``, and internal helpers.
    """

    def __init__(self, max_size: int = 16) -> None:
        self._max_size = 0 if max_size < 0 else max_size
        self._store: OrderedDict[str, RAGAnything] = OrderedDict()
        self._cache_time: dict[str, float] = {}
        self._pinned: set[str] = set()
        self._eviction_lock = asyncio.Lock()
        # -- stats --
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0
        self._total_loads: int = 0

    # ── Dict-like interface (synchronous / backward compat) ──

    def __contains__(self, name: str) -> bool:
        return name in self._store

    def __getitem__(self, name: str) -> RAGAnything:
        val = self._store[name]
        self._store.move_to_end(name)  # LRU: mark recently used
        self.hits += 1
        return val

    def __delitem__(self, name: str) -> None:
        """Remove an entry WITHOUT calling finalize_storages().

        Caller is responsible for calling finalize_storages() first
        when needed (e.g. reload-kb, cleanup_kb_resources).
        """
        self._store.pop(name, None)
        self._cache_time.pop(name, None)

    def __len__(self) -> int:
        return len(self._store)

    def keys(self):
        return self._store.keys()

    def items(self):
        return self._store.items()

    def values(self):
        return self._store.values()

    def get(self, name: str, default=None):
        """Safe access with default.  LRU touch on hit."""
        if name in self._store:
            self._store.move_to_end(name)
            self.hits += 1
            return self._store[name]
        self.misses += 1
        return default

    # ── Cache-time accessors (replaces _kb_cache_time dict) ──

    def get_cache_time(self, name: str) -> float:
        return self._cache_time.get(name, 0.0)

    def set_cache_time(self, name: str, t: float) -> None:
        self._cache_time[name] = t

    def remove_cache_time(self, name: str) -> None:
        self._cache_time.pop(name, None)

    # ── Async store + evict ─────────────────────────────────

    async def put_and_evict(self, name: str, instance: RAGAnything,
                            cache_time: float) -> None:
        """Store a KB instance and evict LRU entries if over capacity.

        When ``max_size`` is 0 (unlimited), eviction is skipped entirely
        (backward-compatible with the old plain-dict behaviour).
        """
        self._store[name] = instance
        self._cache_time[name] = cache_time
        self._store.move_to_end(name)
        self._total_loads += 1
        await self._evict_if_needed()

    async def evict(self, name: str) -> bool:
        """Safely evict a single KB: persist first, then remove.

        Returns False if the KB is pinned or not found.
        """
        if name not in self._store:
            return False
        if name in self._pinned:
            kb_logger.info(f"[KB-CACHE] 跳过淘汰（已固定）: {name}")
            return False
        await self._evict_one(name)
        return True

    async def clear(self) -> None:
        """Clear all entries (persist each first, then clear)."""
        async with self._eviction_lock:
            for name in list(self._store.keys()):
                try:
                    await self._store[name].finalize_storages()
                except Exception:
                    pass
            self._store.clear()
            self._cache_time.clear()

    # ── Pin management ──────────────────────────────────────

    def pin(self, name: str) -> None:
        self._pinned.add(name)

    def unpin(self, name: str) -> None:
        self._pinned.discard(name)

    def is_pinned(self, name: str) -> bool:
        return name in self._pinned

    # ── Dirty check ─────────────────────────────────────────

    def is_dirty(self, name: str) -> bool:
        """Return True if the KB has active processing — do NOT evict."""
        # Active worker subprocesses
        if name in _kb_worker_procs and _kb_worker_procs[name]:
            return True
        # Queue drain in progress
        import raganything.routers.shared as _rshared
        if _rshared._kb_draining.get(name):
            return True
        # File processing in flight
        for (kb_n, _fh) in _processing_files:
            if kb_n == name:
                return True
        # Mid-deletion
        if name in _kbs_being_deleted:
            return True
        return False

    # ── Stats ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_cached": len(self._store),
            "max_size": self._max_size,
            "pinned": sorted(self._pinned),
            "pinned_count": len(self._pinned),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "total_loads": self._total_loads,
            "cached_kbs": list(self._store.keys()),
            "hit_rate": round(
                self.hits / max(self.hits + self.misses, 1), 3
            ),
        }

    # ── Internal ────────────────────────────────────────────

    def _find_eviction_victim(self) -> str | None:
        """Find oldest entry that is not pinned and not dirty."""
        for name in self._store:
            if name in self._pinned:
                continue
            if self.is_dirty(name):
                continue
            return name
        return None

    async def _evict_one(self, name: str) -> None:
        kb_logger.info(
            f"[KB-CACHE] 淘汰 KB 实例: {name} "
            f"(缓存={len(self._store)}/{self._max_size})"
        )
        try:
            await self._store[name].finalize_storages()
        except Exception as exc:
            kb_logger.warning(
                f"[KB-CACHE] finalize_storages 失败（淘汰）: {name}: {exc}"
            )
        del self._store[name]
        self._cache_time.pop(name, None)
        self.evictions += 1

    async def _evict_if_needed(self) -> None:
        """Evict LRU entries until we are within max_size.

        Acquires internal ``_eviction_lock`` to serialize with
        concurrent evictions.  Does NOT hold any per-KB ``_kb_locks``,
        so it cannot deadlock with ``get_kb()`` on other KBs.
        """
        if self._max_size == 0:
            return  # unlimited — backward-compatible old behaviour
        async with self._eviction_lock:
            while len(self._store) > self._max_size:
                victim = self._find_eviction_victim()
                if victim is None:
                    kb_logger.warning(
                        f"[KB-CACHE] 超出容量但无可淘汰 KB "
                        f"(全部固定或处理中): "
                        f"cached={len(self._store)} max={self._max_size}"
                    )
                    break
                await self._evict_one(victim)


# ── KB Instances ──────────────────────────────────────────
kb_instances = KBCache(max_size=MAX_CACHED_KBS)
kb_instances.pin("default")
active_kb: str = "default"
KB_META_FILE = None  # Deprecated: KB metadata is now PG-backed

kb_logger = logging.getLogger("rag_server.kb")

# ── Queue sentinel — tells drain coroutine to exit ──────────
_QUEUE_SENTINEL = object()

# ── KBs currently being deleted — set BEFORE any async yield ─
# Used by _process_uploaded_file except block to skip state writes
# for KBs that are mid-deletion (avoids zombie processing_tasks entries).
_kbs_being_deleted: set[str] = set()

# ── Upload Dedup Tracking ───────────────────────────────────
# Maps (kb_name, file_hash) -> task_id for active processing tasks.
# Entries are removed when the worker completes or fails.
_processing_files: dict[tuple[str, str], str] = {}


def _scale_progress(done: int, total: int, start: int, end: int) -> int:
    """Scale a counted sub-step into a bounded 0-100 progress range."""
    if end <= start:
        return end
    if total <= 0:
        return end

    clamped_done = max(0, min(done, total))
    ratio = clamped_done / total
    return max(start, min(end, int(round(start + (end - start) * ratio))))


def _parse_worker_progress_line(line: str, state: dict[str, Any]) -> dict[str, Any] | None:
    """Convert worker log lines into more truthful progress updates when possible."""
    text = line.strip()
    if not text:
        return None

    if "[PROGRESS] phase=parsing status=start" in text:
        state["track"] = "text"
        return {
            "phase": "parsing",
            "phase_status": "start",
            "message": "解析文档中",
        }

    if "[PROGRESS] phase=parsing status=done" in text:
        return {
            "phase": "parsing",
            "phase_status": "done",
            "progress": 25,
            "message": "文档解析完成",
        }

    match = re.search(r"Parsing .+ complete! Extracted (\d+) content blocks", text)
    if match:
        state["track"] = "text"
        blocks = int(match.group(1))
        return {
            "phase": "parsing",
            "phase_status": "done",
            "progress": 25,
            "message": f"文档解析完成（{blocks} 个内容块）",
        }

    if "Starting text content insertion into LightRAG..." in text:
        state["track"] = "text"
        return {
            "phase": "entity-extraction",
            "phase_status": "start",
            "progress": 28,
            "message": "开始抽取文本实体与关系",
        }

    if "Starting multimodal content processing..." in text:
        state["track"] = "multimodal"
        return {
            "phase": "multimodal-tasks",
            "phase_status": "start",
            "progress": 90,
            "message": "开始处理图片、表格等多模态内容",
        }

    match = re.search(r"Multimodal chunk generation progress:\s*(\d+)/(\d+)", text)
    if match:
        state["track"] = "multimodal"
        done = int(match.group(1))
        total = int(match.group(2))
        return {
            "phase": "multimodal-tasks",
            "phase_status": "describing",
            "progress": _scale_progress(done, total, 91, 94),
            "message": f"多模态内容生成 {done}/{total}",
        }

    match = re.search(r"Generated descriptions for (\d+)/(\d+) multimodal items", text)
    if match:
        state["track"] = "multimodal"
        done = int(match.group(1))
        total = int(match.group(2))
        return {
            "phase": "multimodal-tasks",
            "phase_status": "describing",
            "progress": _scale_progress(done, total, 91, 94),
            "message": f"多模态描述生成完成 {done}/{total}",
        }

    match = re.search(r"Stored (\d+) multimodal chunks to storage", text)
    if match:
        state["track"] = "multimodal"
        chunk_count = int(match.group(1))
        return {
            "phase": "multimodal-tasks",
            "phase_status": "stored",
            "progress": 95,
            "message": f"多模态内容已入库（{chunk_count} 个块）",
        }

    match = re.search(r"Chunk (\d+) of (\d+) extracted", text)
    if match:
        done = int(match.group(1))
        total = int(match.group(2))
        if state.get("track") == "multimodal":
            return {
                "phase": "multimodal-tasks",
                "phase_status": "extracting",
                "progress": _scale_progress(done, total, 95, 97),
                "message": f"多模态实体抽取 {done}/{total}",
            }
        return {
            "phase": "entity-extraction",
            "phase_status": "extracting",
            "progress": _scale_progress(done, total, 30, 70),
            "message": f"文本实体抽取 {done}/{total}",
        }

    if re.search(r"Extracted entities from (\d+) multimodal chunks", text):
        state["track"] = "multimodal"
        return {
            "phase": "multimodal-tasks",
            "phase_status": "extracted",
            "progress": 97,
            "message": "多模态实体抽取完成",
        }

    if re.search(r"Phase 1:\s+Processing\s+\d+\s+entities", text):
        multimodal = state.get("track") == "multimodal"
        return {
            "phase": "graph-building",
            "phase_status": "entities",
            "progress": 97 if multimodal else 72,
            "message": "正在合并实体",
        }

    if re.search(r"Phase 2:\s+Processing\s+\d+\s+relations", text):
        multimodal = state.get("track") == "multimodal"
        return {
            "phase": "graph-building",
            "phase_status": "relations",
            "progress": 98 if multimodal else 82,
            "message": "正在合并关系",
        }

    if re.search(r"Phase 3:\s+Updating final", text):
        multimodal = state.get("track") == "multimodal"
        return {
            "phase": "graph-building",
            "phase_status": "finalizing",
            "progress": 99 if multimodal else 90,
            "message": "正在写入最终结果",
        }

    if "Document " in text and " processing complete!" in text:
        return {
            "phase": "graph-building",
            "phase_status": "finalizing",
            "progress": 99,
            "message": "文档处理完成，正在收尾",
        }

    return None

# ── Worker Process Tracking ─────────────────────────────────
# Maps kb_name -> list of (asyncio.subprocess.Process, task_id) for
# running worker subprocesses.  Used by KB deletion to kill workers.
_kb_worker_procs: dict[str, list] = {}

_WORKER_NUMERIC_THREAD_ENV = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _worker_subprocess_env() -> dict[str, str]:
    """Bound numeric-library threads for isolated document workers.

    Docling imports numeric libraries during worker startup.  Letting every
    concurrent worker inherit a host-wide thread count can exhaust memory
    before parsing begins, especially on Windows.
    """
    try:
        threads = int(os.getenv("DOCUMENT_WORKER_MAX_THREADS", "1"))
    except ValueError:
        threads = 1
    threads = max(1, min(threads, 4))
    env = os.environ.copy()
    for name in _WORKER_NUMERIC_THREAD_ENV:
        env[name] = str(threads)
    return env


def _compute_file_hash(file_path: str) -> str:
    """Compute a short content hash for upload deduplication.

    Uses SHA256 on the **first 64 KiB** of the file for speed (uploaded
    files may be hundreds of MB). Returns the first 16 hex chars.
    """
    import hashlib
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


def _is_file_being_processed(kb_name: str, file_hash: str) -> str | None:
    """Check if a file is currently being processed in the given KB.

    Returns:
        The existing task_id if processing, or None.
    """
    return _processing_files.get((kb_name, file_hash))


def _register_processing_file(kb_name: str, file_hash: str, task_id: str) -> None:
    """Register a file as currently being processed."""
    _processing_files[(kb_name, file_hash)] = task_id


def _unregister_processing_file(kb_name: str, file_hash: str) -> None:
    """Remove a file from the processing tracker (called on completion/failure)."""
    _processing_files.pop((kb_name, file_hash), None)


# ── Uploaded File Metadata (PG) ───────────────────────────

_uploaded_files_has_error_message: bool | None = None


def _uploaded_files_supports_error_message() -> bool:
    """Return whether uploaded_files.error_message should be referenced."""
    return _uploaded_files_has_error_message is not False


def _uploaded_files_mark_missing_error_message(exc: Exception) -> bool:
    """Record legacy schema state when uploaded_files.error_message is absent."""
    global _uploaded_files_has_error_message

    if exc.__class__.__name__ != "UndefinedColumnError":
        return False
    if "error_message" not in str(exc):
        return False

    _uploaded_files_has_error_message = False
    kb_logger.warning(
        "uploaded_files.error_message column is missing; falling back to legacy schema compatibility"
    )
    return True


def _uploaded_files_projection(include_error_message: bool) -> str:
    columns = [
        "id",
        "filename",
        "file_path",
        "file_hash",
        "file_size",
        "kb_name",
        "uploaded_by",
        "task_id",
        "status",
    ]
    if include_error_message:
        columns.append("error_message")
    columns.extend(["created_at", "updated_at"])
    return ", ".join(columns)


async def pg_register_upload(
    filename: str,
    file_path: str,
    file_hash: str,
    file_size: int,
    kb_name: str,
    uploaded_by: int,
    task_id: str | None = None,
    status: str = "queued",
) -> dict[str, Any] | None:
    """Insert uploaded file metadata into PG.

    Returns:
        Serialized upload row, or None if a duplicate hash+kb_name exists.
    """
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        include_error_message = _uploaded_files_supports_error_message()
        sql = (
            "INSERT INTO uploaded_files "
            "(filename, file_path, file_hash, file_size, kb_name, uploaded_by, task_id, status) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "ON CONFLICT (file_hash, kb_name) DO UPDATE SET "
            "filename = EXCLUDED.filename, file_path = EXCLUDED.file_path, "
            "file_size = EXCLUDED.file_size, uploaded_by = EXCLUDED.uploaded_by, "
            "task_id = EXCLUDED.task_id, status = EXCLUDED.status, "
            "error_message = '', updated_at = NOW() "
            "WHERE uploaded_files.status = 'deleted' "
            f"RETURNING {_uploaded_files_projection(include_error_message)}"
        )
        try:
            row = await pool.fetchrow(
                sql,
                filename, file_path, file_hash, file_size, kb_name, uploaded_by, task_id, status,
            )
        except Exception as exc:
            if not include_error_message or not _uploaded_files_mark_missing_error_message(exc):
                raise
            row = await pool.fetchrow(
                (
                    "INSERT INTO uploaded_files "
                    "(filename, file_path, file_hash, file_size, kb_name, uploaded_by, task_id, status) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                    "ON CONFLICT (file_hash, kb_name) DO UPDATE SET "
                    "filename = EXCLUDED.filename, file_path = EXCLUDED.file_path, "
                    "file_size = EXCLUDED.file_size, uploaded_by = EXCLUDED.uploaded_by, "
                    "task_id = EXCLUDED.task_id, status = EXCLUDED.status, "
                    "updated_at = NOW() "
                    "WHERE uploaded_files.status = 'deleted' "
                    f"RETURNING {_uploaded_files_projection(False)}"
                ),
                filename, file_path, file_hash, file_size, kb_name, uploaded_by, task_id, status,
            )
        return _serialize_upload_row(row) if row else None
    except Exception:
        kb_logger.warning("PG uploaded_files insert failed", exc_info=True)
        return None


async def pg_mark_upload_reusable(file_hash: str, kb_name: str) -> bool:
    """Release a terminal upload record so a deleted document can be uploaded again."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool

        result = await get_pg_pool().execute(
            """
            UPDATE uploaded_files
            SET status = 'deleted', updated_at = NOW()
            WHERE file_hash = $1 AND kb_name = $2
              AND status = ANY($3::text[])
            """,
            file_hash,
            kb_name,
            ["completed", "failed", "deleted", "uploaded"],
        )
        return int(str(result).split()[-1]) > 0
    except Exception:
        kb_logger.warning(
            "PG uploaded_files stale-record release failed: kb=%s hash=%s",
            kb_name,
            file_hash[:12],
            exc_info=True,
        )
        return False


async def pg_release_upload_for_deleted_document(kb_name: str, file_path: str) -> bool:
    """Mark the upload metadata reusable after its document has been deleted."""
    filename = os.path.basename(str(file_path or ""))
    filename = re.sub(r"^[0-9a-fA-F]{8}_", "", filename)
    if not filename:
        return False
    try:
        from raganything.services.pg_state_repo import get_pg_pool

        result = await get_pg_pool().execute(
            """
            UPDATE uploaded_files
            SET status = 'deleted', updated_at = NOW()
            WHERE kb_name = $1 AND filename = $2
              AND status = ANY($3::text[])
            """,
            kb_name,
            filename,
            ["completed", "failed", "deleted", "uploaded"],
        )
        return int(str(result).split()[-1]) > 0
    except Exception:
        kb_logger.warning(
            "PG uploaded_files document release failed: kb=%s file=%s",
            kb_name,
            filename,
            exc_info=True,
        )
        return False


def _serialize_upload_row(row: Any) -> dict[str, Any]:
    """Normalize an uploaded_files row to a JSON-friendly dict."""
    return {
        "id": row["id"],
        "filename": row["filename"],
        "file_path": row["file_path"],
        "file_hash": row["file_hash"],
        "file_size": row["file_size"],
        "kb_name": row["kb_name"],
        "uploaded_by": row["uploaded_by"],
        "task_id": row["task_id"],
        "status": row["status"],
        "error_message": row.get("error_message", "") if hasattr(row, "get") else row["error_message"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
    }


async def pg_update_upload_status(
    file_hash: str,
    kb_name: str,
    status: str,
    task_id: str | None = None,
    error_message: str | None = None,
) -> bool:
    """Update the status (and optionally task_id) of an uploaded file."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        include_error_message = _uploaded_files_supports_error_message()
        if include_error_message:
            sql = (
                "UPDATE uploaded_files "
                "SET status = $1, "
                "    task_id = COALESCE($2, task_id), "
                "    error_message = COALESCE($3, error_message), "
                "    updated_at = NOW() "
                "WHERE file_hash = $4 AND kb_name = $5"
            )
            params = [status, task_id, error_message, file_hash, kb_name]
        else:
            sql = (
                "UPDATE uploaded_files "
                "SET status = $1, "
                "    task_id = COALESCE($2, task_id), "
                "    updated_at = NOW() "
                "WHERE file_hash = $3 AND kb_name = $4"
            )
            params = [status, task_id, file_hash, kb_name]

        try:
            result = await pool.execute(sql, *params)
        except Exception as exc:
            if not include_error_message or not _uploaded_files_mark_missing_error_message(exc):
                raise
            result = await pool.execute(
                (
                    "UPDATE uploaded_files "
                    "SET status = $1, "
                    "    task_id = COALESCE($2, task_id), "
                    "    updated_at = NOW() "
                    "WHERE file_hash = $3 AND kb_name = $4"
                ),
                status, task_id, file_hash, kb_name,
            )
        # Parse "UPDATE N" output safely — "UPDATE 0" substring would
        # false-match "UPDATE 10", "UPDATE 100", etc.
        try:
            return int(result.split()[-1]) > 0 if result else False
        except (ValueError, IndexError):
            return False
    except Exception:
        kb_logger.warning("PG uploaded_files status update failed", exc_info=True)
        return False


async def pg_update_upload_status_by_task_id(
    task_id: str,
    status: str,
    *,
    kb_name: str = "",
    expected_current_status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    """Update uploaded_files row by task_id and return the updated row."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        include_error_message = _uploaded_files_supports_error_message()
        if include_error_message:
            params: list[Any] = [status, error_message, task_id]
            where = "task_id = $3"
            if kb_name:
                params.append(kb_name)
                where += f" AND kb_name = ${len(params)}"
            if expected_current_status is not None:
                params.append(expected_current_status)
                where += f" AND status = ${len(params)}"
            sql = (
                "UPDATE uploaded_files "
                "SET status = $1, "
                "    error_message = COALESCE($2, error_message), "
                "    updated_at = NOW() "
                f"WHERE {where} "
                f"RETURNING {_uploaded_files_projection(True)}"
            )
        else:
            params = [status, task_id]
            where = "task_id = $2"
            if kb_name:
                params.append(kb_name)
                where += f" AND kb_name = ${len(params)}"
            if expected_current_status is not None:
                params.append(expected_current_status)
                where += f" AND status = ${len(params)}"
            sql = (
                "UPDATE uploaded_files "
                "SET status = $1, "
                "    updated_at = NOW() "
                f"WHERE {where} "
                f"RETURNING {_uploaded_files_projection(False)}"
            )

        try:
            row = await pool.fetchrow(sql, *params)
        except Exception as exc:
            if not include_error_message or not _uploaded_files_mark_missing_error_message(exc):
                raise
            params = [status, task_id]
            where = "task_id = $2"
            if kb_name:
                params.append(kb_name)
                where += f" AND kb_name = ${len(params)}"
            if expected_current_status is not None:
                params.append(expected_current_status)
                where += f" AND status = ${len(params)}"
            row = await pool.fetchrow(
                (
                    "UPDATE uploaded_files "
                    "SET status = $1, "
                    "    updated_at = NOW() "
                    f"WHERE {where} "
                    f"RETURNING {_uploaded_files_projection(False)}"
                ),
                *params,
            )
        return _serialize_upload_row(row) if row else None
    except Exception:
        kb_logger.warning("PG uploaded_files task update failed", exc_info=True)
        return None


async def pg_get_upload_by_task_id(
    task_id: str,
    *,
    kb_name: str = "",
    uploaded_by: int | None = None,
    is_admin: bool = False,
) -> dict[str, Any] | None:
    """Fetch a single uploaded_files row by task_id with optional access filters."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        conditions = ["task_id = $1"]
        params: list[Any] = [task_id]
        idx = 2

        if kb_name:
            conditions.append(f"kb_name = ${idx}")
            params.append(kb_name)
            idx += 1

        if not is_admin and uploaded_by is not None:
            conditions.append(f"(uploaded_by = ${idx} OR uploaded_by = 0)")
            params.append(uploaded_by)
            idx += 1

        where = " AND ".join(conditions)
        async with pool.acquire() as conn:
            include_error_message = _uploaded_files_supports_error_message()
            try:
                row = await conn.fetchrow(
                    f"""SELECT {_uploaded_files_projection(include_error_message)}
                        FROM uploaded_files
                        WHERE {where}
                        LIMIT 1""",
                    *params,
                )
            except Exception as exc:
                if not include_error_message or not _uploaded_files_mark_missing_error_message(exc):
                    raise
                row = await conn.fetchrow(
                    f"""SELECT {_uploaded_files_projection(False)}
                        FROM uploaded_files
                        WHERE {where}
                        LIMIT 1""",
                    *params,
                )
        return _serialize_upload_row(row) if row else None
    except Exception:
        kb_logger.warning("PG uploaded_files lookup failed", exc_info=True)
        return None


async def pg_claim_upload_task(task_id: str, kb_name: str) -> bool:
    """Atomically claim a queued upload task for processing."""
    row = await pg_update_upload_status_by_task_id(
        task_id,
        "processing",
        kb_name=kb_name,
        expected_current_status="queued",
        error_message="",
    )
    return bool(row and row.get("kb_name") == kb_name)


async def pg_list_uploads(
    kb_name: str = "",
    uploaded_by: int | None = None,
    is_admin: bool = False,
    limit: int = 50,
    offset: int = 0,
    exclude_statuses: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List uploaded files from PG with optional filters.

    Args:
        kb_name: Filter by KB name (empty = all KBs)
        uploaded_by: Filter by uploader (non-admin: forced to self)
        is_admin: If True, sees all; if False, sees own + system
        limit: Page size
        offset: Page offset

    Returns:
        List of uploaded file metadata dicts.
    """
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()

        conditions = []
        params: list = []
        idx = 1

        if kb_name:
            conditions.append(f"kb_name = ${idx}")
            params.append(kb_name)
            idx += 1

        if not is_admin and uploaded_by is not None:
            conditions.append(f"(uploaded_by = ${idx} OR uploaded_by = 0)")
            params.append(uploaded_by)
            idx += 1

        if exclude_statuses:
            conditions.append(f"status <> ALL(${idx}::text[])")
            params.append(exclude_statuses)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        async with pool.acquire() as conn:
            include_error_message = _uploaded_files_supports_error_message()
            try:
                rows = await conn.fetch(
                    (
                        f"SELECT {_uploaded_files_projection(include_error_message)} "
                        f"FROM uploaded_files {where} "
                        f"ORDER BY created_at DESC "
                        f"LIMIT ${idx} OFFSET ${idx + 1}"
                    ),
                    *params,
                )
            except Exception as exc:
                if not include_error_message or not _uploaded_files_mark_missing_error_message(exc):
                    raise
                rows = await conn.fetch(
                    (
                        f"SELECT {_uploaded_files_projection(False)} "
                        f"FROM uploaded_files {where} "
                        f"ORDER BY created_at DESC "
                        f"LIMIT ${idx} OFFSET ${idx + 1}"
                    ),
                    *params,
                )
            total_row = await conn.fetchrow(
                f"SELECT count(*) as total FROM uploaded_files {where}",
                *params[:idx - 1],
            )
            total = total_row["total"] if total_row else 0

        return [_serialize_upload_row(r) for r in rows], total

    except Exception:
        kb_logger.warning("PG uploaded_files list failed", exc_info=True)
        return [], 0


async def pg_get_latest_content_updates_batch(kb_names: list[str]) -> dict[str, str]:
    """Return the latest completed or deleted content change for each KB.

    Upload metadata is the durable source for document processing completion and
    document deletion. Callers intentionally receive an empty mapping when PG
    is unavailable so they can fall back to KB creation metadata.
    """
    names = list(dict.fromkeys(name for name in kb_names if name))
    if not names:
        return {}

    try:
        from raganything.services.pg_state_repo import get_pg_pool

        rows = await get_pg_pool().fetch(
            """
            SELECT kb_name, MAX(updated_at) AS last_content_updated_at
            FROM uploaded_files
            WHERE kb_name = ANY($1::text[])
              AND status = ANY($2::text[])
            GROUP BY kb_name
            """,
            names,
            ["completed", "deleted"],
        )
    except Exception:
        kb_logger.warning("PG uploaded_files content-update lookup failed", exc_info=True)
        return {}

    updates: dict[str, str] = {}
    for row in rows:
        timestamp = row["last_content_updated_at"]
        if timestamp is None:
            continue
        updates[str(row["kb_name"])] = (
            timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
        )
    return updates


# ── KB Metadata Persistence ────────────────────────────────
# KB metadata is stored exclusively in PostgreSQL (kb_metadata table).
# See raganything/services/pg_kb_meta_repo.py for the implementation.


# ── PG Storage Backend Helpers ──────────────────────────────
# LightRAG's PGKVStorage / PGDocStatusStorage require POSTGRES_USER,
# POSTGRES_PASSWORD, POSTGRES_DATABASE in os.environ.  Our .env may
# only set DATABASE_URL, so we extract the individual vars from it.


def _ensure_pg_storage_env() -> None:
    """Ensure POSTGRES_* env vars are set (extract from DATABASE_URL if needed).

    LightRAG's ``check_storage_env_vars()`` validates that POSTGRES_USER,
    POSTGRES_PASSWORD, and POSTGRES_DATABASE are present in os.environ
    before allowing PGKVStorage/PGDocStatusStorage to initialize.

    If DATABASE_URL is set but the individual vars are missing, parse them
    from the DSN so LightRAG can pass the check.
    """
    if all(k in os.environ for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE")):
        return  # already configured

    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        return

    # postgresql://user:password@host:port/database
    m = re.match(
        r"postgresql://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/([^?]+)",
        dsn,
    )
    if m:
        os.environ.setdefault("POSTGRES_USER", m.group(1))
        os.environ.setdefault("POSTGRES_PASSWORD", m.group(2))
        os.environ.setdefault("POSTGRES_HOST", m.group(3))
        os.environ.setdefault("POSTGRES_PORT", m.group(4) or "5432")
        os.environ.setdefault("POSTGRES_DATABASE", m.group(5))
        kb_logger.info("PG storage env vars extracted from DATABASE_URL")


def _pg_storage_ready() -> bool:
    """Check if PG is available for LightRAG storage backends.

    Returns True when all of:
      - The PG pool (from pg_state_repo) is initialized
      - Required POSTGRES_* env vars are present (or extracted from DATABASE_URL)
    """
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        _ensure_pg_storage_env()
        return all(
            k in os.environ
            for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE")
        )
    except (RuntimeError, ImportError):
        return False


# ── P2 PG Extension Checks ──────────────────────────────────
# PGVectorStorage needs the pgvector extension (CREATE EXTENSION vector).
# PGGraphStorage needs the Apache AGE extension (CREATE EXTENSION age).
# Both are checked lazily at KB creation time.


async def _pg_vector_ready() -> bool:
    """Check if pgvector extension is available for PGVectorStorage.

    Returns True when:
      - PG storage is ready (pool + env vars)
      - The 'vector' extension is installed in the PG database
    """
    if not _pg_storage_ready():
        return False
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT extname FROM pg_extension WHERE extname = 'vector'"
            )
            return row is not None
    except Exception:
        return False


async def _pg_age_ready() -> bool:
    """Check if Apache AGE extension is available for PGGraphStorage.

    Returns True when:
      - PG storage is ready (pool + env vars)
      - The 'age' extension is installed/loadable in the PG database
    """
    if not _pg_storage_ready():
        return False
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT extname FROM pg_extension WHERE extname = 'age'"
            )
            return row is not None
    except Exception:
        return False


# ── KB Metadata JSON fallback file ──────────────────────
KB_META_JSON = Path("rag_storage_kb_meta.json")


async def load_kb_meta() -> dict[str, Any]:
    """Load KB metadata — PG first, JSON fallback.

    Returns:
        Dict keyed by KB name: {name: {name, created, domain, ...}, ...}
        Empty dict if no KBs exist (caller should create default if needed).
    """
    # ── Path 1: PG ──────────────────────────────────────
    try:
        from raganything.services.pg_kb_meta_repo import pg_load_kb_meta
        result = await pg_load_kb_meta()
        if result:
            return result
    except Exception:
        kb_logger.debug("PG kb_meta load failed, trying JSON fallback")

    # ── Path 2: JSON file fallback ──────────────────────
    if KB_META_JSON.exists():
        try:
            import json as _json
            data = _json.loads(KB_META_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                kb_logger.info("[KB-META] 从 JSON 文件加载了 %d 个知识库", len(data))
                return data
        except (_json.JSONDecodeError, OSError):
            pass

    return {}


async def save_kb_meta(meta: dict[str, Any]) -> None:
    """Persist KB metadata — PG + JSON mirror.

    Args:
        meta: Full KB metadata dict: {name: {name, created, ...}, ...}
    """
    # ── PG ──────────────────────────────────────────────
    try:
        from raganything.services.pg_kb_meta_repo import pg_save_all_kb_meta
        await pg_save_all_kb_meta(meta)
    except Exception:
        kb_logger.warning("PG kb_meta save failed, only JSON will be updated")

    # ── JSON mirror ─────────────────────────────────────
    try:
        import json as _json
        KB_META_JSON.write_text(
            _json.dumps(meta, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        kb_logger.warning("JSON kb_meta write failed")


def kb_dir(name: str) -> str:
    """Get storage directory path for a KB name."""
    return "./rag_storage" if name == "default" else f"./rag_storage_{name}"


# ── Doc Status / Text Chunks Dispatch Helpers ─────────────────
# When PG storage backends are active, LightRAG's doc_status and text_chunks
# are stored in PG tables (LIGHTRAG_DOC_STATUS, LIGHTRAG_KV_STORE_*), NOT in
# the JSON files.  These helpers dispatch between PG (via LightRAG instance
# API) and file reads so that the rest of kb_service.py works transparently
# regardless of the active storage backend.


async def _load_doc_status_json(kb_name: str) -> dict[str, Any]:
    """Load doc_status data for a KB, dispatching PG → LightRAG API → JSON fallback.

    Returns a dict with the same shape as kv_store_doc_status.json:
        {doc_id: {file_path, status, metadata, chunks_list, ...}, ...}

    Query order:
      1. PG via LightRAG's PGDocStatusStorage (if PG is ready)
      2. JSON file fallback (for data created before PG migration or when PG is empty)
    """
    import json as _json

    # ── Path 1: PG via LightRAG doc_status ─────────────────
    if _pg_storage_ready():
        rag = kb_instances.get(kb_name)
        if rag is None:
            try:
                rag = await get_kb(kb_name)
            except Exception:
                pass
        if rag is not None and rag.lightrag and hasattr(rag.lightrag, "doc_status"):
            try:
                from raganything.base import DocStatus as RAGDocStatus
                ds = rag.lightrag.doc_status
                # Guard: PG storage may not be initialized (e.g. after finalize()
                # in worker subprocess, or when ClientManager returns None).
                if getattr(ds, "db", None) is None:
                    kb_logger.debug(
                        "PG doc_status.db is None for KB %s, falling back to JSON",
                        kb_name,
                    )
                else:
                    all_statuses = [
                        RAGDocStatus.PENDING,
                        RAGDocStatus.READY,
                        RAGDocStatus.HANDLING,
                        RAGDocStatus.PROCESSING,
                        RAGDocStatus.PROCESSED,
                        RAGDocStatus.FAILED,
                    ]
                    result: dict[str, Any] = {}
                    for status in all_statuses:
                        page = 1
                        while True:
                            docs, total = await ds.get_docs_paginated(
                                status_filter=status, page=page, page_size=200,
                            )
                            for doc_id, dps in docs:
                                result[doc_id] = {
                                    "file_path": dps.file_path,
                                    "status": dps.status.value if hasattr(dps.status, "value") else dps.status,
                                    "content_summary": dps.content_summary,
                                    "content_length": dps.content_length,
                                    "chunks_count": dps.chunks_count,
                                    "chunks_list": dps.chunks_list or [],
                                    "metadata": dps.metadata or {},
                                    "error_msg": dps.error_msg,
                                    "created_at": dps.created_at,
                                    "updated_at": dps.updated_at,
                                    "track_id": dps.track_id,
                                }
                            if len(docs) < 200:
                                break
                            page += 1
                    if result:
                        return result
            except Exception:
                kb_logger.warning(
                    "PG doc_status load failed for KB %s",
                    kb_name, exc_info=True,
                )

    # ── Path 2: JSON file fallback ─────────────────────────
    json_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
    if json_path.exists():
        try:
            data = _json.loads(json_path.read_text(encoding="utf-8"))
            if data:
                kb_logger.info(
                    "[DOC-STATUS] KB=%s 从 JSON 备份加载了 %d 条记录",
                    kb_name, len(data),
                )
                return data
        except (_json.JSONDecodeError, OSError):
            kb_logger.warning(
                "JSON doc_status load failed for KB %s",
                kb_name, exc_info=True,
            )

    return {}


async def _save_doc_status_json(kb_name: str, data: dict[str, Any]) -> None:
    """Save doc_status data for a KB via LightRAG's PGDocStatusStorage (PG only)."""
    rag = kb_instances.get(kb_name)
    if rag is None:
        try:
            rag = await get_kb(kb_name)
        except Exception:
            pass
    if rag is not None and rag.lightrag and hasattr(rag.lightrag, "doc_status"):
        try:
            upsert_data: dict[str, dict[str, Any]] = {}
            for doc_id, info in data.items():
                upsert_data[doc_id] = {
                    "content_summary": info.get("content_summary", ""),
                    "content_length": info.get("content_length", 0),
                    "file_path": info.get("file_path", ""),
                    "status": info.get("status", "pending"),
                    "chunks_count": info.get("chunks_count", 0),
                    "chunks_list": info.get("chunks_list", []),
                    "metadata": info.get("metadata", {}),
                    "error_msg": info.get("error_msg"),
                    "track_id": info.get("track_id"),
                }
            await rag.lightrag.doc_status.upsert(upsert_data)
            await rag.lightrag.doc_status.index_done_callback()
        except Exception:
            kb_logger.warning(
                "PG doc_status save failed for KB %s", kb_name, exc_info=True,
            )


async def _load_text_chunks_json(kb_name: str) -> dict[str, Any]:
    """Load text_chunks data for a KB, dispatching PG → LightRAG API or file.

    Returns a dict with the same shape as kv_store_text_chunks.json.
    When PG storage is active, uses LightRAG's text_chunks storage.
    """
    # Try PG path — try kb_instances first, then get_kb()
    if _pg_storage_ready():
        rag = kb_instances.get(kb_name)
        if rag is None:
            try:
                rag = await get_kb(kb_name)
            except Exception:
                pass
        if rag is not None and rag.lightrag and hasattr(rag.lightrag, "text_chunks"):
            try:
                # LightRAG's text_chunks is a BaseKVStorage.  There's no direct
                # "get all" method, but get_by_ids with a known chunk list works.
                # For our cleanup purpose, we just need file_path from each chunk.
                # The PGKVStorage uses a workspace-keyed table.
                # Strategy: query the LightRAG doc_status for all chunks_list,
                # then batch-fetch via text_chunks.get_by_ids().
                ds_data = await _load_doc_status_json(kb_name)
                all_chunk_ids: list[str] = []
                for info in ds_data.values():
                    all_chunk_ids.extend(info.get("chunks_list", []))
                if all_chunk_ids:
                    chunks = await rag.lightrag.text_chunks.get_by_ids(all_chunk_ids)
                    result: dict[str, Any] = {}
                    for chunk in chunks:
                        if chunk:
                            cid = chunk.get("id") or chunk.get("__id__")
                            if cid:
                                result[cid] = chunk
                    if result:
                        return result
            except Exception:
                kb_logger.warning(
                    "PG text_chunks load failed for KB %s",
                    kb_name, exc_info=True,
                )

    return {}


async def _load_full_docs_json(kb_name: str) -> dict[str, Any]:
    """Load full_docs data for a KB, dispatching PG → LightRAG API → JSON fallback.

    Returns a dict with the same shape as kv_store_full_docs.json.

    Query order:
      1. PG via LightRAG's full_docs KV storage (if PG is ready)
      2. JSON file fallback (for data created before PG migration or when PG is empty)
    """
    import json as _json

    # ── Path 1: PG via LightRAG full_docs ─────────────────
    if _pg_storage_ready():
        rag = kb_instances.get(kb_name)
        if rag is None:
            try:
                rag = await get_kb(kb_name)
            except Exception:
                pass
        if rag is not None and rag.lightrag and hasattr(rag.lightrag, "full_docs"):
            try:
                ds_data = await _load_doc_status_json(kb_name)
                doc_ids = list(ds_data.keys())
                if doc_ids:
                    docs = await rag.lightrag.full_docs.get_by_ids(doc_ids)
                    result: dict[str, Any] = {}
                    for doc in docs:
                        if doc:
                            did = doc.get("id") or doc.get("__id__")
                            if did:
                                result[did] = doc
                    if result:
                        return result
            except Exception:
                kb_logger.warning(
                    "PG full_docs load failed for KB %s",
                    kb_name, exc_info=True,
                )

    # ── Path 2: JSON file fallback ─────────────────────────
    json_path = Path(kb_dir(kb_name)) / "kv_store_full_docs.json"
    if json_path.exists():
        try:
            data = _json.loads(json_path.read_text(encoding="utf-8"))
            if data:
                kb_logger.info(
                    "[FULL-DOCS] KB=%s 从 JSON 备份加载了 %d 条记录",
                    kb_name, len(data),
                )
                return data
        except (_json.JSONDecodeError, OSError):
            kb_logger.warning(
                "JSON full_docs load failed for KB %s",
                kb_name, exc_info=True,
            )

    return {}


# ── KB Instance Management ─────────────────────────────────

async def get_kb(name: str = None) -> RAGAnything:
    """Get or create a KB instance.

    Automatically detects when disk data is newer than the cached instance
    (e.g. after a worker subprocess has written new documents) and rebuilds
    the instance to ensure queries see the latest data.

    Args:
        name: KB name (defaults to active_kb)

    Returns:
        RAGAnything instance for the named KB
    """
    import time as _time
    name = name or active_kb
    # Serialize initialization per KB to prevent concurrent creation race
    if name not in _kb_locks:
        _kb_locks[name] = asyncio.Lock()
    async with _kb_locks[name]:
        if name in kb_instances:
            # ── Cache freshness check ──
            # When PG storage is active, skip mtime check (JSON file is stale).
            # Instead, we trust the cached instance (PG is always current).
            if not _pg_storage_ready():
                doc_status_path = Path(kb_dir(name)) / "kv_store_doc_status.json"
                if doc_status_path.exists():
                    try:
                        disk_mtime = doc_status_path.stat().st_mtime
                        cache_time = kb_instances.get_cache_time(name)
                        if disk_mtime > cache_time:
                            kb_logger.info(
                                f"[KB] 缓存过期重建: {name} "
                                f"(disk={disk_mtime:.0f} > cache={cache_time:.0f})"
                            )
                            try:
                                await kb_instances[name].finalize_storages()
                            except Exception:
                                pass
                            del kb_instances[name]
                    except OSError:
                        pass  # stat() failed, trust cache
        if name not in kb_instances:
            from lightrag.kg.shared_storage import set_default_workspace
            target = kb_dir(name)
            set_default_workspace(target)
            instance = await create_rag(working_dir=target)
            await instance._ensure_lightrag_initialized()
            # Lower vector retrieval cosine threshold for broader semantic recall
            if instance.lightrag and hasattr(instance.lightrag, 'chunks_vdb'):
                instance.lightrag.chunks_vdb.cosine_better_than_threshold = 0.0
            await kb_instances.put_and_evict(name, instance, _time.time())
            kb_logger.info(f"[KB] 初始化知识库实例: {name} workspace={target}")
    return kb_instances[name]


async def cleanup_kb_resources(name: str) -> None:
    """Unified cleanup of all resources when a KB is deleted.

    Kills running workers, clears queues, removes cached instances,
    cleans dedup/processing state, deletes storage directories and
    upload files, and removes metadata.

    Idempotent — safe to call multiple times.
    """
    import shutil as _shutil
    import raganything.routers.shared as _rshared

    kb_logger.info(f"[cleanup] 开始清理 KB 资源: {name}")
    _kbs_being_deleted.add(name)  # set BEFORE any async yield

    # ── 1. Kill all running worker subprocesses ──────────
    worker_list = _kb_worker_procs.pop(name, [])
    for proc, task_id in worker_list:
        try:
            if proc.returncode is None:
                proc.kill()
                kb_logger.info(f"[cleanup] 已终止 Worker 进程: task={task_id}")
        except Exception:
            pass

    # ── 2. Stop drain & clear queue ──────────────────────
    _drain_start_locks.pop(name, None)
    queue = _rshared._kb_queues.pop(name, None)
    if queue is not None:
        # Put a sentinel so the drain coroutine exits even if it is
        # currently blocked on queue.get().  Any intervening tasks
        # will fail (KB dir is gone) and the drain cleans up after each.
        try:
            queue.put_nowait(_QUEUE_SENTINEL)
        except Exception:
            pass
    _rshared._kb_draining.pop(name, None)

    # ── 3. Clean dedup tracking entries ──────────────────
    dedup_removed = 0
    for (kb_n, fh) in list(_processing_files.keys()):
        if kb_n == name:
            del _processing_files[(kb_n, fh)]
            dedup_removed += 1
    if dedup_removed:
        kb_logger.info(f"[cleanup] 已清理 {dedup_removed} 个去重记录: {name}")

    # ── 4. Clean processing_tasks entries ────────────────
    from raganything.services.state_service import processing_tasks, delete_task
    tasks_removed = 0
    for tid in list(processing_tasks.keys()):
        if processing_tasks[tid].get("kb", "") == name:
            await delete_task(tid)
            tasks_removed += 1
    if tasks_removed:
        kb_logger.info(f"[cleanup] 已清理 {tasks_removed} 个处理中任务记录: {name}")

    # ── 5. Clean cached KB instance ──────────────────────
    if name in kb_instances:
        try:
            await kb_instances[name].finalize_storages()
        except Exception as exc:
            kb_logger.warning(f"[cleanup] finalize_storages 失败 ({name}): {exc}")
        del kb_instances[name]

    # ── 6. Collect upload files BEFORE deleting dir ──────
    _found_files: set = set()

    # Use PG dispatch helpers when available, file fallback otherwise
    doc_status = await _load_doc_status_json(name)
    for info in doc_status.values():
        fp = info.get("file_path", "")
        if fp:
            _found_files.add(fp)

    chunks = await _load_text_chunks_json(name)
    for chunk_data in chunks.values():
        try:
            cd = json.loads(chunk_data) if isinstance(chunk_data, str) else chunk_data
            fp = cd.get("file_path", "")
            if fp and fp not in _found_files:
                _found_files.add(fp)
        except Exception:
            pass

    # ── 7. Delete output & storage directories ───────────
    output_dir = "./output" if name == "default" else f"./output_{name}"
    _shutil.rmtree(output_dir, ignore_errors=True)
    _shutil.rmtree(kb_dir(name), ignore_errors=True)
    kb_logger.info(f"[cleanup] 已删除存储目录: {kb_dir(name)}")

    # ── 8. Delete upload files ───────────────────────────
    for fp in _found_files:
        upload_file = Path("./uploads") / Path(fp).name
        if upload_file.exists():
            try:
                upload_file.unlink()
            except OSError:
                pass

    # ── 9. Remove metadata (PG + in-memory) ──────────────
    meta = await load_kb_meta()
    if name in meta:
        del meta[name]
        await save_kb_meta(meta)
    # Explicitly delete the PG row — pg_save_all_kb_meta only upserts,
    # it does NOT delete entries removed from the dict.
    try:
        from raganything.services.pg_kb_meta_repo import pg_delete_kb_meta
        await pg_delete_kb_meta(name)
    except Exception:
        pass

    # ── 10. Clean ALL PG LightRAG tables for this workspace ──
    # LightRAG's postgres_impl.py creates 11+ tables (LIGHTRAG_DOC_STATUS,
    # LIGHTRAG_DOC_FULL, LIGHTRAG_VDB_*, LIGHTRAG_LLM_CACHE, etc.).
    # Hardcoding table names is fragile — new LightRAG versions may add or
    # rename tables.  Instead, query information_schema for all LIGHTRAG%
    # tables that have a 'workspace' column, and DELETE from each.
    wd = kb_dir(name)
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            # Discover all LightRAG tables with workspace-based isolation
            lightrag_tables = await conn.fetch(
                """SELECT table_name
                   FROM information_schema.columns
                   WHERE table_schema = 'public'
                     AND column_name = 'workspace'
                     AND table_name LIKE 'lightrag%'
                   ORDER BY table_name"""
            )
            for row in lightrag_tables:
                tbl = row["table_name"]
                try:
                    result = await conn.execute(
                        f"DELETE FROM {tbl} WHERE workspace=$1", wd,
                    )
                    # Parse deleted row count from command tag
                    try:
                        deleted = int(str(result).split()[-1])
                    except (ValueError, IndexError):
                        deleted = 0
                    if deleted:
                        kb_logger.info(
                            f"[cleanup] PG {tbl}: 已删除 {deleted} 行 (workspace={wd})"
                        )
                except Exception:
                    pass
                # Also clean rows written with empty workspace by pre-fix workers.
                # Before the set_default_workspace() fix, worker subprocesses
                # wrote all data with workspace="" (LightRAG default).
                try:
                    result2 = await conn.execute(
                        f"DELETE FROM {tbl} WHERE workspace=''"
                    )
                    try:
                        deleted2 = int(str(result2).split()[-1])
                    except (ValueError, IndexError):
                        deleted2 = 0
                    if deleted2:
                        kb_logger.info(
                            f"[cleanup] PG {tbl}: 已删除 {deleted2} 行 (workspace='', 修复前残留)"
                        )
                except Exception:
                    pass
            # Clean uploaded_files for this KB
            try:
                await conn.execute(
                    "DELETE FROM uploaded_files WHERE kb_name=$1", name,
                )
            except Exception:
                pass
        kb_logger.info(f"[cleanup] 已清理 PG 表数据: {name}")
    except Exception:
        kb_logger.warning(f"[cleanup] PG 表清理失败: {name}", exc_info=True)

    # ── 11. Reset active KB if needed ────────────────────
    if _rshared.active_kb == name:
        _rshared.active_kb = "default"

    # ── 12. Invalidate query cache ───────────────────────
    try:
        from raganything.query_cache import get_query_cache
        get_query_cache().invalidate()
    except Exception:
        pass

    kb_logger.info(f"[cleanup] KB 资源清理完成: {name}")
    _kbs_being_deleted.discard(name)


async def delete_kb(name: str) -> bool:
    """Delete a KB instance and its storage.

    Delegates to ``cleanup_kb_resources()`` for unified cleanup.

    Args:
        name: KB name to delete

    Returns:
        True if deleted, False if not found
    """
    if name not in kb_instances and name not in await load_kb_meta():
        return False

    await cleanup_kb_resources(name)
    kb_logger.info(f"[KB] 已删除知识库: {name}")
    return True


async def list_kbs() -> dict[str, Any]:
    """List all KB metadata entries from PostgreSQL."""
    from raganything.services.pg_kb_meta_repo import pg_load_kb_meta
    return await pg_load_kb_meta()


async def list_kbs_by_domain(domain: str) -> dict[str, Any]:
    """List KB metadata entries filtered by domain from PostgreSQL.

    Args:
        domain: Domain filter value (e.g. ``"autorepair"``, ``"general"``).

    Returns:
        Dict of KB name → metadata for KBs matching the domain.
        KBs without a ``domain`` field are treated as ``"general"`` for
        backward compatibility with KBs created before this field existed.
    """
    from raganything.services.pg_kb_meta_repo import pg_list_kbs_by_domain
    rows = await pg_list_kbs_by_domain(domain)
    return {
        r["name"]: {
            "name": r.get("display_name", r["name"]),
            "created": r.get("created_at", ""),
            "domain": r.get("domain", "general"),
            "description": r.get("description", ""),
            "owner_id": r.get("owner_id", 0),
            "owner_username": r.get("owner_username", ""),
            "status": r.get("status", "ready"),
            "document_count": r.get("document_count", 0),
        }
        for r in rows
    }


# ── RAGAnything Factory ────────────────────────────────────

async def create_rag(
    parser: str = None,
    working_dir: str = None,
    chunking_strategy: str = None,
) -> RAGAnything:
    """Create a RAGAnything instance with configured LLM/embedding functions.

    Args:
        parser: Parser name (default from env PARSER or "mineru")
        working_dir: Working directory for LightRAG storage
        chunking_strategy: Chunking strategy name

    Returns:
        Configured RAGAnything instance
    """
    if parser is None:
        parser = os.getenv("PARSER", "docling")
    if chunking_strategy is None:
        chunking_strategy = os.getenv("CHUNKING_STRATEGY", "recursive")
    wd = working_dir or WORKING_DIR

    # ── 从 os.environ 读取运行时可变配置 ──────────────────
    # 不依赖模块级全局变量！PUT /api/settings 修改 os.environ 后，
    # 下次 create_rag() 调用自动获得最新值。
    _llm_model = os.getenv("LLM_MODEL", "qwen-plus")
    _vision_model = os.getenv("VISION_MODEL", "qwen-vl-plus")
    _emb_model = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
    _emb_dim = int(os.getenv("EMBEDDING_DIM", "1024"))
    _api_key = os.getenv("LLM_BINDING_API_KEY")
    _base_url = os.getenv("LLM_BINDING_HOST")

    def llm_func(prompt, system_prompt=None, history_messages=[], **kw):
        if "max_tokens" not in kw:
            kw["max_tokens"] = int(os.getenv("MAX_TOKENS", "4096"))
        return openai_complete_if_cache(
            _llm_model, prompt, system_prompt=system_prompt,
            history_messages=history_messages, api_key=_api_key, base_url=_base_url, **kw,
        )

    def vision_func(prompt, system_prompt=None, history_messages=[],
                    image_data=None, image_mime_type=None, messages=None, **kw):
        if messages is not None:
            return openai_complete_if_cache(
                _vision_model, "", system_prompt=None, history_messages=[],
                messages=messages, api_key=_api_key, base_url=_base_url, **kw,
            )
        elif image_data is not None:
            mime_type = (
                image_mime_type
                if image_mime_type in _VLM_IMAGE_MIME_TYPES
                else "image/jpeg"
            )
            return openai_complete_if_cache(
                _vision_model, "", system_prompt=None, history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                    ]},
                ],
                api_key=_api_key, base_url=_base_url, **kw,
            )
        else:
            return llm_func(prompt, system_prompt, history_messages, **kw)

    # LightRAG's @wrap_embedding_func_with_attrs hardcodes embedding_dim=1536,
    # but DashScope text-embedding-v3 returns 1024-dim vectors. We override the
    # embedding_dim attribute on the partial function so LightRAG allocates
    # vector storage at the correct (API-native) dimension.
    _raw_embed_func = partial(
        openai_embed.func, model=_emb_model, api_key=_api_key, base_url=_base_url
    )
    _raw_embed_func.embedding_dim = _emb_dim

    # Wrap with local persistent cache to avoid redundant API calls.
    # Same entity/relation names across chunks → instant cache hits.
    _cached_embed_func = make_cached_embed_func(_raw_embed_func, wd, _emb_model)

    embedding_func = EmbeddingFunc(
        embedding_dim=_emb_dim, max_token_size=8192,
        func=_cached_embed_func,
    )

    def _env_int(key: str, default: int, min_val: int = 1, max_val: int = 100) -> int:
        """安全读取整数环境变量，防止 typo 导致启动崩溃或恶意超限值"""
        try:
            val = int(os.getenv(key, str(default)))
            return max(min_val, min(val, max_val))
        except ValueError:
            return default

    # ── Chunking strategy mapping ──────────────────────────
    chunk_token_size = _env_int("CHUNK_SIZE", 800, max_val=4096)
    embedding_batch_size = _env_int("EMBEDDING_BATCH_SIZE", 10, max_val=10)

    def _get_embedding_func_for_chunk(texts: list[str]) -> list[list[float]]:
        return embedding_func.func(texts, model=EMB_MODEL)

    async def _get_llm_func_for_chunk(prompt: str, system_prompt: str = "",
                                       history_messages=None, **kw):
        return await llm_func(prompt, system_prompt=system_prompt,
                              history_messages=history_messages or [], **kw)

    chunking_strategy_map = {
        "fixed_size": None,  # Use LightRAG default
        "recursive": recursive_chunking,
        "sentence": sentence_chunking,
        "structure": structure_chunking,
        "semantic": make_semantic_chunking(
            _get_embedding_func_for_chunk, embedding_batch_size
        ),
        "agentic": make_agentic_chunking(_get_llm_func_for_chunk, _llm_model),
    }
    chosen_chunking_func = chunking_strategy_map.get(chunking_strategy)

    lightrag_kwargs = {
        "chunk_token_size": chunk_token_size,
        "chunk_overlap_token_size": _env_int("CHUNK_OVERLAP", 100, max_val=500),
        "enable_llm_cache": os.getenv("ENABLE_LLM_CACHE", "true").lower() == "true",
        "enable_llm_cache_for_entity_extract": os.getenv("ENABLE_LLM_CACHE_FOR_EXTRACT", "true").lower() == "true",
        "embedding_batch_num": embedding_batch_size,
        "embedding_func_max_async": _env_int("ENTITY_EXTRACT_CONCURRENCY", 3, max_val=16),
        # 显式传入 LightRAG 参数，消除 import-order 依赖
        "llm_model_max_async": _env_int("MAX_ASYNC", 4, max_val=16),
        "entity_extract_max_gleaning": _env_int("MAX_GLEANING", 1, max_val=2),
    }
    if chosen_chunking_func is not None:
        lightrag_kwargs["chunking_func"] = chosen_chunking_func

    config = RAGAnythingConfig(
        working_dir=wd,
        parser=parser,
        enable_image_processing=os.getenv("ENABLE_IMAGE_PROCESSING", "true").lower() == "true",
        enable_table_processing=os.getenv("ENABLE_TABLE_PROCESSING", "true").lower() == "true",
        enable_equation_processing=os.getenv("ENABLE_EQUATION_PROCESSING", "true").lower() == "true",
        enable_video_processing=os.getenv("ENABLE_VIDEO_PROCESSING", "false").lower() == "true",
        entity_types=os.getenv("ENTITY_TYPES", ""),
        entity_extraction_min_degree=int(os.getenv("ENTITY_EXTRACTION_MIN_DEGREE", "0")),
    )

    # ── Vision embedding (doubao-embedding-vision) ──────────
    # Feature-gated: returns None when VISION_SEARCH_ENABLED is False
    # or VISION_EMBEDDING_MODEL is not set.
    if os.getenv("VISION_SEARCH_ENABLED", "false").lower() == "true":
        vision_embed_func = create_vision_embed_func(working_dir=wd)
    else:
        vision_embed_func = None

    # ── PG Storage Backends (P1 + P2) ────────────────────────
    # When PostgreSQL is available, switch LightRAG from file-based
    # JSON storage to PG-backed storage.  Each backend is enabled
    # independently based on extension availability:
    #
    #   P1 — kv_storage         : PGKVStorage (no extra extension)
    #   P1 — doc_status_storage : PGDocStatusStorage (no extra extension)
    #   P2 — vector_storage     : PGVectorStorage (needs pgvector)
    #   P2 — graph_storage      : PGGraphStorage (needs Apache AGE)
    #
    # LightRAG auto-creates required tables on first use. Each KB is
    # isolated via the workspace (set by set_default_workspace() above).
    #
    # ⚠️  Data-aware dispatch: if the worker wrote data to JSON files
    # (pre-PG-migration) but PG tables are empty, stay on JSON so
    # queries can find the existing data.  New uploads with the fixed
    # worker will write to both JSON and PG, enabling future migration.
    _use_pg_backends = False
    if _pg_storage_ready():
        import json as _json_check
        _json_ds = Path(wd) / "kv_store_doc_status.json"
        _json_has_data = False
        if _json_ds.exists():
            try:
                _json_has_data = bool(_json_check.loads(_json_ds.read_text(encoding="utf-8")))
            except Exception:
                pass

        _pg_has_data = False
        try:
            from raganything.services.pg_state_repo import get_pg_pool
            _pool = get_pg_pool()
            async with _pool.acquire() as _conn:
                _row = await _conn.fetchrow(
                    "SELECT 1 FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1 LIMIT 1",
                    wd,
                )
                _pg_has_data = _row is not None
        except Exception:
            pass

        if _pg_has_data or not _json_has_data:
            # PG has data → use PG.  OR  Fresh KB (no JSON data) → use PG.
            _use_pg_backends = True
        else:
            kb_logger.info(
                "JSON data exists but PG tables empty — keeping JSON storage "
                "for KB at %s (queries would return 0 results otherwise)",
                wd,
            )

    if _use_pg_backends:
        lightrag_kwargs["kv_storage"] = "PGKVStorage"
        lightrag_kwargs["doc_status_storage"] = "PGDocStatusStorage"
        backends = ["PGKVStorage", "PGDocStatusStorage"]

        # P2: PGVectorStorage — requires pgvector extension
        if await _pg_vector_ready():
            lightrag_kwargs["vector_storage"] = "PGVectorStorage"
            backends.append("PGVectorStorage")
        else:
            kb_logger.info("pgvector not available, vector storage stays NanoVectorDB")

        # P2: PGGraphStorage — requires Apache AGE extension
        if await _pg_age_ready():
            lightrag_kwargs["graph_storage"] = "PGGraphStorage"
            backends.append("PGGraphStorage")
        else:
            kb_logger.info("AGE not available, graph storage stays NetworkX")

        kb_logger.info("PG storage backends enabled: %s", " + ".join(backends))
    else:
        kb_logger.debug("PG storage backends not available, using JSON files")

    # ── PG workspace isolation ──────────────────────────────
    # LightRAG defaults workspace=os.getenv("WORKSPACE","") which is "".
    # Without an explicit workspace, ALL KBs share the same PG tables,
    # causing data leaks between KBs and 0 entity/relation counts.
    # Pass the working directory as the workspace so each KB has its
    # own isolated PG data partition.
    lightrag_kwargs["workspace"] = wd

    return RAGAnything(config=config, llm_model_func=llm_func,
                       vision_model_func=vision_func, embedding_func=embedding_func,
                       vision_embed_func=vision_embed_func,
                       lightrag_kwargs=lightrag_kwargs)


# ── Recovery Lock (PG advisory + file fallback) ──────────────
# Multi-worker recovery lock. PG advisory lock auto-releases on connection
# close — no cleanup needed after worker crash.

import tempfile
import time as _time_module


@asynccontextmanager
async def _recovery_lock():
    """Serialize recovery locally and across PostgreSQL-backed workers."""
    async with _recovery_local_lock:
        if not _pg_storage_ready():
            yield None
            return

        try:
            from raganything.services.pg_state_repo import get_pg_pool

            pool = get_pg_pool()
        except Exception:
            kb_logger.warning("[Recovery] PG lock unavailable; skipping recovery")
            yield _RECOVERY_LOCK_NOT_ACQUIRED
            return

        async with pool.acquire() as conn:
            try:
                locked = await conn.fetchval("SELECT pg_try_advisory_lock(987654)")
            except Exception:
                kb_logger.warning("[Recovery] PG lock acquisition failed", exc_info=True)
                yield _RECOVERY_LOCK_NOT_ACQUIRED
                return

            if not locked:
                kb_logger.debug("[Recovery] another process is already scanning")
                yield _RECOVERY_LOCK_NOT_ACQUIRED
                return

            try:
                yield conn
            finally:
                try:
                    await conn.execute("SELECT pg_advisory_unlock(987654)")
                except Exception:
                    kb_logger.warning("[Recovery] PG lock release failed", exc_info=True)


async def _persist_failed_doc_status(
    kb_name: str,
    filename: str,
    error_message: str,
    task_id: str = "",
    chunking_strategy: str = "",
) -> str | None:
    """Create a retryable failed document record when parsing never reached LightRAG."""
    doc_id = "doc-failed-" + hashlib.sha256(
        f"{kb_name}:{filename}".encode("utf-8")
    ).hexdigest()
    metadata = {
        "failure_stage": "worker",
        "retryable": True,
        "task_id": task_id,
    }
    if chunking_strategy:
        metadata["chunking_strategy"] = chunking_strategy
    record = {
        "content_summary": "",
        "content_length": 0,
        "file_path": filename,
        "status": "failed",
        "chunks_count": 0,
        "chunks_list": [],
        "metadata": metadata,
        "error_msg": error_message[:2000],
        "track_id": task_id or None,
    }
    try:
        rag = kb_instances.get(kb_name)
        if rag is None:
            rag = await get_kb(kb_name)
        if rag is None or not getattr(rag, "lightrag", None):
            return None
        await rag.lightrag.doc_status.upsert({doc_id: record})
        await rag.lightrag.doc_status.index_done_callback()
        kb_logger.warning(
            "[DOC-STATUS] Created failed placeholder doc=%s file=%s KB=%s",
            doc_id[:24],
            filename,
            kb_name,
        )
        return doc_id
    except Exception:
        kb_logger.warning(
            "[DOC-STATUS] Failed to create parser-stage failure record for KB=%s file=%s",
            kb_name,
            filename,
            exc_info=True,
        )
        return None


async def _fix_stuck_doc_status(
    kb_name: str,
    filename: str,
    error_message: str | None = None,
    task_id: str = "",
    chunking_strategy: str = "",
):
    """Fix documents stuck in 'handling' state after subprocess crash/timeout.

    Uses PG-dispatch when PG storage is active, file fallback otherwise.

    Args:
        kb_name: KB name
        filename: The file whose doc_status may be stuck
    """
    try:
        data = await _load_doc_status_json(kb_name)
        data = data or {}
        changed = False
        matched = False
        for doc_id, info in data.items():
            stored = info.get("file_path", "")
            stored_base = os.path.basename(stored)
            search_base = os.path.basename(filename)
            # Robust match: handles hash-prefixed uploads and full/partial paths
            # Length guard: prefix is exactly 9 chars (8 hex + 1 underscore)
            same_document = (
                stored == filename
                or stored_base == search_base
                or (
                    stored_base.endswith("_" + search_base)
                    and len(stored_base) - len(search_base) == 9
                )
            )
            matched = matched or same_document
            if (stored == filename
                    or stored_base == search_base
                    or (stored_base.endswith("_" + search_base)
                        and len(stored_base) - len(search_base) == 9)) \
                    and info.get("status") == "handling":
                info["status"] = "failed"
                info["error_msg"] = "处理中断：子进程异常退出或超时"
                if chunking_strategy:
                    metadata = info.get("metadata") or {}
                    metadata = dict(metadata) if isinstance(metadata, dict) else {}
                    metadata["chunking_strategy"] = chunking_strategy
                    info["metadata"] = metadata
                changed = True
                kb_logger.warning(
                    f"[FIX-STUCK] 修复卡住的文档: {filename} (KB={kb_name}) handling→failed"
                )
        if changed:
            await _save_doc_status_json(kb_name, data)
        elif not matched:
            failure_args = (
                kb_name,
                filename,
                error_message or "Worker exited before document parsing created a status record.",
                task_id,
            )
            if chunking_strategy:
                await _persist_failed_doc_status(*failure_args, chunking_strategy)
            else:
                await _persist_failed_doc_status(*failure_args)
    except Exception as ex:
        kb_logger.error(f"[FIX-STUCK] 修复失败: {ex}")


def _has_processing_end_time(info: dict[str, Any]) -> bool:
    metadata = info.get("metadata") or {}
    if not isinstance(metadata, dict):
        return False
    try:
        return float(metadata.get("processing_end_time", 0)) > 0
    except (TypeError, ValueError):
        return False


def _has_completed_multimodal_metadata(info: dict[str, Any]) -> bool:
    """Return whether the durable multimodal completion marker is present."""
    metadata = info.get("metadata")
    return (
        isinstance(metadata, dict)
        and metadata.get("multimodal_processed") is True
    )


async def _recover_pg_document_status(conn) -> None:
    """Mark finished PG-backed documents as processed without loading KBs."""
    try:
        recovered = await conn.fetch(
            """
            UPDATE LIGHTRAG_DOC_STATUS
               SET status = $1, updated_at = CURRENT_TIMESTAMP
             WHERE status = $2
               AND COALESCE(metadata ->> 'processing_end_time', '')
                   ~ '^[0-9]+([.][0-9]+)?$'
               AND (metadata ->> 'processing_end_time')::double precision > 0
               AND metadata -> 'multimodal_processed' = 'true'::jsonb
               AND NOT EXISTS (
                   SELECT 1
                     FROM processing_tasks AS task
                    WHERE task.status NOT IN ('completed', 'failed')
                      AND LIGHTRAG_DOC_STATUS.workspace = CASE
                          WHEN task.kb_name = 'default' THEN './rag_storage'
                          ELSE './rag_storage_' || task.kb_name
                      END
               )
         RETURNING workspace, id
            """,
            DocStatus.PROCESSED.value,
            DocStatus.HANDLING.value,
        )
    except Exception:
        kb_logger.warning("[Recovery] PG document-status recovery failed", exc_info=True)
        return

    for row in recovered:
        kb_logger.info(
            "[Recovery] fixed finished document: %s/%s",
            row["workspace"],
            str(row["id"])[:16],
        )


async def _active_recovery_kbs(conn) -> set[str] | None:
    if conn is not None:
        try:
            rows = await conn.fetch(
                "SELECT kb_name FROM processing_tasks WHERE status NOT IN ('completed', 'failed')"
            )
            return {str(row["kb_name"] or "default") for row in rows}
        except Exception:
            kb_logger.warning("[Recovery] PG active-task lookup failed", exc_info=True)
            # A stale local cache must not cause a live document to be marked
            # complete when the authoritative task store cannot be queried.
            return None

    from raganything.services.state_service import processing_tasks

    return {
        str(task.get("kb") or task.get("kb_name") or "default")
        for task in processing_tasks.values()
        if task.get("status") not in ("completed", "failed")
    }


async def _recover_json_document_status(conn=None) -> None:
    """Preserve recovery for JSON-backed and pre-migration knowledge bases."""
    try:
        meta = await load_kb_meta()
    except Exception:
        return

    if not meta:
        return

    # Without PostgreSQL, this process owns both the task cache and recovery
    # loop, so a single snapshot is sufficient. With PostgreSQL, however,
    # task creation can occur in another worker and must be serialized with
    # each JSON read/modify/replace operation below.
    active_kbs = None
    if conn is None:
        active_kbs = await _active_recovery_kbs(None)
        if active_kbs is None:
            return

    for kb_name in list(meta.keys()):
        json_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
        if not json_path.exists():
            continue

        if conn is None:
            if kb_name in active_kbs:
                continue
            await _recover_json_status_file(kb_name, json_path)
            continue

        try:
            # PostgreSQL task writes use ROW EXCLUSIVE locks. SHARE conflicts
            # with them, so no worker can create or update an active task
            # between this authoritative check and the atomic JSON replace.
            # NOWAIT keeps recovery best-effort: a busy task writer causes
            # this scan to skip rather than delaying uploads indefinitely.
            async with conn.transaction():
                await conn.execute("LOCK TABLE processing_tasks IN SHARE MODE NOWAIT")
                active_kbs = await _active_recovery_kbs(conn)
                if active_kbs is None:
                    return
                if kb_name not in active_kbs:
                    await _recover_json_status_file(kb_name, json_path)
        except Exception:
            kb_logger.warning(
                "[Recovery] JSON task/write coordination failed for KB %s",
                kb_name,
                exc_info=True,
            )
            return


async def _recover_json_status_file(kb_name: str, json_path: Path) -> None:
    """Recover one JSON status file while its task-state guard is held."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
    except (json.JSONDecodeError, OSError):
        kb_logger.warning("[Recovery] JSON doc-status load failed for KB %s", kb_name)
        return

    changed = False
    for doc_id, info in data.items():
        if not isinstance(info, dict):
            continue
        if info.get("status") != DocStatus.HANDLING.value:
            continue
        if not _has_processing_end_time(info):
            continue
        if not _has_completed_multimodal_metadata(info):
            continue
        info["status"] = DocStatus.PROCESSED.value
        changed = True
        kb_logger.info(
            "[Recovery] fixed finished JSON document: %s/%s",
            kb_name,
            str(doc_id)[:16],
        )

    if not changed:
        return

    try:
        temporary_path = json_path.with_suffix(json_path.suffix + ".recovery")
        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary_path.replace(json_path)
        if kb_name in kb_instances:
            del kb_instances[kb_name]
    except OSError:
        kb_logger.warning("[Recovery] JSON doc-status save failed for KB %s", kb_name)


async def _recover_stuck_documents():
    """Recover finished documents without loading every registered KB instance.

    Orphan reconciliation remains in the explicit repair and delete-recovery
    paths. It is intentionally excluded from document-status recovery.
    """
    async with _recovery_lock() as lock_connection:
        if lock_connection is _RECOVERY_LOCK_NOT_ACQUIRED:
            return
        if lock_connection is not None:
            await _recover_pg_document_status(lock_connection)
        await _recover_json_document_status(lock_connection)


async def _stuck_recovery_loop(interval_sec: int = 300):
    """Background asyncio task: periodically scan for stuck documents.

    Args:
        interval_sec: Seconds between scans (default 5 minutes)

    Uses a process-local lock plus a PostgreSQL advisory lock when available
    so only one worker scans persistent document status at a time.
    """
    await asyncio.sleep(5)  # let startup settle first
    while True:
        try:
            await _recover_stuck_documents()
        except Exception as e:
            kb_logger.warning(f"[Recovery] 周期扫描异常: {e}")
        await asyncio.sleep(interval_sec)


async def _finalize_failed_upload(
    task_id: str,
    kb_name: str,
    filename: str,
    user_id: int,
    error_message: str,
    file_hash: str | None,
    chunking_strategy: str = "",
) -> None:
    """Persist document failure before making its task terminal.

    Recovery treats non-terminal task rows as a KB-wide liveness guard. Keep
    that guard in place until the matching document is failed (or a retryable
    placeholder was created), so periodic recovery cannot complete it in the
    middle of failure handling.
    """
    from raganything.services.ws_service import add_event
    from raganything.services.state_service import upsert_task_state

    fix_args = (kb_name, filename, error_message, task_id)
    if chunking_strategy:
        await _fix_stuck_doc_status(*fix_args, chunking_strategy)
    else:
        await _fix_stuck_doc_status(*fix_args)
    await upsert_task_state(task_id, {
        "id": task_id, "status": "failed", "error": error_message,
        "kb": kb_name, "file": filename, "user_id": user_id,
        "chunking_strategy": chunking_strategy,
    })
    await add_event(
        "upload_error", file=filename, task_id=task_id,
        error=error_message, user_id=user_id,
    )
    if file_hash is not None:
        await pg_update_upload_status_by_task_id(
            task_id,
            "failed",
            kb_name=kb_name,
            error_message=error_message,
        )
        _unregister_processing_file(kb_name, file_hash)


# ── Document Upload Processing ─────────────────────────────

async def _verify_document_persisted(kb_name: str, filename: str) -> str | None:
    """Verify that a processed document has chunks in doc_status.

    Uses PG dispatch when PG storage is active, file fallback otherwise.

    Raises RuntimeError if the document is missing from doc_status or has
    zero chunks after worker subprocess reports success.

    When PG doc_status is temporarily unreadable (e.g. after subprocess
    finalization), the check is skipped with a warning instead of failing
    — the worker independently persisted data to PG.
    """
    data = await _load_doc_status_json(kb_name)
    if not data:
        # Distinguish: PG unreadable vs truly missing data
        if _pg_storage_ready():
            rag = kb_instances.get(kb_name)
            if rag is not None and hasattr(rag, "lightrag") and rag.lightrag:
                ds = getattr(rag.lightrag, "doc_status", None)
                if ds is not None and getattr(ds, "db", None) is None:
                    kb_logger.warning(
                        "[VERIFY] PG doc_status 暂时不可用，跳过验证 (KB=%s, file=%s)",
                        kb_name, filename,
                    )
                    return None
        raise RuntimeError(
            f"文档处理异常：doc_status 无数据 (KB={kb_name})"
        )

    fname = os.path.basename(filename)
    for doc_id, info in data.items():
        stored_raw = info.get("file_path", "")
        stored_base = os.path.basename(stored_raw)
        # Robust match: handles hash-prefixed uploads (8-hex + "_" + original)
        # Length guard: prefix is exactly 9 chars (8 hex + 1 underscore)
        if (stored_base == fname
                or (stored_base.endswith("_" + fname)
                    and len(stored_base) - len(fname) == 9)):
            chunks = info.get("chunks_count", 0)
            status = info.get("status", "?")
            normalized_status = str(status or "").lower()
            if normalized_status == "failed":
                raise RuntimeError(
                    f"文档处理异常：status=failed, chunks={chunks} (doc_id={doc_id[:16]})"
                )
            if chunks == 0:
                raise RuntimeError(
                    f"文档处理异常：chunks=0, status={status} (doc_id={doc_id[:16]})"
                )
            return str(doc_id)
    raise RuntimeError(f"文档处理异常：doc_status 中未找到匹配记录 ({fname})")


def _find_document_status_for_filename(
    data: dict[str, Any], filename: str
) -> tuple[str, dict[str, Any]] | None:
    """Find the persisted status row for a possibly hash-prefixed upload."""
    fname = os.path.basename(filename)
    for doc_id, info in data.items():
        if not isinstance(info, dict):
            continue
        stored_base = os.path.basename(str(info.get("file_path") or ""))
        if stored_base == fname or (
            stored_base.endswith("_" + fname)
            and len(stored_base) - len(fname) == 9
        ):
            return str(doc_id), info
    return None


def _automatic_tag_chunk_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("chunk_id") or chunk.get("id") or "")


def _automatic_tag_chunk_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize persisted records for the local automatic tag planner."""
    normalized: list[dict[str, Any]] = []
    for record in records:
        chunk = dict(record)
        chunk_id = _automatic_tag_chunk_id(chunk)
        if not chunk_id:
            continue
        chunk["chunk_id"] = chunk_id
        normalized.append(chunk)
    return normalized


async def _load_automatic_tag_chunks(
    kb_name: str, document_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load chunks for automatic tags despite delayed doc-status visibility."""
    from raganything.services.kb_chunk_repo import (
        PersistedChunkQueryError,
        query_chunks_by_document_id,
    )

    status_info: dict[str, Any] = {}
    instance = None
    for attempt in range(3):
        statuses = await _load_doc_status_json(kb_name)
        candidate = statuses.get(document_id) if isinstance(statuses, dict) else None
        if isinstance(candidate, dict):
            status_info = dict(candidate)
        chunk_ids = [
            str(value) for value in status_info.get("chunks_list", []) if value
        ]
        if chunk_ids:
            instance = await get_kb(kb_name)
            records = await instance.lightrag.text_chunks.get_by_ids(chunk_ids)
            chunks = _automatic_tag_chunk_records([
                dict(record) for record in (records or []) if isinstance(record, dict)
            ])
            expected_ids = set(chunk_ids)
            loaded_ids = {chunk["chunk_id"] for chunk in chunks}
            if loaded_ids == expected_ids:
                return chunks, {
                    "chunk_count": len(chunks),
                    "status_retries": attempt,
                    "status_repaired": False,
                    "chunk_source": "doc_status",
                }
            kb_logger.warning(
                "[AUTO-TAGS] doc-status chunks incomplete; KB=%s doc=%s expected=%s loaded=%s",
                kb_name, document_id, len(expected_ids), len(loaded_ids),
            )
        elif attempt < 2:
            kb_logger.info(
                "[AUTO-TAGS] doc-status chunks not visible; retry=%s/2 KB=%s doc=%s",
                attempt + 1, kb_name, document_id,
            )
            await asyncio.sleep(0.2)

    instance = instance or await get_kb(kb_name)
    try:
        chunks = _automatic_tag_chunk_records(
            await query_chunks_by_document_id(instance.lightrag, document_id)
        )
    except PersistedChunkQueryError:
        kb_logger.warning(
            "[AUTO-TAGS] persisted chunk fallback unavailable; KB=%s doc=%s",
            kb_name, document_id, exc_info=True,
        )
        return [], {
            "chunk_count": 0,
            "status_retries": 2,
            "status_repaired": False,
            "chunk_source": "unavailable",
        }
    if not chunks:
        kb_logger.warning(
            "[AUTO-TAGS] no persisted chunks; upload remains available KB=%s doc=%s",
            kb_name, document_id,
        )
        return [], {
            "chunk_count": 0,
            "status_retries": 2,
            "status_repaired": False,
            "chunk_source": "none",
        }

    recovered_ids = [chunk["chunk_id"] for chunk in chunks]
    repaired = False
    if status_info:
        repaired_status = dict(status_info)
        repaired_status["chunks_list"] = recovered_ids
        repaired_status["chunks_count"] = len(recovered_ids)
        try:
            await instance.lightrag.doc_status.upsert({document_id: repaired_status})
            await instance.lightrag.doc_status.index_done_callback()
            repaired = True
            kb_logger.info(
                "[AUTO-TAGS] repaired doc-status from PG chunks; KB=%s doc=%s chunks=%s",
                kb_name, document_id, len(recovered_ids),
            )
        except Exception:
            kb_logger.warning(
                "[AUTO-TAGS] PG chunk fallback succeeded but doc-status repair failed; KB=%s doc=%s",
                kb_name, document_id, exc_info=True,
            )
    else:
        kb_logger.warning(
            "[AUTO-TAGS] PG chunk fallback found chunks but doc-status is unavailable; KB=%s doc=%s",
            kb_name, document_id,
        )
    kb_logger.info(
        "[AUTO-TAGS] using PG chunk fallback; KB=%s doc=%s chunks=%s",
        kb_name, document_id, len(recovered_ids),
    )
    return chunks, {
        "chunk_count": len(chunks),
        "status_retries": 2,
        "status_repaired": repaired,
        "chunk_source": "postgres",
    }


async def _generate_uploaded_document_tags(
    kb_name: str,
    document_id: str,
    *,
    filename: str = "",
    user_id: int,
) -> dict[str, Any]:
    """Generate local keyword tags for one canonical persisted document ID."""
    from raganything.services.auto_tagging import (
        automatic_tagging_enabled,
        build_automatic_tag_plan,
    )
    from raganything.services.kb_tag_repo import replace_automatic_document_tags

    if not automatic_tagging_enabled():
        return {
            "assigned": 0, "skipped": 0, "document_tags": 0, "chunk_tags": 0,
            "chunk_count": 0, "status_retries": 0, "status_repaired": False,
            "chunk_source": "disabled",
        }
    chunks, recovery = await _load_automatic_tag_chunks(kb_name, document_id)
    if not chunks:
        return {
            "assigned": 0, "skipped": 0, "document_tags": 0, "chunk_tags": 0,
            **recovery,
        }
    plan = build_automatic_tag_plan(chunks, filename=filename)
    result = await replace_automatic_document_tags(
        kb_name,
        document_id,
        plan.document_tags,
        plan.chunk_tags,
        user_id=user_id,
    )
    return {**result, **recovery}


async def _process_uploaded_file(
    task_id: str, file_path: str, filename: str,
    kb_name: str = "default", chunking_strategy: str = "", user_id: int = 0,
    enable_image: bool | None = None,
    enable_table: bool | None = None,
    enable_equation: bool | None = None,
    enable_video: bool | None = None,
):
    """Background upload processing via isolated subprocess.

    This function coordinates with ws_service and state_service for
    progress reporting and status tracking.

    Args:
        task_id: Unique task identifier
        file_path: Path to the uploaded file
        filename: Original filename
        kb_name: Target KB name
        chunking_strategy: Chunking strategy override
        user_id: Owner user ID
    """
    from raganything.services.ws_service import ws_broadcast, emit_progress, add_event
    from raganything.services.state_service import (
        processing_tasks, upsert_task_state, update_task_progress, complete_task,
    )

    actual_strategy = chunking_strategy or CHUNKING_STRATEGY
    task_data = {
        "id": task_id, "file": filename, "status": "processing",
        "started_at": datetime.now().isoformat(), "progress": 0,
        "kb": kb_name, "user_id": user_id,
        "phase": "initializing",
        "phase_status": "start",
        "message": "初始化处理环境",
        "chunking_strategy": actual_strategy,
    }
    await upsert_task_state(task_id, task_data)
    await add_event("upload_start", file=filename, task_id=task_id, user_id=user_id)
    # Register for dedup tracking (inside try — file I/O can fail)
    file_hash = None
    worker_progress_state = {"track": "text"}
    try:
        # Compute file hash and register for dedup (may fail if file was removed)
        file_hash = _compute_file_hash(file_path)
        _register_processing_file(kb_name, file_hash, task_id)

        # Update PG uploaded_files status → processing
        await pg_update_upload_status_by_task_id(
            task_id,
            "processing",
            kb_name=kb_name,
            error_message="",
        )
        kb_logger.info(f"[UPLOAD] 任务={task_id} 文件={filename} KB={kb_name} 策略={actual_strategy}")

        worker_script = Path(__file__).parent.parent.parent / "process_worker.py"
        cmd = [
            sys.executable, str(worker_script),
            "--file", str(Path(file_path).resolve()),
            "--kb", kb_name,
            "--strategy", actual_strategy,
        ]
        # ── Per-upload multimodal flags ─────────────────
        if enable_image is not None:
            cmd.append("--enable-image")
            cmd.append("true" if enable_image else "false")
        if enable_table is not None:
            cmd.append("--enable-table")
            cmd.append("true" if enable_table else "false")
        if enable_equation is not None:
            cmd.append("--enable-equation")
            cmd.append("true" if enable_equation else "false")
        if enable_video is not None:
            cmd.append("--enable-video")
            cmd.append("true" if enable_video else "false")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent.parent),
            env=_worker_subprocess_env(),
        )

        # Track worker process for KB deletion to kill it if needed
        _kb_worker_procs.setdefault(kb_name, []).append((proc, task_id))

        worker_output_lines: list[str] = []

        async def _read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    worker_output_lines.append(text)
                    kb_logger.info(f"[WORKER:{task_id}] {text}")
                    # Parse structured progress lines from worker
                    m = re.match(
                        r"\[PROGRESS\]\s+phase=(\S+)\s+status=(\S+)(?:\s+file=(.+))?",
                        text,
                    )
                    progress_update = _parse_worker_progress_line(text, worker_progress_state)
                    if progress_update and task_id in processing_tasks:
                        current_pct = processing_tasks[task_id].get("progress", 0) or 0
                        next_pct = progress_update.get("progress")
                        if next_pct is None:
                            next_pct = current_pct
                        else:
                            next_pct = max(current_pct, next_pct)
                        await update_task_progress(
                            task_id,
                            next_pct,
                            message=progress_update.get("message", ""),
                            phase=progress_update.get("phase", ""),
                            phase_status=progress_update.get("phase_status", ""),
                        )
                        await ws_broadcast({
                            "type": "progress",
                            "task_id": task_id,
                            "progress": next_pct,
                            "phase": progress_update.get("phase", ""),
                            "phase_status": progress_update.get("phase_status", ""),
                            "message": progress_update.get("message", ""),
                        })

        stdout_task = asyncio.ensure_future(_read_stream(proc.stdout))
        stderr_task = asyncio.ensure_future(_read_stream(proc.stderr))
        try:
            timeout_sec = int(os.getenv("PROCESS_TIMEOUT", "3600"))
            await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"子进程处理超时（{timeout_sec // 60}分钟），"
                "文档过大或图片过多，可设置环境变量 PROCESS_TIMEOUT 调整"
            )
        await stdout_task
        await stderr_task

        # Worker completed — remove from tracking list
        try:
            _kb_worker_procs.setdefault(kb_name, []).remove((proc, task_id))
        except ValueError:
            pass  # already removed by cleanup_kb_resources

        # Check worker output for merge/extraction errors
        worker_has_errors = any(
            "ERROR:" in line and ("Merging stage failed" in line or "chunks=0" in line)
            for line in worker_output_lines
        )

        if proc.returncode != 0:
            # Exit code 3 = worker conflict (file already locked by another worker)
            if proc.returncode == 3:
                conflict_lines = [l for l in worker_output_lines if "already being processed" in l or "active processor" in l]
                conflict_detail = conflict_lines[0] if conflict_lines else "文件正在被另一个 Worker 处理"
                raise RuntimeError(f"处理冲突: {conflict_detail}")
            failure_lines = [
                line for line in worker_output_lines
                if (
                    "ERROR" in line
                    or "未捕获异常:" in line
                    or "处理失败:" in line
                    or "Traceback (most recent call last)" in line
                    or "OpenBLAS" in line
                    or "MemoryError" in line
                    or "Exception:" in line
                )
            ]
            readable_lines = [line for line in failure_lines if "Traceback" not in line]
            if readable_lines:
                error_detail = "; ".join(readable_lines[-2:])
            else:
                diagnostic_tail = [line for line in worker_output_lines[-12:] if line]
                error_detail = "; ".join(diagnostic_tail[-3:]) if diagnostic_tail else f"exit code {proc.returncode}"
            error_detail = error_detail[:600]
            raise RuntimeError(f"子进程处理失败: {error_detail}")

        if worker_has_errors:
            error_lines = [l for l in worker_output_lines if "ERROR:" in l and "Merging" in l]
            error_detail = error_lines[0] if error_lines else "Merging stage failed"
            raise RuntimeError(f"子进程实体提取失败 (chunks=0): {error_detail}")

        # Verify data was actually persisted: the worker may exit 0 even when
        # LightRAG internally marked the document as failed.
        persisted_filename = os.path.basename(file_path)
        document_id = await _verify_document_persisted(kb_name, persisted_filename)

        # Clear cached instance so next query reloads from disk.
        # ⚠️ Do NOT call finalize_storages() on the cached instance — the
        # worker subprocess already persisted the latest data to disk via
        # RAGAnything.finalize_storages().  The server's cached instance
        # holds PRE-WORKER state and would overwrite fresh data.
        if kb_name in kb_instances:
            del kb_instances[kb_name]
            kb_logger.info(f"[KB] 清除缓存实例: {kb_name}（子进程写入新数据）")

        await emit_progress(task_id, 100, "处理完成")
        # Tags are generated after every chunk is durable. They improve linking
        # and scoped Q&A, but must not make an otherwise successful upload fail.
        if document_id:
            try:
                tag_result = await _generate_uploaded_document_tags(
                    kb_name, document_id, filename=filename, user_id=user_id,
                )
                kb_logger.info(
                    "[AUTO-TAGS] generated KB=%s doc=%s file=%s source=%s assigned=%s document_tags=%s chunk_tags=%s skipped=%s",
                    kb_name, document_id, filename, tag_result["chunk_source"],
                    tag_result["assigned"], tag_result["document_tags"],
                    tag_result["chunk_tags"], tag_result["skipped"],
                )
            except Exception:
                kb_logger.warning(
                    "[AUTO-TAGS] generation failed but upload remains available: kb=%s doc=%s file=%s",
                    kb_name, document_id, filename, exc_info=True,
                )
        else:
            kb_logger.warning(
                "[AUTO-TAGS] deferred because canonical document ID is unavailable; KB=%s file=%s",
                kb_name, filename,
            )
        await complete_task(task_id)
        if task_id in processing_tasks:
            processing_tasks[task_id]["chunking_strategy"] = actual_strategy
        await add_event("upload_complete", file=filename, task_id=task_id, kb=kb_name, user_id=user_id)
        await ws_broadcast({"type": "upload_done", "task_id": task_id, "filename": filename, "kb": kb_name})
        # Update PG uploaded_files status → completed
        await pg_update_upload_status_by_task_id(
            task_id,
            "completed",
            kb_name=kb_name,
            error_message="",
        )
        _unregister_processing_file(kb_name, file_hash)

    except Exception as e:
        # Remove worker from tracking list (may not exist if exception was pre-spawn)
        try:
            _kb_worker_procs.get(kb_name, []).remove((proc, task_id))
        except (NameError, ValueError):
            pass

        # If the KB is being deleted (cleanup_kb_resources), skip all
        # state writes to avoid zombie processing_tasks entries and
        # writes to deleted storage directories.
        if kb_name in _kbs_being_deleted:
            kb_logger.warning(
                f"[UPLOAD] KB '{kb_name}' 已被删除，跳过失败状态写入: "
                f"file={filename} task={task_id}"
            )
            return

        await _finalize_failed_upload(
            task_id,
            kb_name,
            filename,
            user_id,
            str(e),
            file_hash,
            actual_strategy,
        )


# ── Per-KB Queue Drain ────────────────────────────────────

async def _drain_kb_queue(kb_name: str) -> None:
    """Drain the per-KB processing queue, one file at a time.

    This coroutine is started automatically when the first file enters an
    empty queue.  It processes files sequentially (respecting
    ``_MAX_CONCURRENT_FILES``) and exits when the queue is empty.
    """
    import raganything.routers.shared as _rshared

    # Prevent duplicate drain coroutines for the same KB
    if _rshared._kb_draining.get(kb_name):
        kb_logger.debug(f"[QUEUE] Drain 已在运行: {kb_name}")
        return
    _rshared._kb_draining[kb_name] = True

    queue = _rshared._kb_queues.setdefault(kb_name, asyncio.Queue())

    # Track whether we have a pre-fetched task (avoids TOCTOU on empty check)
    _next_task = None

    try:
        kb_logger.info(f"[QUEUE] 开始 drain: {kb_name}")
        while True:
            # ── Fetch next task (with timeout to avoid empty() race) ──
            if _next_task is not None:
                task_info = _next_task
                _next_task = None
            else:
                try:
                    task_info = await asyncio.wait_for(queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    kb_logger.info(f"[QUEUE] 队列已空 (超时): {kb_name}")
                    break

            # Sentinel — KB was deleted, exit immediately
            if task_info is _QUEUE_SENTINEL:
                kb_logger.info(f"[QUEUE] 收到停止信号 (KB 已删除): {kb_name}")
                break

            kb_logger.info(
                f"[QUEUE] 取出任务: file={task_info.get('filename', '?')} "
                f"kb={kb_name} queue_remaining={queue.qsize()}"
            )

            task_id = task_info.get("task_id", "")
            upload_record = None
            if task_id:
                upload_record = await pg_get_upload_by_task_id(
                    task_id,
                    kb_name=kb_name,
                    is_admin=True,
                )
                if upload_record and upload_record.get("status") == "deleted":
                    _unregister_processing_file(kb_name, upload_record.get("file_hash", ""))
                    kb_logger.info(
                        f"[QUEUE] 璺宠繃宸插垹闄ょ殑浠诲姟: task={task_id} kb={kb_name}"
                    )
                    continue
                if upload_record and upload_record.get("status") == "queued":
                    claimed = await pg_claim_upload_task(task_id, kb_name)
                    if not claimed:
                        refreshed = await pg_get_upload_by_task_id(
                            task_id,
                            kb_name=kb_name,
                            is_admin=True,
                        )
                        if refreshed and refreshed.get("status") == "deleted":
                            _unregister_processing_file(kb_name, refreshed.get("file_hash", ""))
                            kb_logger.info(
                                f"[QUEUE] 浠诲姟鍦ㄨ皟搴﹀墠宸茶鍒犻櫎: task={task_id} kb={kb_name}"
                            )
                            continue
                        if refreshed and refreshed.get("status") != "processing":
                            kb_logger.warning(
                                f"[QUEUE] 浠诲姟鐘舵€佸紓甯革紝璺宠繃: task={task_id} "
                                f"status={refreshed.get('status')} kb={kb_name}"
                            )
                            continue

            # Notify frontend that queue position has changed
            try:
                from raganything.services.ws_service import ws_broadcast
                await ws_broadcast({
                    "type": "queue_position",
                    "kb": kb_name,
                    "filename": task_info.get("filename", ""),
                    "queue_remaining": queue.qsize(),
                })
            except Exception:
                pass  # WebSocket failure shouldn't block processing

            try:
                await _process_uploaded_file(**task_info)
            except Exception as exc:
                # Single file failure must not kill the drain loop.
                kb_logger.error(
                    f"[QUEUE] 文件处理失败 (继续队列): "
                    f"file={task_info.get('filename', '?')} error={exc}"
                )

            # Pre-fetch next task to avoid the unreliable queue.empty() race.
            # If nothing arrives within 1.0s, the drain exits cleanly.
            try:
                _next_task = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                kb_logger.info(f"[QUEUE] 队列已空: {kb_name}")
                break
    finally:
        _rshared._kb_draining[kb_name] = False
        kb_logger.debug(f"[QUEUE] Drain 已退出: {kb_name}")


# Per-KB locks to prevent duplicate drain coroutines from racing
_drain_start_locks: dict[str, asyncio.Lock] = {}


async def _ensure_queue_draining(kb_name: str) -> tuple:
    """Start drain if not already running; return queue and position info.

    Returns:
        (queue, position, queue_size) — position is 1-based.
    """
    import raganything.routers.shared as _rshared

    lock = _drain_start_locks.setdefault(kb_name, asyncio.Lock())

    async with lock:
        queue = _rshared._kb_queues.setdefault(kb_name, asyncio.Queue())
        qsize = queue.qsize()

        if not _rshared._kb_draining.get(kb_name):
            task = asyncio.create_task(_drain_kb_queue(kb_name))
            task.add_done_callback(
                lambda t: kb_logger.error(
                    f"[QUEUE] Drain 异常崩溃: {kb_name}",
                    exc_info=t.exception(),
                ) if t.exception() else None
            )

    return queue, qsize


WORKFLOW_DIR = Path("./workflows")
WORKFLOW_DIR.mkdir(exist_ok=True)


# ── Utility: Citation block builder ────────────────────────

def _build_citation_block(ctx: str, answer: str) -> str:
    """Build a citation source block from retrieval context.

    Parses [来源 文档名] markers in the context and builds a structured
    reference summary. Returns empty string if none found or already present.

    Args:
        ctx: Retrieval context text
        answer: LLM answer text

    Returns:
        Citation block string or empty string
    """
    import re as _re
    if ctx is None or answer is None:
        return ""
    if '📚 参考来源' in answer or '【引用来源】' in answer:
        return ""

    seen_docs: set[str] = set()
    for m in _re.finditer(r'\[来源\s*([^\]]+?)\]', ctx):
        name = m.group(1).strip()
        if name and not name.isdigit():
            seen_docs.add(name)

    if not seen_docs:
        return ""

    lines = ["\n📚 参考来源"]
    for doc in sorted(seen_docs):
        lines.append(f"[来源 {doc}]")
    lines.append("\n（系统自动追加：LLM 未生成引用块，此处仅列出相关文档名。）")

    return "\n".join(lines)


async def _get_kb_doc_list(kb: str) -> str:
    """Get formatted list of available documents in a KB for prompt context.

    Args:
        kb: KB name

    Returns:
        Formatted document list string for LLM prompts
    """
    try:
        instance = await get_kb(kb)
        doc_names = set()
        if hasattr(instance, '_ensure_chunk_source_cache'):
            await instance._ensure_chunk_source_cache()
        if hasattr(instance, '_chunk_source_cache') and instance._chunk_source_cache:
            for info in instance._chunk_source_cache.values():
                name = info.get('document_name', '')
                if name and name != 'unknown':
                    doc_names.add(name)
        if not doc_names and instance.lightrag:
            try:
                store = instance.lightrag.doc_status
                if hasattr(store, '_data'):
                    async with store._storage_lock:
                        for ds in store._data.values():
                            fp = ds.get('file_path', '')
                            if fp:
                                doc_names.add(fp)
            except Exception:
                pass

        if not doc_names:
            return ""

        lines = [f"- 《{name}》" for name in sorted(doc_names)[:10]]
        return (
            "## 可用文档\n"
            "以下文档在检索内容中以 `[来源 文档名]` 标注。"
            "回答时请用 `[来源 文档名]` 标注每条引用来源。\n"
            + "\n".join(lines)
        )
    except Exception:
        return ""


# ── Utility: Entity type inference ─────────────────────────

def infer_entity_type(name: str) -> str:
    """Infer entity type from name for knowledge graph classification.

    Args:
        name: Entity name string

    Returns:
        Entity type: 'organization', 'method', 'metric', 'image',
        'equation', 'component', 'ui', or 'concept'
    """
    n = str(name).lower()
    if any(w in n for w in ['大学', '学院', '公司', '医院', '研究所', '实验室',
                              'institute', 'university', 'hospital']):
        return 'organization'
    if any(w in n for w in ['模型', '算法', '方法', '网络', '框架', 'model',
                              'algorithm', 'network', 'method', 'mobilenet',
                              'resnet', 'efficientnet', 'cnn', 'rnn', 'transformer']):
        return 'method'
    if n.replace('.', '').replace('%', '').replace('-', '').isdigit() or \
       any(c in n for c in ['%', 'ms', 'mb', 'db']):
        return 'metric'
    if any(w in n for w in ['.png', '.jpg', '.jpeg', '.gif', 'image', '图像', '图片', '图']):
        return 'image'
    if any(w in n for w in ['函数', '公式', 'function', 'equation', 'loss',
                              'sigmoid', 'relu', 'softmax']):
        return 'equation'
    if any(w in n for w in ['层', '卷积', 'layer', 'conv', 'batch', 'norm',
                              'dropout', 'pool']):
        return 'component'
    if any(w in n for w in ['接口', 'api', '页面', '系统', '界面', 'interface',
                              'page', 'system', 'button', 'icon', 'form']):
        return 'ui'
    if any(w in n for w in ['数据', '精度', '准确率', '召回', 'f1', 'accuracy',
                              'precision', 'recall']):
        return 'metric'
    return 'concept'


# ── Multimodal Retroactive Processing ──────────────────────

async def _reprocess_multimodal_for_kb(kb_name: str, user_id: int = 1):
    """Reprocess multimodal content for documents that missed it.

    Scans doc_status in a KB for documents where ``multimodal_processed``
    is not ``True``, locates the original file, re-parses (hitting the
    parse_cache when available), and processes only multimodal items
    (images, tables, equations).  Text content is NOT re-inserted.

    Args:
        kb_name: Knowledge base name
        user_id: User ID for audit logging

    Returns:
        dict with ``processed``, ``skipped``, ``total``, ``message``
    """
    from raganything.utils._content import separate_content
    from raganything.services.ws_service import ws_broadcast, add_event

    instance = await get_kb(kb_name)
    if instance is None or instance.lightrag is None:
        raise ValueError(f"KB '{kb_name}' 未初始化")

    # Verify at least one modal processor is registered
    active_processors = [
        k for k, v in (instance.modal_processors or {}).items() if v is not None
    ]
    if not active_processors:
        raise ValueError(
            f"KB '{kb_name}' 未启用任何多模态处理器，请在设置页面开启后再执行回溯"
        )
    kb_logger.info(
        f"[REPROCESS-MULTIMODAL] KB={kb_name} 活跃处理器: {active_processors}"
    )

    # Scan doc_status for documents needing multimodal processing
    all_docs = await _load_doc_status_json(kb_name)
    if not all_docs:
        return {"processed": 0, "skipped": 0, "total": 0, "message": "知识库无文档记录"}

    needs_processing: list[tuple[str, dict]] = []
    for doc_id, info in all_docs.items():
        if info.get("status") == "failed":
            continue
        if not is_multimodal_processed(info):
            needs_processing.append((doc_id, dict(info)))

    if not needs_processing:
        return {
            "processed": 0, "skipped": 0, "total": 0,
            "message": "所有文档已完成多模态处理",
        }

    kb_logger.info(
        f"[REPROCESS-MULTIMODAL] KB={kb_name} "
        f"发现 {len(needs_processing)} 个文档需要回溯处理"
    )

    upload_dir = Path("./uploads")
    processed = 0
    skipped = 0
    total = len(needs_processing)

    await ws_broadcast({
        "type": "reprocess_start",
        "kb": kb_name,
        "total": total,
        "message": f"开始回溯处理 {total} 个文档的多模态内容",
    })

    for doc_id, info in needs_processing:
        file_ref = info.get("file_path", "")
        kb_logger.info(
            f"[REPROCESS-MULTIMODAL] [{processed + skipped + 1}/{total}] "
            f"file={file_ref} doc_id={doc_id[:16]}..."
        )

        # Locate the original file
        original_path: Path | None = None
        if file_ref:
            # 1. Try uploads/<file_ref> directly (most common case)
            candidate = upload_dir / Path(file_ref).name
            if candidate.exists():
                original_path = candidate
            # 2. Exact path as stored
            if original_path is None:
                candidate = Path(file_ref)
                if candidate.exists():
                    original_path = candidate
            # 3. Search uploads by basename
            if original_path is None and upload_dir.exists():
                basename = Path(file_ref).name
                for f in upload_dir.iterdir():
                    if f.is_file() and f.name.endswith(basename):
                        original_path = f
                        break
            # 4. Fuzzy match in uploads (prefix match)
            if original_path is None and upload_dir.exists():
                basename = Path(file_ref).name
                for f in upload_dir.iterdir():
                    if f.is_file() and basename in f.name:
                        original_path = f
                        break

        if original_path is None:
            kb_logger.warning(
                f"[REPROCESS-MULTIMODAL] 找不到原始文件: {file_ref}，跳过"
            )
            skipped += 1
            continue

        try:
            # Try parse cache lookup first — read directly from the
            # JSON file to handle parser/config changes between uploads.
            content_list = None
            kb_workspace = Path(kb_dir(kb_name))
            cache_file = kb_workspace / "kv_store_parse_cache.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as _f:
                        all_cache = json.load(_f)
                    for entry in all_cache.values():
                        if isinstance(entry, dict) and entry.get("doc_id") == doc_id:
                            content_list = entry.get("content_list")
                            kb_logger.info(
                                f"[REPROCESS-MULTIMODAL] 缓存命中: {file_ref}"
                            )
                            break
                except Exception as _e:
                    kb_logger.warning(
                        f"[REPROCESS-MULTIMODAL] 缓存读取失败: {_e}"
                    )

            if content_list is None:
                # Fallback: re-parse. Use absolute path for cache key match.
                content_list, _ = await instance.parse_document(
                    str(original_path.resolve())
                )

            # Separate multimodal content
            _, multimodal_items = separate_content(content_list)

            if not multimodal_items:
                kb_logger.info(
                    f"[REPROCESS-MULTIMODAL] 文档无多模态内容，标记完成: {file_ref}"
                )
                await instance._mark_multimodal_processing_complete(doc_id)
                processed += 1
                continue

            kb_logger.info(
                f"[REPROCESS-MULTIMODAL] {file_ref}: "
                f"{len(multimodal_items)} 个多模态条目 → 开始处理"
            )

            # Process multimodal content (VLM descriptions, entity extraction)
            await instance._process_multimodal_content(
                multimodal_items, str(original_path), doc_id
            )

            processed += 1
            await ws_broadcast({
                "type": "reprocess_progress",
                "kb": kb_name,
                "processed": processed,
                "skipped": skipped,
                "total": total,
                "current_doc": file_ref,
            })

        except Exception as e:
            kb_logger.error(
                f"[REPROCESS-MULTIMODAL] 处理失败 {file_ref}: {e}"
            )
            skipped += 1

    result = {
        "processed": processed,
        "skipped": skipped,
        "total": total,
        "message": (
            f"回溯处理完成: {processed} 个成功"
            + (f", {skipped} 个跳过" if skipped else "")
        ),
    }
    await add_event(
        "reprocess_multimodal_done",
        kb=kb_name, user_id=user_id, **result,
    )
    await ws_broadcast({
        "type": "reprocess_done", "kb": kb_name, **result,
    })
    return result


__all__ = [
    "kb_instances",
    "active_kb",
    "KB_META_FILE",
    "load_kb_meta",
    "save_kb_meta",
    "kb_dir",
    "get_kb",
    "create_kb",
    "delete_kb",
    "list_kbs",
    "list_kbs_by_domain",
    "create_rag",
    "_fix_stuck_doc_status",
    "_recover_stuck_documents",
    "_stuck_recovery_loop",
    "_process_uploaded_file",
    "_reprocess_multimodal_for_kb",
    "_build_citation_block",
    "_get_kb_doc_list",
    "infer_entity_type",
    "create_vision_embed_func",
    "API_KEY",
    "BASE_URL",
    "LLM_MODEL",
    "VISION_MODEL",
    "EMB_MODEL",
    "EMB_DIM",
    "WORKING_DIR",
    "CHUNKING_STRATEGY",
    "WORKFLOW_DIR",
]
