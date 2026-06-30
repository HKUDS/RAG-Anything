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
from typing import Any, Optional
import os
import sys
import re
import asyncio
import logging
from datetime import datetime
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
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

# ── Configuration ─────────────────────────────────────────
API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
WORKING_DIR = os.getenv("WORKING_DIR", "./rag_storage")
CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "recursive")

# ── KB State ──────────────────────────────────────────────
kb_instances: dict[str, RAGAnything] = {}
_kb_locks: dict[str, asyncio.Lock] = {}
_kb_cache_time: dict[str, float] = {}
active_kb: str = "default"
KB_META_FILE = Path("./rag_storage_kb_meta.json")

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

# ── Worker Process Tracking ─────────────────────────────────
# Maps kb_name -> list of (asyncio.subprocess.Process, task_id) for
# running worker subprocesses.  Used by KB deletion to kill workers.
_kb_worker_procs: dict[str, list] = {}


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


# ── KB Metadata Persistence ────────────────────────────────
#
# Dispatch architecture (matches auth.py pattern):
#   - PG available → load/save from kb_metadata table
#   - PG unavailable → load/save from rag_storage_kb_meta.json (legacy)
#
# Both paths are async-safe. PG operations use the shared pool from
# pg_state_repo.py. File operations run via run_in_executor to avoid
# blocking the event loop on disk I/O.


def _pg_kb_meta_ready() -> bool:
    """Check if PG KB metadata backend is available."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except (RuntimeError, ImportError):
        return False


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


def _load_kb_meta_file() -> dict[str, Any]:
    """Load KB metadata from JSON file (sync, for internal use)."""
    if KB_META_FILE.exists():
        with open(KB_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_kb_meta_file(meta: dict[str, Any]) -> None:
    """Persist KB metadata to JSON file atomically (sync, for internal use)."""
    tmp = KB_META_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(KB_META_FILE)


async def load_kb_meta() -> dict[str, Any]:
    """Load KB metadata — dispatched to PG when available, file fallback.

    Returns:
        Dict keyed by KB name: {name: {name, created, domain, ...}, ...}
        Empty dict if no KBs exist (caller should create default if needed).
    """
    if _pg_kb_meta_ready():
        try:
            from raganything.services.pg_kb_meta_repo import pg_load_kb_meta
            result = await pg_load_kb_meta()
            if result:
                return result
        except Exception:
            kb_logger.warning("PG KB meta load failed, falling back to file")

    # File fallback — run blocking I/O in thread pool
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _load_kb_meta_file)


async def save_kb_meta(meta: dict[str, Any]) -> None:
    """Persist KB metadata — PG + file dual-write when PG available.

    Args:
        meta: Full KB metadata dict: {name: {name, created, ...}, ...}
    """
    # Always write to file first (safe, atomic, always works)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _save_kb_meta_file, meta)

    # If PG available, also write to PG (shadow write, best-effort)
    if _pg_kb_meta_ready():
        try:
            from raganything.services.pg_kb_meta_repo import pg_save_all_kb_meta
            await pg_save_all_kb_meta(meta)
        except Exception:
            kb_logger.warning("PG KB meta save failed, file saved successfully")


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
    """Load doc_status data for a KB, dispatching PG → LightRAG API or file.

    Returns a dict with the same shape as kv_store_doc_status.json:
        {doc_id: {file_path, status, metadata, chunks_list, ...}, ...}

    When PG storage is active, queries LightRAG's PGDocStatusStorage.
    Otherwise reads the JSON file directly.
    """
    # Try PG path — try kb_instances first, then get_kb()
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
                # Fetch all statuses we know about
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
                    "PG doc_status load failed for KB %s, falling back to file",
                    kb_name, exc_info=True,
                )

    # File fallback
    status_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
    if status_path.exists():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: json.loads(status_path.read_text("utf-8"))
        )
    return {}


async def _save_doc_status_json(kb_name: str, data: dict[str, Any]) -> None:
    """Save doc_status data for a KB, dispatching PG → LightRAG API or file.

    When PG storage is active, writes via LightRAG's PGDocStatusStorage.upsert().
    Also writes to the JSON file as a safety fallback (dual-write pattern).
    """
    # Always write to file first (safety net)
    status_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
    loop = asyncio.get_running_loop()

    def _write_file():
        status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(status_path)

    await loop.run_in_executor(None, _write_file)

    # PG shadow write — try kb_instances first, then get_kb()
    if _pg_storage_ready():
        rag = kb_instances.get(kb_name)
        if rag is None:
            try:
                rag = await get_kb(kb_name)
            except Exception:
                pass
        if rag is not None and rag.lightrag and hasattr(rag.lightrag, "doc_status"):
            try:
                # Convert flat dict values to DocProcessingStatus-compatible dicts
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
            except Exception:
                kb_logger.warning(
                    "PG doc_status save failed for KB %s, file saved",
                    kb_name, exc_info=True,
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
                    "PG text_chunks load failed for KB %s, falling back to file",
                    kb_name, exc_info=True,
                )

    # File fallback
    chunks_path = Path(kb_dir(kb_name)) / "kv_store_text_chunks.json"
    if chunks_path.exists():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: json.loads(chunks_path.read_text("utf-8"))
        )
    return {}


async def _load_full_docs_json(kb_name: str) -> dict[str, Any]:
    """Load full_docs data for a KB, dispatching PG → LightRAG API or file.

    Returns a dict with the same shape as kv_store_full_docs.json.
    """
    # Try PG path — try kb_instances first, then get_kb()
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
                    "PG full_docs load failed for KB %s, falling back to file",
                    kb_name, exc_info=True,
                )

    # File fallback
    fdp = Path(kb_dir(kb_name)) / "kv_store_full_docs.json"
    if fdp.exists():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: json.loads(fdp.read_text("utf-8"))
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
                        cache_time = _kb_cache_time.get(name, 0)
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
            kb_instances[name] = instance
            _kb_cache_time[name] = _time.time()
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
    from raganything.services.state_service import processing_tasks
    tasks_removed = 0
    for tid in list(processing_tasks.keys()):
        if processing_tasks[tid].get("kb", "") == name:
            del processing_tasks[tid]
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
    _kb_cache_time.pop(name, None)

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

    # ── 9. Remove metadata ───────────────────────────────
    meta = await load_kb_meta()
    if name in meta:
        del meta[name]
        await save_kb_meta(meta)

    # ── 10. Reset active KB if needed ────────────────────
    if _rshared.active_kb == name:
        _rshared.active_kb = "default"

    # ── 11. Invalidate query cache ───────────────────────
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
    """List all KB metadata entries — PG-dispatched."""
    if _pg_kb_meta_ready():
        try:
            from raganything.services.pg_kb_meta_repo import pg_load_kb_meta
            return await pg_load_kb_meta()
        except Exception:
            kb_logger.warning("PG list_kbs failed, falling back to file")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _load_kb_meta_file)


async def list_kbs_by_domain(domain: str) -> dict[str, Any]:
    """List KB metadata entries filtered by domain.

    Args:
        domain: Domain filter value (e.g. ``"manufacturing"``, ``"general"``).

    Returns:
        Dict of KB name → metadata for KBs matching the domain.
        KBs without a ``domain`` field are treated as ``"general"`` for
        backward compatibility with KBs created before this field existed.
    """
    if _pg_kb_meta_ready():
        try:
            from raganything.services.pg_kb_meta_repo import pg_list_kbs_by_domain
            rows = await pg_list_kbs_by_domain(domain)
            # Convert list response back to dict for backward compatibility
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
        except Exception:
            kb_logger.warning("PG list_kbs_by_domain failed, falling back to file")
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, _load_kb_meta_file)
    return {
        name: info for name, info in meta.items()
        if info.get("domain", "general") == domain
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
                    image_data=None, messages=None, **kw):
        if messages is not None:
            return openai_complete_if_cache(
                _vision_model, "", system_prompt=None, history_messages=[],
                messages=messages, api_key=_api_key, base_url=_base_url, **kw,
            )
        elif image_data is not None:
            return openai_complete_if_cache(
                _vision_model, "", system_prompt=None, history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
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
        "semantic": make_semantic_chunking(_get_embedding_func_for_chunk),
        "agentic": make_agentic_chunking(_get_llm_func_for_chunk, _llm_model),
    }
    chosen_chunking_func = chunking_strategy_map.get(chunking_strategy)

    lightrag_kwargs = {
        "chunk_token_size": chunk_token_size,
        "chunk_overlap_token_size": _env_int("CHUNK_OVERLAP", 100, max_val=500),
        "enable_llm_cache": os.getenv("ENABLE_LLM_CACHE", "true").lower() == "true",
        "enable_llm_cache_for_entity_extract": os.getenv("ENABLE_LLM_CACHE_FOR_EXTRACT", "true").lower() == "true",
        "embedding_batch_num": _env_int("EMBEDDING_BATCH_SIZE", 10, max_val=10),
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
    if _pg_storage_ready():
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

    return RAGAnything(config=config, llm_model_func=llm_func,
                       vision_model_func=vision_func, embedding_func=embedding_func,
                       vision_embed_func=vision_embed_func,
                       lightrag_kwargs=lightrag_kwargs)


# ── Recovery Lock (PG advisory + file fallback) ──────────────
# Multi-worker recovery lock. PG advisory lock auto-releases on connection
# close — no cleanup needed after worker crash.

import tempfile
import time as _time_module


def _acquire_recovery_lock(timeout_sec: float = 30.0) -> bool:
    """Attempt to acquire a PG advisory lock for recovery.

    When PG is available, uses ``pg_try_advisory_lock()`` which
    auto-releases on connection close. Falls back to file lock.

    Returns True if the lock was acquired.
    """
    # File-based fallback (sync, runs before async path is available)
    lock_path = Path(WORKING_DIR) / ".recovery.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = _time_module.time()
    try:
        if lock_path.exists():
            content = lock_path.read_text(encoding="utf-8").strip()
            try:
                lock_time = float(content)
                if now - lock_time < timeout_sec:
                    return False  # another process is actively recovering
            except ValueError:
                pass  # corrupt lock file, overwrite
        lock_path.write_text(str(now), encoding="utf-8")
        return True
    except Exception:
        return False


async def _acquire_recovery_lock_pg() -> bool:
    """Acquire a PG advisory lock (async, preferred)."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            locked = await conn.fetchval("SELECT pg_try_advisory_lock(987654)")
            return bool(locked)
    except Exception:
        return False


def _release_recovery_lock() -> None:
    """Release the recovery lock. PG advisory lock auto-releases on connection close."""
    lock_path = Path(WORKING_DIR) / ".recovery.lock"
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception:
        pass


async def _fix_stuck_doc_status(kb_name: str, filename: str):
    """Fix documents stuck in 'handling' state after subprocess crash/timeout.

    Uses PG-dispatch when PG storage is active, file fallback otherwise.

    Args:
        kb_name: KB name
        filename: The file whose doc_status may be stuck
    """
    try:
        data = await _load_doc_status_json(kb_name)
        if not data:
            return
        changed = False
        for doc_id, info in data.items():
            stored = info.get("file_path", "")
            stored_base = os.path.basename(stored)
            search_base = os.path.basename(filename)
            # Robust match: handles hash-prefixed uploads and full/partial paths
            # Length guard: prefix is exactly 9 chars (8 hex + 1 underscore)
            if (stored == filename
                    or stored_base == search_base
                    or (stored_base.endswith("_" + search_base)
                        and len(stored_base) - len(search_base) == 9)) \
                    and info.get("status") == "handling":
                info["status"] = "failed"
                info["error_msg"] = "处理中断：子进程异常退出或超时"
                changed = True
                kb_logger.warning(
                    f"[FIX-STUCK] 修复卡住的文档: {filename} (KB={kb_name}) handling→failed"
                )
        if changed:
            await _save_doc_status_json(kb_name, data)
    except Exception as ex:
        kb_logger.error(f"[FIX-STUCK] 修复失败: {ex}")


async def _recover_stuck_documents():
    """Scan all KBs and auto-complete documents that finished processing
    but are stuck with status='handling'.

    A document is recoverable when its ``metadata.processing_end_time`` is
    set (meaning the worker finished writing data) but the top-level
    ``status`` was never updated from ``handling`` to ``completed``.

    Uses a file-based lock (``.recovery.lock``) so only one worker runs
    recovery at a time in multi-worker deployments.
    """
    locked = await _acquire_recovery_lock_pg() or _acquire_recovery_lock()
    if not locked:
        kb_logger.debug("[Recovery] 另一进程正在执行恢复，跳过")
        return
    try:
        try:
            meta = await load_kb_meta()
        except Exception:
            return  # no KBs registered yet

        for kb_name in list(meta.keys()):
            try:
                data = await _load_doc_status_json(kb_name)
                if not data:
                    continue
                changed = False
                for doc_id, info in data.items():
                    if info.get("status") != "handling":
                        continue
                    end_time = info.get("metadata", {}).get("processing_end_time")
                    if end_time and end_time > 0:
                        info["status"] = "completed"
                        changed = True
                        kb_logger.info(
                            f"[Recovery] 修复卡住文档: {kb_name}/{doc_id[:16]} "
                            f"(processing_end={end_time})"
                        )
                if changed:
                    await _save_doc_status_json(kb_name, data)
                    # Clear cached instance so next query reloads from storage.
                    if kb_name in kb_instances:
                        del kb_instances[kb_name]
                        _kb_cache_time.pop(kb_name, None)
            except Exception as e:
                kb_logger.warning(f"[Recovery] 扫描 KB '{kb_name}' 异常: {e}")

        # ── Periodic orphan purge (once per recovery scan) ──
        for kb_name in list(meta.keys()):
            try:
                doc_data = await _load_doc_status_json(kb_name)
                if not doc_data:
                    continue
                valid_ids = set(doc_data.keys())
                ep = Path(kb_dir(kb_name)) / "kv_store_full_entities.json"
                if ep.exists():
                    entities_data = json.loads(ep.read_text(encoding="utf-8"))
                    orphan_count = sum(1 for k in entities_data if k not in valid_ids)
                    if orphan_count > 0:
                        try:
                            _inst = await get_kb(kb_name)
                            from raganything.routers.knowledge import _purge_all_orphans
                            await _purge_all_orphans(_inst, kb_name)
                            if kb_name in kb_instances:
                                del kb_instances[kb_name]
                                _kb_cache_time.pop(kb_name, None)
                        except Exception:
                            pass
            except Exception:
                pass
    finally:
        _release_recovery_lock()


async def _stuck_recovery_loop(interval_sec: int = 300):
    """Background asyncio task: periodically scan for stuck documents.

    Args:
        interval_sec: Seconds between scans (default 5 minutes)

    Uses a file-based lock (``.recovery.lock``) to deduplicate across
    workers.  The lock auto-expires after 30 seconds to recover from
    process crashes during recovery.
    """
    await asyncio.sleep(5)  # let startup settle first
    while True:
        try:
            await _recover_stuck_documents()
        except Exception as e:
            kb_logger.warning(f"[Recovery] 周期扫描异常: {e}")
        await asyncio.sleep(interval_sec)


# ── Document Upload Processing ─────────────────────────────

async def _verify_document_persisted(kb_name: str, filename: str) -> None:
    """Verify that a processed document has chunks in doc_status.

    Uses PG dispatch when PG storage is active, file fallback otherwise.

    Raises RuntimeError if the document is missing from doc_status or has
    zero chunks after worker subprocess reports success.
    """
    data = await _load_doc_status_json(kb_name)
    if not data:
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
            if chunks == 0:
                raise RuntimeError(
                    f"文档处理异常：chunks=0, status={status} (doc_id={doc_id[:16]})"
                )
            return
    raise RuntimeError(f"文档处理异常：doc_status 中未找到匹配记录 ({fname})")


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
    from raganything.services.state_service import processing_tasks, upsert_task_state

    task_data = {
        "id": task_id, "file": filename, "status": "processing",
        "started_at": datetime.now().isoformat(), "progress": 0,
        "kb": kb_name, "user_id": user_id,
    }
    processing_tasks[task_id] = task_data
    await upsert_task_state(task_id, task_data)
    await add_event("upload_start", file=filename, task_id=task_id, user_id=user_id)
    actual_strategy = chunking_strategy or CHUNKING_STRATEGY

    # Register for dedup tracking (inside try — file I/O can fail)
    file_hash = None
    try:
        # Compute file hash and register for dedup (may fail if file was removed)
        file_hash = _compute_file_hash(file_path)
        _register_processing_file(kb_name, file_hash, task_id)

        await emit_progress(task_id, 5, f"子进程处理: {filename}")
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

        await emit_progress(task_id, 10, "处理中...")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent.parent),
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
                    if m and task_id in processing_tasks:
                        phase = m.group(1)
                        status = m.group(2)
                        # Map phases to progress percentages
                        phase_map = {
                            "parsing": (5, 25),
                            "entity-extraction": (25, 55),
                            "embedding": (55, 75),
                            "graph-building": (75, 90),
                            "multimodal-tasks": (90, 98),
                        }
                        if phase in phase_map:
                            pct = phase_map[phase][1] if status == "done" else phase_map[phase][0]
                        else:
                            pct = processing_tasks[task_id].get("progress", 0)
                        processing_tasks[task_id]["progress"] = pct
                        processing_tasks[task_id]["phase"] = phase
                        processing_tasks[task_id]["phase_status"] = status
                        await ws_broadcast({
                            "type": "progress", "task_id": task_id,
                            "progress": pct, "phase": phase, "phase_status": status,
                            "message": f"{phase}: {status}",
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
            error_lines = [l for l in worker_output_lines if "ERROR" in l]
            error_detail = "; ".join(error_lines[-2:]) if error_lines else f"exit code {proc.returncode}"
            raise RuntimeError(f"子进程处理失败: {error_detail}")

        if worker_has_errors:
            error_lines = [l for l in worker_output_lines if "ERROR:" in l and "Merging" in l]
            error_detail = error_lines[0] if error_lines else "Merging stage failed"
            raise RuntimeError(f"子进程实体提取失败 (chunks=0): {error_detail}")

        # Verify data was actually persisted: the worker may exit 0 even when
        # LightRAG internally marked the document as failed.
        await _verify_document_persisted(kb_name, filename)

        # Clear cached instance so next query reloads from disk.
        # ⚠️ Do NOT call finalize_storages() on the cached instance — the
        # worker subprocess already persisted the latest data to disk via
        # RAGAnything.finalize_storages().  The server's cached instance
        # holds PRE-WORKER state and would overwrite fresh data.
        if kb_name in kb_instances:
            del kb_instances[kb_name]
            _kb_cache_time.pop(kb_name, None)
            kb_logger.info(f"[KB] 清除缓存实例: {kb_name}（子进程写入新数据）")

        await emit_progress(task_id, 100, "处理完成")
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["chunking_strategy"] = actual_strategy
        await add_event("upload_complete", file=filename, task_id=task_id, kb=kb_name, user_id=user_id)
        await ws_broadcast({"type": "upload_done", "task_id": task_id, "filename": filename, "kb": kb_name})
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

        processing_tasks[task_id]["status"] = "failed"
        processing_tasks[task_id]["error"] = str(e)
        await add_event("upload_error", file=filename, task_id=task_id, error=str(e), user_id=user_id)
        await _fix_stuck_doc_status(kb_name, filename)
        if file_hash is not None:
            _unregister_processing_file(kb_name, file_hash)


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

    try:
        kb_logger.info(f"[QUEUE] 开始 drain: {kb_name}")
        while True:
            try:
                # Block until a task is available
                task_info = await queue.get()
            except Exception:
                break

            # Sentinel — KB was deleted, exit immediately
            if task_info is _QUEUE_SENTINEL:
                kb_logger.info(f"[QUEUE] 收到停止信号 (KB 已删除): {kb_name}")
                break

            kb_logger.info(
                f"[QUEUE] 取出任务: file={task_info.get('filename', '?')} "
                f"kb={kb_name} queue_remaining={queue.qsize()}"
            )

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

            # Exit if the queue is now empty
            if queue.empty():
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
            asyncio.ensure_future(_drain_kb_queue(kb_name))

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
        if not info.get("multimodal_processed", False):
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
