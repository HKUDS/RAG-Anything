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
from typing import Any
import os
import sys
import re
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from collections import OrderedDict
from collections.abc import Mapping
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
_retry_cleanup_locks: dict[tuple[str, str], asyncio.Lock] = {}
_deferred_auto_tag_tasks: dict[asyncio.Task[Any], str] = {}
try:
    _AUTO_TAG_PLANNING_CONCURRENCY = int(
        os.getenv("AUTO_TAG_PLANNING_CONCURRENCY", "2")
    )
except ValueError:
    _AUTO_TAG_PLANNING_CONCURRENCY = 2
_auto_tag_planning_semaphore = asyncio.Semaphore(
    max(1, min(_AUTO_TAG_PLANNING_CONCURRENCY, 2))
)


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

    if "[PROGRESS] phase=model-preflight status=start" in text:
        return {
            "phase": "model-preflight",
            "phase_status": "start",
            "progress": 2,
            "message": "正在检查模型服务连接",
        }

    if "[PROGRESS] phase=model-preflight status=done" in text:
        return {
            "phase": "model-preflight",
            "phase_status": "done",
            "progress": 5,
            "message": "模型服务连接正常",
        }

    ocr_page = re.search(
        r"OCR_PAGE_METRICS.*?[\"']page(?:_number)?[\"']\s*[:=]\s*(\d+)"
        r"(?:.*?[\"'](?:total_pages|total)[\"']\s*[:=]\s*(\d+))?",
        text,
    )
    if ocr_page:
        state["track"] = "ocr"
        page = int(ocr_page.group(1))
        total_pages = int(ocr_page.group(2)) if ocr_page.group(2) else 0
        return {
            "phase": "ocr",
            "phase_status": "page",
            "progress": (
                _scale_progress(page, total_pages, 5, 24)
                if total_pages > 0 else None
            ),
            "message": (
                f"OCR page {page}/{total_pages}"
                if total_pages > 0 else f"OCR page {page}"
            ),
        }

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

    # Docling emits page paths/metrics while parsing. Treat those lines as
    # real activity so a large PDF with slow per-page work does not look idle.
    page_match = re.search(
        r"(?:page[- ]|Page\s+)(\d+)(?:\s*(?:/|of)\s*(\d+))?",
        text,
    )
    if page_match:
        state["track"] = "text"
        page = int(page_match.group(1))
        total_pages = int(page_match.group(2)) if page_match.group(2) else 0
        progress = (
            _scale_progress(page, total_pages, 6, 24)
            if total_pages > 0 else None
        )
        return {
            "phase": "parsing",
            "phase_status": "page",
            "progress": progress,
            "message": (
                f"page {page}/{total_pages}"
                if total_pages > 0 else f"page {page}"
            ),
        }

    # Worker stages may be namespaced (for example
    # ``multimodal-tasks/graph-building``).  Parse the complete token so
    # every explicit stage log still refreshes the idle watchdog heartbeat.
    generic_phase = re.search(
        r"\[PROGRESS\]\s+phase=([^\s]+)\s+status=([^\s]+)", text
    )
    if generic_phase:
        phase = generic_phase.group(1)
        status = generic_phase.group(2)
        phase_parts = [part for part in phase.split("/") if part]
        phase_key = phase_parts[-1] if phase_parts else phase
        state["track"] = (
            "multimodal" if "multimodal-tasks" in phase_parts
            else state.get("track", "text")
        )
        progress_by_phase = {
            "multimodal-tasks": 90,
            "graph-building": 97,
            "ocr": 10,
            "embedding": 80,
        }
        return {
            "phase": phase,
            "phase_status": status,
            "progress": progress_by_phase.get(phase, progress_by_phase.get(phase_key)),
            "message": f"{phase} {status}",
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


def _worker_watchdog_config() -> tuple[float, float]:
    """Return ``(idle_timeout, max_elapsed)`` for an upload Worker.

    ``PROCESS_TIMEOUT`` was historically a hard wall-clock timeout.  It is
    retained as the fallback for ``PROCESS_IDLE_TIMEOUT`` so existing
    deployments keep their configured safety limit while active page/chunk
    progress can refresh the watchdog.  ``PROCESS_MAX_TIMEOUT`` is optional
    and disabled by default; set it when a hard upper bound is desired.
    """

    def _read_seconds(name: str, default: float) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(0.0, value)

    legacy_timeout = _read_seconds("PROCESS_TIMEOUT", 3600.0)
    idle_timeout = _read_seconds("PROCESS_IDLE_TIMEOUT", legacy_timeout)
    max_elapsed = _read_seconds("PROCESS_MAX_TIMEOUT", 0.0)
    return idle_timeout, max_elapsed


async def _wait_for_worker_with_watchdog(
    proc,
    progress_event: asyncio.Event,
    progress_state: dict[str, Any],
    *,
    idle_timeout: float,
    max_elapsed: float = 0.0,
    started_at: float | None = None,
) -> None:
    """Wait for a Worker while allowing active progress to reset idle time.

    The helper deliberately owns and cancels its ``proc.wait()`` task when a
    watchdog fires.  The caller can then kill the subprocess and await it
    without leaving a pending task behind.  ``progress_state`` is updated by
    the stream readers and must contain ``last_progress_at`` when a progress
    event is emitted.
    """

    started = time.monotonic() if started_at is None else started_at
    last_progress_at = float(progress_state.get("last_progress_at") or started)
    wait_task = asyncio.create_task(proc.wait())
    try:
        while True:
            now = time.monotonic()
            idle_remaining = (
                idle_timeout - (now - last_progress_at)
                if idle_timeout > 0
                else float("inf")
            )
            max_remaining = (
                max_elapsed - (now - started)
                if max_elapsed > 0
                else float("inf")
            )
            remaining = min(idle_remaining, max_remaining)
            if remaining <= 0:
                timeout_kind = (
                    "max_elapsed"
                    if max_elapsed > 0 and max_remaining <= idle_remaining
                    else "idle"
                )
                progress_state["watchdog_timeout"] = timeout_kind
                raise asyncio.TimeoutError

            progress_wait = asyncio.create_task(progress_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {wait_task, progress_wait},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                if not progress_wait.done():
                    progress_wait.cancel()
                await asyncio.gather(progress_wait, return_exceptions=True)

            if wait_task in done:
                await wait_task
                return

            if progress_wait in done:
                progress_event.clear()
                observed = progress_state.get("last_progress_at")
                if observed is not None:
                    try:
                        last_progress_at = max(last_progress_at, float(observed))
                    except (TypeError, ValueError):
                        last_progress_at = time.monotonic()
                else:
                    last_progress_at = time.monotonic()
                continue

            # A progress event may race with asyncio.wait's timeout boundary.
            # Prefer the observed timestamp over killing an actively progressing
            # Worker.
            observed = progress_state.get("last_progress_at")
            try:
                observed_float = float(observed) if observed is not None else None
            except (TypeError, ValueError):
                observed_float = None
            if progress_event.is_set() or (
                observed_float is not None and observed_float > last_progress_at
            ):
                progress_event.clear()
                last_progress_at = max(
                    last_progress_at,
                    observed_float if observed_float is not None else time.monotonic(),
                )
                continue

            timeout_kind = (
                "max_elapsed"
                if max_elapsed > 0
                and (max_elapsed - (time.monotonic() - started))
                <= (idle_timeout - (time.monotonic() - last_progress_at))
                else "idle"
            )
            progress_state["watchdog_timeout"] = timeout_kind
            raise asyncio.TimeoutError
    except asyncio.TimeoutError:
        if not wait_task.done():
            wait_task.cancel()
            await asyncio.gather(wait_task, return_exceptions=True)
        raise
    except BaseException:
        if not wait_task.done():
            wait_task.cancel()
            await asyncio.gather(wait_task, return_exceptions=True)
        raise


def _select_worker_failure_detail(lines: list[str], returncode: int) -> str:
    """Keep the causal worker error instead of a later cleanup warning."""
    clean = [str(line).strip() for line in lines if str(line).strip()]
    priorities = (
        "[WORKER] ERROR: unhandled",
        "RetryableExternalServiceError",
        "外部 Embedding 服务",
        "外部 VLM 服务",
        "LightRAG pipeline failed",
        "Embedding func: Error",
        "VLM OCR 失败",
        "Failed to extract document",
        "MemoryError",
        "OpenBLAS",
    )
    for marker in priorities:
        matches = [line for line in clean if marker in line]
        if matches:
            return matches[-1][:600]

    errors = [
        line for line in clean
        if (
            "ERROR" in line
            or "未捕获异常:" in line
            or "处理失败:" in line
            or "Exception:" in line
        )
        and "Traceback" not in line
        and "Failed to finalize" not in line
        and "storage cleanup failed" not in line
    ]
    if errors:
        return errors[-1][:600]
    tail = clean[-12:]
    return ("; ".join(tail[-3:]) if tail else f"exit code {returncode}")[:600]


def _parse_worker_error(lines: list[str], returncode: int) -> dict[str, Any]:
    """Prefer the worker's structured primary error over cleanup noise."""
    for line in reversed(lines):
        marker = "WORKER_ERROR_JSON "
        if marker not in line:
            continue
        try:
            payload = json.loads(line.split(marker, 1)[1])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("message"):
            return payload
    unsigned = int(returncode) & 0xFFFFFFFF
    if unsigned == 0xC0000005:
        return {
            "stage": "native_crash",
            "root_type": "WindowsAccessViolation",
            "retryable": False,
            "message": "上传 Worker 原生崩溃（Windows 访问冲突 0xC0000005）",
            "secondary": [],
        }
    return {
        "stage": "worker",
        "root_type": "WorkerProcessError",
        "retryable": returncode == 4,
        "message": _select_worker_failure_detail(lines, returncode),
        "secondary": [],
    }


class WorkerProcessError(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        super().__init__(str(payload.get("message") or "Worker failed"))
        self.stage = str(payload.get("stage") or "worker")
        self.root_type = str(payload.get("root_type") or "WorkerProcessError")
        self.failure_code = str(payload.get("failure_code") or "")
        self.retryable = bool(payload.get("retryable"))
        self.secondary = list(payload.get("secondary") or [])
        self.page_coverage = payload.get("page_coverage")


def _retry_cleanup_lock(kb_name: str, filename: str) -> asyncio.Lock:
    key = (kb_name, os.path.basename(filename))
    lock = _retry_cleanup_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _retry_cleanup_locks[key] = lock
    return lock


def _worker_resource_snapshot(proc: Any) -> dict[str, Any]:
    """Best-effort RSS/CPU sample for timeout diagnostics."""
    try:
        import psutil

        process = psutil.Process(proc.pid)
        memory = process.memory_info()
        return {
            "pid": process.pid,
            "rss_bytes": int(memory.rss),
            "cpu_percent": float(process.cpu_percent(interval=None)),
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}

# ── Worker Process Tracking ─────────────────────────────────
# Maps kb_name -> list of (asyncio.subprocess.Process, task_id) for
# running worker subprocesses.  Used by KB deletion to kill workers.
_kb_worker_procs: dict[str, list] = {}
_active_upload_execution: dict[str, asyncio.Task] = {}
_upload_cancellation_tasks: dict[str, asyncio.Task] = {}
_UPLOAD_CANCELLATION_WORKER_WAIT_SECONDS = 10.0

_WORKER_NUMERIC_THREAD_ENV = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
_ocr_worker_slots: dict[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]] = {}


def _get_ocr_worker_slot() -> asyncio.Semaphore:
    """Return the process-wide OCR concurrency gate for the active event loop."""
    try:
        capacity = int(os.getenv("DOCUMENT_OCR_MAX_CONCURRENCY", "1"))
    except ValueError:
        capacity = 1
    capacity = max(1, min(capacity, 4))
    loop = asyncio.get_running_loop()
    current = _ocr_worker_slots.get(loop)
    if current is None or current[0] != capacity:
        semaphore = asyncio.Semaphore(capacity)
        _ocr_worker_slots[loop] = (capacity, semaphore)
        return semaphore
    return current[1]


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
_uploaded_files_has_terminal_metadata: bool | None = None


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


def _uploaded_files_supports_terminal_metadata() -> bool:
    """Return whether uploaded_files has the 019 outcome columns."""
    return _uploaded_files_has_terminal_metadata is not False


def _uploaded_files_mark_missing_terminal_metadata(exc: Exception) -> bool:
    """Remember a pre-019 schema when a query references its new columns."""
    global _uploaded_files_has_terminal_metadata
    if exc.__class__.__name__ != "UndefinedColumnError":
        return False
    if "outcome" not in str(exc) and "warning_message" not in str(exc):
        return False
    _uploaded_files_has_terminal_metadata = False
    kb_logger.warning(
        "uploaded_files terminal metadata columns are missing; using legacy compatibility"
    )
    return True


def _uploaded_files_projection(
    include_error_message: bool, include_terminal_metadata: bool = False,
) -> str:
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
    if include_terminal_metadata:
        columns.extend(["outcome", "warning_message"])
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
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))", f"kb-mutation:{kb_name}"
                )
                reindexing = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM vision_reindex_jobs WHERE kb=$1 "
                    "AND state IN ('queued','running'))",
                    kb_name,
                )
                if reindexing:
                    raise RuntimeError("reindex_in_progress")
                try:
                    row = await conn.fetchrow(
                        sql,
                        filename, file_path, file_hash, file_size, kb_name, uploaded_by, task_id, status,
                    )
                except Exception as exc:
                    if not include_error_message or not _uploaded_files_mark_missing_error_message(exc):
                        raise
                    row = await conn.fetchrow(
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
            ["queued", "processing", "completed", "failed", "deleted", "uploaded"],
        )
        changed = int(str(result).split()[-1]) > 0
        if changed:
            await bump_kb_corpus_revision(kb_name)
        return changed
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
    get = row.get if hasattr(row, "get") else lambda key, default="": row[key]
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
        "error_message": get("error_message", ""),
        "outcome": get("outcome", ""),
        "warning_message": get("warning_message", ""),
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
    outcome: str | None = None,
    warning_message: str | None = None,
    claim_owner: str | None = None,
    claim_generation: int | None = None,
) -> dict[str, Any] | None:
    """Update uploaded_files row by task_id and return the updated row."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        for _attempt in range(3):
            include_error_message = _uploaded_files_supports_error_message()
            include_terminal_metadata = _uploaded_files_supports_terminal_metadata()
            params: list[Any] = [status]
            assignments = ["status = $1"]
            if include_error_message:
                params.append(error_message)
                assignments.append(
                    f"error_message = COALESCE(${len(params)}, error_message)"
                )
            if include_terminal_metadata:
                params.append(outcome)
                assignments.append(f"outcome = COALESCE(${len(params)}, outcome)")
                params.append(warning_message)
                assignments.append(
                    f"warning_message = COALESCE(${len(params)}, warning_message)"
                )
            params.append(task_id)
            where = f"task_id = ${len(params)}"
            if kb_name:
                params.append(kb_name)
                where += f" AND kb_name = ${len(params)}"
            if expected_current_status is not None:
                params.append(expected_current_status)
                where += f" AND status = ${len(params)}"
            if claim_owner is not None or claim_generation is not None:
                if claim_owner is None or claim_generation is None:
                    raise ValueError("claim owner and generation must be provided together")
                params.append(claim_owner)
                where += f" AND processing_owner = ${len(params)}"
                params.append(int(claim_generation))
                where += f" AND processing_generation = ${len(params)}"
            sql = (
                "UPDATE uploaded_files "
                f"SET {', '.join(assignments)}, updated_at = NOW() "
                f"WHERE {where} "
                f"RETURNING {_uploaded_files_projection(include_error_message, include_terminal_metadata)}"
            )
            try:
                row = await pool.fetchrow(sql, *params)
                return _serialize_upload_row(row) if row else None
            except Exception as exc:
                if (
                    include_terminal_metadata
                    and _uploaded_files_mark_missing_terminal_metadata(exc)
                ):
                    continue
                if include_error_message and _uploaded_files_mark_missing_error_message(exc):
                    continue
                raise
        return None
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
            row = None
            for _attempt in range(3):
                include_error_message = _uploaded_files_supports_error_message()
                include_terminal_metadata = _uploaded_files_supports_terminal_metadata()
                try:
                    row = await conn.fetchrow(
                        f"""SELECT {_uploaded_files_projection(include_error_message, include_terminal_metadata)}
                            FROM uploaded_files
                            WHERE {where}
                            LIMIT 1""",
                        *params,
                    )
                    break
                except Exception as exc:
                    if (
                        include_terminal_metadata
                        and _uploaded_files_mark_missing_terminal_metadata(exc)
                    ):
                        continue
                    if include_error_message and _uploaded_files_mark_missing_error_message(exc):
                        continue
                    raise
        return _serialize_upload_row(row) if row else None
    except Exception:
        kb_logger.warning("PG uploaded_files lookup failed", exc_info=True)
        return None


async def pg_claim_upload_task(task_id: str, kb_name: str, owner: str) -> int | None:
    """Atomically claim a queued upload task for processing."""
    from raganything.services.pg_state_repo import get_pg_pool

    row = await get_pg_pool().fetchrow(
        "UPDATE uploaded_files SET status='processing',processing_owner=$3,"
        "processing_generation=processing_generation+1,processing_heartbeat_at=NOW(),"
        "error_message='',updated_at=NOW() WHERE task_id=$1 AND kb_name=$2 "
        "AND status='queued' RETURNING processing_generation",
        task_id,
        kb_name,
        owner,
    )
    return int(row["processing_generation"]) if row else None


async def pg_heartbeat_upload_claim(
    task_id: str, kb_name: str, owner: str, generation: int
) -> bool:
    from raganything.services.pg_state_repo import get_pg_pool

    result = await get_pg_pool().execute(
        "UPDATE uploaded_files SET processing_heartbeat_at=NOW(),updated_at=NOW() "
        "WHERE task_id=$1 AND kb_name=$2 AND processing_owner=$3 "
        "AND processing_generation=$4 AND status='processing'",
        task_id,
        kb_name,
        owner,
        generation,
    )
    return result == "UPDATE 1"


async def pg_begin_upload_cancellation(task_id: str, kb_name: str) -> dict[str, Any] | None:
    """Atomically fence a processing/retry upload before cancellation cleanup."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            upload = await conn.fetchrow(
                "SELECT * FROM uploaded_files WHERE task_id=$1 AND kb_name=$2 FOR UPDATE",
                task_id, kb_name,
            )
            if not upload:
                return None
            current = str(upload["status"] or "")
            if current == "cancelling":
                return {**dict(upload), "cancellation_started": False}
            if current not in {"processing", "retry_wait"}:
                return {**dict(upload), "cancellation_started": False}
            row = await conn.fetchrow(
                "UPDATE uploaded_files SET status='cancelling',processing_owner=NULL,"
                "processing_generation=processing_generation+1,processing_heartbeat_at=NULL,"
                "updated_at=NOW() WHERE id=$1 AND status=$2 RETURNING *",
                upload["id"], current,
            )
            if not row:
                return None
            await conn.execute(
                "UPDATE upload_retry_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,"
                "updated_at=NOW() WHERE upload_id=$1 AND status IN ('queued','retry_wait','running')",
                upload["id"],
            )
            await conn.execute(
                "UPDATE processing_tasks SET status='cancelling',retryable=FALSE,next_retry_at=NULL,"
                "message='Stopping and deleting upload',updated_at=NOW() WHERE task_id=$1",
                task_id,
            )
            from raganything.services.state_service import processing_tasks
            if task_id in processing_tasks:
                processing_tasks[task_id].update({
                    "status": "cancelling",
                    "retryable": False,
                    "next_retry_at": None,
                    "message": "Stopping and deleting upload",
                })
            return {**dict(row), "cancellation_started": True}


async def _upload_is_cancelling(task_id: str, kb_name: str) -> bool:
    upload = await pg_get_upload_by_task_id(task_id, kb_name=kb_name, is_admin=True)
    return bool(upload and upload.get("status") in {"cancelling", "deleted"})


async def _cleanup_cancelled_upload_document(upload: dict[str, Any], kb_name: str) -> None:
    """Remove only document records durably attributed to a cancelled upload."""
    task_id = str(upload.get("task_id") or "")
    file_hash = str(upload.get("file_hash") or "")
    if not task_id:
        return
    statuses = await _load_doc_status_json(kb_name) or {}
    doc_ids: list[str] = []
    for doc_id, info in statuses.items():
        if not isinstance(info, dict):
            continue
        metadata = info.get("metadata") if isinstance(info.get("metadata"), dict) else {}
        markers = {str(value) for value in (info.get("track_id"), metadata.get("task_id")) if value}
        stored_hash = str(metadata.get("file_hash") or "")
        if task_id in markers or (file_hash and stored_hash == file_hash):
            doc_ids.append(str(doc_id))
    if not doc_ids:
        return
    instance = kb_instances.get(kb_name) or await get_kb(kb_name)
    lightrag = getattr(instance, "lightrag", None)
    if lightrag is None:
        raise RuntimeError("cancellation_cleanup_kb_unavailable")
    for doc_id in doc_ids:
        result = await lightrag.adelete_by_doc_id(doc_id, delete_llm_cache=True)
        if getattr(result, "status", "success") not in {"success", "not_found"}:
            raise RuntimeError(f"cancellation_cleanup_failed:{doc_id}")
    vision_repo = getattr(lightrag, "image_vision_repo", None)
    if vision_repo is not None:
        for doc_id in doc_ids:
            await vision_repo.delete_by_doc_id(doc_id)
        if hasattr(vision_repo, "index_done_callback"):
            await vision_repo.index_done_callback()
    from raganything.services.document_repair import cancel_repair_jobs
    from raganything.services.document_tagging import cancel_document_tagging
    from raganything.services.kb_tag_repo import delete_document_tags
    await cancel_repair_jobs(kb_name, doc_ids)
    await cancel_document_tagging(kb_name, doc_ids)
    for doc_id in doc_ids:
        await delete_document_tags(kb_name, doc_id)
    if getattr(instance, "multimodal_status_cache", None) is not None:
        await instance.multimodal_status_cache.delete(doc_ids)
        await instance.multimodal_status_cache.index_done_callback()
    from raganything.query_cache import get_query_cache
    get_query_cache().invalidate()


async def _stop_cancelled_upload_worker(proc: Any, task_id: str) -> bool:
    """Stop one worker with bounded waits before task-owned cleanup begins."""
    try:
        proc.terminate()
    except (AttributeError, ProcessLookupError):
        try:
            proc.kill()
        except (AttributeError, ProcessLookupError):
            return getattr(proc, "returncode", None) is not None

    try:
        await asyncio.wait_for(
            proc.wait(), timeout=_UPLOAD_CANCELLATION_WORKER_WAIT_SECONDS
        )
        return True
    except asyncio.TimeoutError:
        kb_logger.warning(
            "[UPLOAD-CANCEL] worker did not exit after terminate: task=%s", task_id
        )

    try:
        proc.kill()
    except (AttributeError, ProcessLookupError):
        return getattr(proc, "returncode", None) is not None

    try:
        await asyncio.wait_for(
            proc.wait(), timeout=_UPLOAD_CANCELLATION_WORKER_WAIT_SECONDS
        )
        return True
    except asyncio.TimeoutError:
        kb_logger.warning(
            "[UPLOAD-CANCEL] worker remains alive after kill: task=%s", task_id
        )
        return False


async def _finish_upload_cancellation(upload: dict[str, Any], kb_name: str) -> None:
    """Wait for the exact upload execution, then make its deletion durable."""
    task_id = str(upload["task_id"])
    try:
        for proc, running_task_id in list(_kb_worker_procs.get(kb_name, [])):
            if str(running_task_id) != task_id or getattr(proc, "returncode", None) is not None:
                continue
            if not await _stop_cancelled_upload_worker(proc, task_id):
                # Keep durable cancellation and dedup ownership until a later
                # polling request or recovery pass can complete cleanup.
                return
        execution = _active_upload_execution.get(task_id)
        if execution is not None and execution is not asyncio.current_task():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        await _cleanup_cancelled_upload_document(upload, kb_name)
        staged_file = Path(str(upload.get("file_path") or ""))
        if staged_file.exists() and staged_file.is_file():
            staged_file.unlink()
        from raganything.services.state_service import delete_task, processing_tasks
        processing_tasks.pop(task_id, None)
        await delete_task(task_id)
        from raganything.services.user_settings import delete_task_settings_snapshot
        await delete_task_settings_snapshot(task_id)
        _unregister_processing_file(kb_name, str(upload.get("file_hash") or ""))
        deleted = await pg_update_upload_status_by_task_id(
            task_id, "deleted", kb_name=kb_name, expected_current_status="cancelling", error_message="",
        )
        if deleted is not None:
            await bump_kb_corpus_revision(kb_name)
            from raganything.services.ws_service import add_event
            await add_event("upload_cancelled", task_id=task_id, file=upload.get("filename", ""), kb=kb_name)
    except Exception:
        kb_logger.warning("[UPLOAD-CANCEL] cleanup remains pending: task=%s", task_id, exc_info=True)
    finally:
        _upload_cancellation_tasks.pop(task_id, None)


async def cancel_inflight_upload(task_id: str, kb_name: str) -> dict[str, Any] | None:
    """Start idempotent cancellation for a processing or retry-wait upload."""
    upload = await pg_begin_upload_cancellation(task_id, kb_name)
    if upload is None:
        return None
    if upload.get("status") != "cancelling":
        return upload
    if task_id not in _upload_cancellation_tasks:
        _upload_cancellation_tasks[task_id] = asyncio.create_task(
            _finish_upload_cancellation(upload, kb_name), name=f"upload-cancel:{task_id}"
        )
    return upload


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
            rows = []
            for _attempt in range(3):
                include_error_message = _uploaded_files_supports_error_message()
                include_terminal_metadata = _uploaded_files_supports_terminal_metadata()
                try:
                    rows = await conn.fetch(
                        (
                            f"SELECT {_uploaded_files_projection(include_error_message, include_terminal_metadata)} "
                            f"FROM uploaded_files {where} "
                            f"ORDER BY created_at DESC "
                            f"LIMIT ${idx} OFFSET ${idx + 1}"
                        ),
                        *params,
                    )
                    break
                except Exception as exc:
                    if (
                        include_terminal_metadata
                        and _uploaded_files_mark_missing_terminal_metadata(exc)
                    ):
                        continue
                    if include_error_message and _uploaded_files_mark_missing_error_message(exc):
                        continue
                    raise
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
            "SELECT name AS kb_name, corpus_revision FROM kb_metadata "
            "WHERE name = ANY($1::text[])",
            names,
        )
    except Exception:
        kb_logger.warning("PG uploaded_files content-update lookup failed", exc_info=True)
        return {}

    updates: dict[str, str] = {}
    for row in rows:
        updates[str(row["kb_name"])] = str(int(row["corpus_revision"] or 0))
    return updates


async def bump_kb_corpus_revision(kb_name: str) -> int:
    """Advance the durable cache identity after any visible corpus mutation."""
    from raganything.services.pg_state_repo import get_pg_pool

    row = await get_pg_pool().fetchrow(
        "UPDATE kb_metadata SET corpus_revision=corpus_revision+1,updated_at=NOW() "
        "WHERE name=$1 RETURNING corpus_revision",
        kb_name,
    )
    if row is None:
        raise RuntimeError("knowledge base metadata is unavailable")
    return int(row["corpus_revision"])


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
    """Load KB metadata from the authoritative PostgreSQL store.

    Returns:
        Dict keyed by KB name: {name: {name, created, domain, ...}, ...}
        Empty dict if no KBs exist (caller should create default if needed).
    """
    try:
        from raganything.services.pg_kb_meta_repo import pg_load_kb_meta
        return await pg_load_kb_meta()
    except Exception:
        kb_logger.exception("PG kb_meta load failed")
        raise


async def save_kb_meta(meta: dict[str, Any]) -> None:
    """Persist KB metadata — PG + JSON mirror.

    Args:
        meta: Full KB metadata dict: {name: {name, created, ...}, ...}
    """
    # ── PG ──────────────────────────────────────────────
    from raganything.services.pg_kb_meta_repo import pg_save_all_kb_meta
    await pg_save_all_kb_meta(meta)

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


def _serialize_doc_status_record(record: Any) -> dict[str, Any]:
    """Normalize a full doc-status record without trusting paginated summaries."""
    if isinstance(record, dict):
        if "chunks_list" not in record:
            raise RuntimeError("full doc_status record is missing chunks_list")
        get_value = record.get
    else:
        if not hasattr(record, "chunks_list"):
            raise RuntimeError("full doc_status record is missing chunks_list")

        def get_value(key: str, default: Any = None) -> Any:
            return getattr(record, key, default)

    status = get_value("status")
    if hasattr(status, "value"):
        status = status.value
    chunks_list = get_value("chunks_list")
    if chunks_list is None:
        chunks_list = []
    if not isinstance(chunks_list, list):
        raise RuntimeError("full doc_status chunks_list is not a list")
    chunks_count = get_value("chunks_count")
    if chunks_count is not None:
        try:
            expected_count = int(chunks_count)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("full doc_status chunks_count is invalid") from exc
        if expected_count != len(chunks_list):
            raise RuntimeError(
                "full doc_status chunk declaration is inconsistent: "
                f"chunks_count={expected_count}, chunks_list={len(chunks_list)}"
            )
    if len(set(chunks_list)) != len(chunks_list):
        raise RuntimeError("full doc_status chunks_list contains duplicate IDs")

    return {
        "file_path": get_value("file_path", ""),
        "status": status,
        "content_summary": get_value("content_summary", ""),
        "content_length": get_value("content_length", 0),
        "chunks_count": chunks_count,
        "chunks_list": list(chunks_list),
        "metadata": get_value("metadata") or {},
        "error_msg": get_value("error_msg"),
        "created_at": get_value("created_at"),
        "updated_at": get_value("updated_at"),
        "track_id": get_value("track_id"),
    }


async def _get_pg_doc_status_storage(kb_name: str) -> Any | None:
    """Return a live PG doc-status store, or ``None`` for a JSON-backed KB."""
    if not _pg_storage_ready():
        return None

    rag = kb_instances.get(kb_name)
    if rag is None:
        try:
            rag = await get_kb(kb_name)
        except Exception as exc:
            raise RuntimeError(
                f"PG doc_status initialization failed for KB {kb_name}"
            ) from exc
    if rag is None or not rag.lightrag or not hasattr(rag.lightrag, "doc_status"):
        raise RuntimeError(f"PG doc_status storage is unavailable for KB {kb_name}")

    ds = rag.lightrag.doc_status
    # JSONDocStatusStorage deliberately has no ``db`` attribute.
    if not hasattr(ds, "db"):
        return None
    if getattr(ds, "db", None) is not None:
        return ds

    # finalize_storages() can leave a released PG store in the instance cache.
    if kb_instances.get(kb_name) is rag:
        del kb_instances[kb_name]
    try:
        rag = await get_kb(kb_name)
        ds = rag.lightrag.doc_status
    except Exception as exc:
        raise RuntimeError(
            f"PG doc_status cache recovery failed for KB {kb_name}"
        ) from exc
    if not hasattr(ds, "db") or getattr(ds, "db", None) is None:
        raise RuntimeError(f"PG doc_status storage is unavailable for KB {kb_name}")
    return ds


async def _load_doc_status_by_id(
    kb_name: str, doc_id: str,
) -> dict[str, Any] | None:
    """Load one full doc-status record, including its authoritative chunk IDs."""
    import json as _json

    ds = await _get_pg_doc_status_storage(kb_name)
    if ds is not None:
        try:
            record = await ds.get_by_id(doc_id)
        except Exception:
            kb_logger.warning(
                "PG doc_status single-record load failed for KB %s doc %s",
                kb_name, doc_id, exc_info=True,
            )
            raise
        return _serialize_doc_status_record(record) if record is not None else None

    json_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
    if not json_path.exists():
        return None
    try:
        data = _json.loads(json_path.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError):
        kb_logger.warning(
            "JSON doc_status load failed for KB %s", kb_name, exc_info=True,
        )
        return None
    record = data.get(doc_id) if isinstance(data, dict) else None
    return _serialize_doc_status_record(record) if isinstance(record, dict) else None


def _serialize_doc_status_summary(record: Any) -> dict[str, Any]:
    """Normalize fields exposed by LightRAG's summary-only pagination API."""
    if isinstance(record, Mapping):
        get_value = record.get
    elif hasattr(record, "keys") and hasattr(record, "__getitem__"):
        # asyncpg.Record is mapping-like but is not a dict.  Do not use
        # getattr here: that silently drops every database column and turns a
        # valid document into an empty list-view row.
        def get_value(key: str, default: Any = None) -> Any:
            try:
                return record[key]
            except (KeyError, IndexError):
                return default
    else:
        def get_value(key: str, default: Any = None) -> Any:
            return getattr(record, key, default)
    status = get_value("status")
    if hasattr(status, "value"):
        status = status.value
    return {
        "file_path": get_value("file_path", ""),
        "status": status,
        "content_summary": get_value("content_summary", ""),
        "content_length": get_value("content_length", 0),
        "chunks_count": get_value("chunks_count", 0),
        "metadata": get_value("metadata") or {},
        "error_msg": get_value("error_msg"),
        "created_at": get_value("created_at"),
        "updated_at": get_value("updated_at"),
        "track_id": get_value("track_id"),
    }


async def _load_pg_doc_status_summaries_read_only(kb_name: str) -> dict[str, Any]:
    """Read list-view doc-status fields directly from PostgreSQL.

    This is deliberately limited to summary fields.  It lets read-only document
    views remain available when constructing a RAG instance is impossible (for
    example, because the configured default parser is not installed), without
    weakening the authoritative LightRAG path used for full records or writes.
    """
    if not _pg_storage_ready():
        raise RuntimeError("PG doc_status summary storage is unavailable")

    from raganything.services.pg_state_repo import get_pg_pool

    workspace = kb_dir(kb_name)
    pool = get_pg_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, file_path, status, content_summary, content_length,
                          chunks_count, metadata, error_msg, created_at, updated_at,
                          track_id
                     FROM LIGHTRAG_DOC_STATUS
                    WHERE workspace=$1
                    ORDER BY updated_at DESC NULLS LAST, id""",
                workspace,
            )
    except Exception as exc:
        raise RuntimeError("PG doc_status summary read failed") from exc

    return {
        str(row["id"]): _serialize_doc_status_summary(row)
        for row in rows
    }


async def _load_doc_status_summaries(kb_name: str) -> dict[str, Any]:
    """Load lightweight status rows for list views without transferring chunk IDs."""
    try:
        ds = await _get_pg_doc_status_storage(kb_name)
    except RuntimeError:
        # Do not fall back to legacy JSON after a PG-backed KB has been
        # selected.  A parser-installation failure can prevent a query-only
        # RAG instance from initializing, though, so the list view may use a
        # bounded direct PG summary read instead.
        kb_logger.warning(
            "PG doc_status instance unavailable; using read-only summary fallback for KB %s",
            kb_name,
        )
        return await _load_pg_doc_status_summaries_read_only(kb_name)
    if ds is None:
        return await _load_doc_status_json(kb_name)

    result: dict[str, Any] = {}
    page = 1
    while True:
        docs, total = await ds.get_docs_paginated(
            status_filter=None, page=page, page_size=200,
        )
        for doc_id, summary in docs:
            result[str(doc_id)] = _serialize_doc_status_summary(summary)
        if not docs or len(result) >= total:
            return result
        page += 1


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
    ds = await _get_pg_doc_status_storage(kb_name)
    if ds is not None:
        try:
            result: dict[str, Any] = {}
            page = 1
            while True:
                # Pagination is a summary-only API in PG: it deliberately
                # returns chunks_list=[] even for processed documents. Use it
                # only to discover IDs, then hydrate authoritative records.
                docs, total = await ds.get_docs_paginated(
                    status_filter=None, page=page, page_size=200,
                )
                if not docs:
                    if len(result) < total:
                        raise RuntimeError(
                            "PG doc_status pagination ended before all full records "
                            f"were loaded for KB {kb_name}: loaded={len(result)}, total={total}"
                        )
                    return result

                doc_ids = [str(doc_id) for doc_id, _summary in docs]
                full_records = await ds.get_by_ids(doc_ids)
                if len(full_records) != len(doc_ids):
                    raise RuntimeError(
                        "PG doc_status full-record hydration returned an unexpected "
                        f"count for KB {kb_name}: expected={len(doc_ids)}, "
                        f"actual={len(full_records)}"
                    )
                missing_ids = [
                    doc_id for doc_id, record in zip(doc_ids, full_records)
                    if record is None
                ]
                if missing_ids:
                    raise RuntimeError(
                        "PG doc_status full records are temporarily unavailable for "
                        f"KB {kb_name}: {', '.join(missing_ids[:5])}"
                    )
                for doc_id, record in zip(doc_ids, full_records):
                    result[doc_id] = _serialize_doc_status_record(record)

                if len(result) >= total:
                    return result
                page += 1
        except Exception:
            kb_logger.warning(
                "PG doc_status load failed for KB %s",
                kb_name, exc_info=True,
            )
            raise

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


def _upload_filename_key(value: str) -> str:
    name = os.path.basename(str(value or ""))
    return re.sub(r"^[0-9a-fA-F]{8}_", "", name)


async def _load_fresh_pg_doc_status_records(kb_name: str) -> dict[str, dict[str, Any]]:
    """Read authoritative document records without relying on a cached KB instance."""
    if not _pg_storage_ready():
        return {}
    from raganything.services.pg_state_repo import get_pg_pool

    rows = await get_pg_pool().fetch(
        "SELECT id,file_path,status,content_summary,content_length,chunks_count,"
        "chunks_list,metadata,error_msg,created_at,updated_at,track_id "
        "FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1",
        kb_dir(kb_name),
    )
    return {
        str(row["id"]): {
            "file_path": row["file_path"] or "",
            "status": getattr(row["status"], "value", row["status"]),
            "content_summary": row["content_summary"] or "",
            "content_length": row["content_length"] or 0,
            "chunks_count": row["chunks_count"] or 0,
            "chunks_list": list(row["chunks_list"] or []),
            "metadata": row["metadata"] or {},
            "error_msg": row["error_msg"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "track_id": row["track_id"],
        }
        for row in rows
    }


def _matching_uploaded_document_statuses(
    statuses: dict[str, Any], filename: str, task_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    filename_key = _upload_filename_key(filename)
    matches: list[tuple[str, dict[str, Any]]] = []
    for doc_id, status in (statuses or {}).items():
        if not isinstance(status, dict):
            continue
        if _upload_filename_key(str(status.get("file_path") or "")) != filename_key:
            continue
        metadata = status.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        markers = {
            str(value) for value in (
                status.get("task_id"),
                metadata.get("task_id"),
            ) if value
        }
        if not markers or task_id in markers:
            matches.append((str(doc_id), status))
    return matches


async def persist_document_processing_snapshot(
    kb_name: str,
    filename: str,
    task_id: str,
    snapshot: dict[str, Any],
) -> str:
    """Attach the immutable, secret-free enqueue snapshot to document metadata."""
    statuses = await _load_doc_status_json(kb_name)
    matches = _matching_uploaded_document_statuses(statuses, filename, task_id)
    if not matches:
        # The isolated worker can finish and commit before this process's
        # cached LightRAG status store observes its write. Query the durable
        # workspace directly before declaring a completed document missing.
        fresh_statuses = await _load_fresh_pg_doc_status_records(kb_name)
        matches = _matching_uploaded_document_statuses(
            fresh_statuses, filename, task_id
        )
    if not matches:
        raise RuntimeError("processed_document_status_missing")
    matches.sort(key=lambda item: str(item[1].get("updated_at") or ""), reverse=True)
    doc_id, status = matches[0]
    metadata = status.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    settings = snapshot.get("settings")
    profile_ids = snapshot.get("profile_ids")
    if not isinstance(settings, dict) or not isinstance(profile_ids, dict):
        raise RuntimeError("settings_snapshot_invalid")
    metadata["processing_settings_snapshot"] = {
        "revision": int(snapshot.get("revision") or 0),
        "fingerprint": str(snapshot.get("fingerprint") or ""),
        "profile_ids": json.loads(json.dumps(profile_ids)),
        "settings": json.loads(json.dumps(settings)),
    }
    updated = {**status, "metadata": metadata}
    store = await _get_pg_doc_status_storage(kb_name)
    if store is None:
        rag = kb_instances.get(kb_name) or await get_kb(kb_name)
        store = getattr(getattr(rag, "lightrag", None), "doc_status", None)
    if store is None:
        raise RuntimeError("document_status_storage_unavailable")
    await store.upsert({doc_id: updated})
    callback = getattr(store, "index_done_callback", None)
    if callback is not None:
        await callback()
    return doc_id


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

async def get_kb(
    name: str = None,
    *,
    task_settings: dict[str, Any] | None = None,
) -> RAGAnything:
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
    if task_settings is not None:
        # A task-bound configuration must not mutate or reuse the shared KB
        # instance.  It is intentionally uncached and is finalized by the
        # caller once the task has completed.
        from lightrag.kg.shared_storage import set_default_workspace

        target = kb_dir(name)
        set_default_workspace(target)
        metadata = (await load_kb_meta()).get(name, {})
        vision_state = (metadata.get("extra") or {}).get("vision_embedding") or {}
        profile_scope = None
        if vision_state.get("profile_id") and vision_state.get("profile_fingerprint"):
            profile_scope = (vision_state["profile_id"], vision_state["profile_fingerprint"])
        instance = await create_rag(
            working_dir=target,
            vision_embedding_profile=profile_scope,
            task_settings=task_settings,
        )
        await instance._ensure_lightrag_initialized()
        return instance
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
            metadata = (await load_kb_meta()).get(name, {})
            vision_state = (metadata.get("extra") or {}).get("vision_embedding") or {}
            profile_scope = None
            if vision_state.get("profile_id") and vision_state.get("profile_fingerprint"):
                profile_scope = (
                    vision_state["profile_id"],
                    vision_state["profile_fingerprint"],
                )
            instance = await create_rag(
                working_dir=target,
                vision_embedding_profile=profile_scope,
            )
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

    # A compensation task must not recreate storage or write tags after the
    # knowledge base has entered deletion.
    await _cancel_deferred_auto_tag_tasks(name)

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
    vision_embedding_profile: tuple[str, str] | None = None,
    task_settings: dict[str, Any] | None = None,
) -> RAGAnything:
    """Create a RAGAnything instance with configured LLM/embedding functions.

    Args:
        parser: Parser name (default from env PARSER or "mineru")
        working_dir: Working directory for LightRAG storage
        chunking_strategy: Chunking strategy name

    Returns:
        Configured RAGAnything instance
    """
    task_ingestion = (task_settings or {}).get("ingestion", {})
    if not isinstance(task_ingestion, dict):
        raise ValueError("task ingestion settings must be an object")
    if parser is None:
        parser = task_ingestion.get("parser")
    if parser is None:
        parser = os.getenv("PARSER", "docling")
    if chunking_strategy is None:
        chunking_strategy = task_ingestion.get("chunking_strategy")
    if chunking_strategy is None:
        chunking_strategy = os.getenv("CHUNKING_STRATEGY", "recursive")
    wd = working_dir or WORKING_DIR
    raw_query_scope = (task_settings or {}).get("_query_scope", {})
    if raw_query_scope and not isinstance(raw_query_scope, dict):
        raise ValueError("query cache scope must be an object")
    query_cache_scope = {
        "workspace": str((raw_query_scope or {}).get("workspace") or wd),
        "permission_scope": str(
            (raw_query_scope or {}).get("permission_scope") or "background"
        ),
        "corpus_revision": str(
            (raw_query_scope or {}).get("corpus_revision") or "unknown"
        ),
        "settings_fingerprint": str(
            (raw_query_scope or {}).get("settings_fingerprint")
            or (task_settings or {}).get("fingerprint")
            or "legacy"
        ),
        "llm_profile_fingerprint": str(
            (raw_query_scope or {}).get("llm_profile_fingerprint") or "legacy"
        ),
    }
    cache_scope = json.dumps(
        query_cache_scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )

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
        kw.setdefault("timeout", int(os.getenv("LLM_TIMEOUT", "180")))
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

    async def _preflight_embed_func(texts, *, timeout: int):
        raw_call = getattr(openai_embed.func, "__wrapped__", openai_embed.func)
        return await raw_call(
            texts,
            model=_emb_model,
            api_key=_api_key,
            base_url=_base_url,
            client_configs={"timeout": timeout, "max_retries": 0},
        )

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
    requested_chunk_size = task_ingestion.get("chunk_size")
    chunk_token_size = (
        max(64, min(int(requested_chunk_size), 4096))
        if isinstance(requested_chunk_size, int)
        else _env_int("CHUNK_SIZE", 800, max_val=4096)
    )
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
        enable_image_processing=task_ingestion.get("enable_image", os.getenv("ENABLE_IMAGE_PROCESSING", "true").lower() == "true"),
        enable_table_processing=task_ingestion.get("enable_table", os.getenv("ENABLE_TABLE_PROCESSING", "true").lower() == "true"),
        enable_equation_processing=task_ingestion.get("enable_equation", os.getenv("ENABLE_EQUATION_PROCESSING", "true").lower() == "true"),
        enable_video_processing=task_ingestion.get("enable_video", os.getenv("ENABLE_VIDEO_PROCESSING", "false").lower() == "true"),
        entity_types=task_ingestion.get("entity_types", os.getenv("ENTITY_TYPES", "")),
        entity_extraction_min_degree=task_ingestion.get("minimum_relation_degree", int(os.getenv("ENTITY_EXTRACTION_MIN_DEGREE", "0"))),
    )

    # ── Vision embedding (doubao-embedding-vision) ──────────
    # Feature-gated: returns None when VISION_SEARCH_ENABLED is False
    # or VISION_EMBEDDING_MODEL is not set.
    if vision_embedding_profile is not None:
        from raganything.services.vision_models import build_embedding_provider, require_available

        profile_id, profile_fingerprint = vision_embedding_profile
        entry = require_available(profile_id, "embedding")
        if entry.fingerprint != profile_fingerprint:
            raise RuntimeError("vision embedding profile fingerprint is no longer available")
        vision_embed_func = build_embedding_provider(profile_id, working_dir=wd)
    elif os.getenv("VISION_SEARCH_ENABLED", "false").lower() == "true":
        vision_embed_func = create_vision_embed_func(working_dir=wd)
    else:
        vision_embed_func = None

    task_models = (task_settings or {}).get("models", {})
    task_runtime = (task_settings or {}).get("runtime", {})
    if task_models:
        if not isinstance(task_models, dict):
            raise ValueError("task model settings must be an object")
        from raganything.services.vision_models import (
            build_llm_callable,
            build_vlm_callable,
            get_entry,
            require_available,
        )

        llm_profile_id = task_models.get("llm_profile_id")
        vlm_profile_id = task_models.get("vlm_profile_id")
        if not isinstance(llm_profile_id, str) or not llm_profile_id:
            raise RuntimeError("settings snapshot is missing an LLM profile")
        if not isinstance(vlm_profile_id, str) or not vlm_profile_id:
            raise RuntimeError("settings snapshot is missing a VLM profile")
        profile_fingerprints = (task_settings or {}).get("profile_fingerprints") or {}
        if not isinstance(profile_fingerprints, dict):
            raise RuntimeError("settings snapshot profile fingerprints are invalid")
        require_vlm = (task_settings or {}).get("_require_vlm", True) is not False
        for profile_id, kind in ((llm_profile_id, "llm"), (vlm_profile_id, "vlm")):
            expected = profile_fingerprints.get(kind)
            if not isinstance(expected, str) or not expected:
                raise RuntimeError("settings snapshot is missing a model profile fingerprint")
            entry = (
                require_available(profile_id, kind)
                if kind == "llm" or require_vlm
                else get_entry(profile_id, kind)
            )
            if entry.fingerprint != expected:
                raise RuntimeError("profile_changed")
        # Credentials remain server-only; the durable snapshot freezes only
        # the public profile identity and non-secret configuration hash.
        llm_func = build_llm_callable(
            llm_profile_id,
            cache_scope=cache_scope,
            timeout=task_runtime.get("llm_timeout") if isinstance(task_runtime, dict) else None,
        )
        # Text-only queries do not invoke the vision function and therefore do
        # not construct a VLM adapter. Image-query and ingestion boundaries
        # retain strict VLM availability and adapter checks.
        vision_func = (
            build_vlm_callable(vlm_profile_id) if require_vlm else llm_func
        )

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

    rag = RAGAnything(config=config, llm_model_func=llm_func,
                      vision_model_func=vision_func, embedding_func=embedding_func,
                      vision_embed_func=vision_embed_func,
                      vision_profile_id=vision_embedding_profile[0] if vision_embedding_profile else "legacy-doubao-embedding",
                      vision_profile_fingerprint=vision_embedding_profile[1] if vision_embedding_profile else "legacy-unscoped",
                      query_cache_scope=query_cache_scope,
                      lightrag_kwargs=lightrag_kwargs)
    # The worker preflight bypasses the local embedding cache intentionally.
    rag._raw_embedding_provider = _raw_embed_func
    rag._raw_embedding_preflight_provider = _preflight_embed_func
    rag._raw_llm_preflight_provider = llm_func
    return rag


# ── Recovery Lock (PG advisory + file fallback) ──────────────
# Multi-worker recovery lock. PG advisory lock auto-releases on connection
# close — no cleanup needed after worker crash.


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
        "content_ready": False,
        "multimodal_processed": False,
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
    file_hash: str = "",
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
        search_base = os.path.basename(filename)
        active_candidates: list[str] = []
        active_unscoped: list[str] = []
        for candidate_id, candidate in data.items():
            if not isinstance(candidate, dict):
                continue
            stored_base = os.path.basename(str(candidate.get("file_path") or ""))
            same_document = (
                stored_base == search_base
                or (
                    stored_base.endswith("_" + search_base)
                    and len(stored_base) - len(search_base) == 9
                )
            )
            if not same_document or str(candidate.get("status") or "").lower() not in {
                "handling", "processing",
            }:
                continue
            active_candidates.append(str(candidate_id))
            candidate_metadata = candidate.get("metadata")
            candidate_metadata = (
                candidate_metadata if isinstance(candidate_metadata, dict) else {}
            )
            if not (
                candidate.get("track_id")
                or candidate_metadata.get("task_id")
                or candidate_metadata.get("file_hash")
            ):
                active_unscoped.append(str(candidate_id))
        # An unscoped active row can only be claimed when it is the sole active
        # row for this filename. If a scoped row exists alongside it, the
        # filename alone cannot establish ownership, so fail closed.
        if active_unscoped and len(active_candidates) > 1:
            kb_logger.error(
                "[FIX-STUCK] 同名活动文档归属不明确，跳过批量失败标记: KB=%s file=%s docs=%s",
                kb_name,
                filename,
                active_unscoped,
            )
            return
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
            normalized_status = str(info.get("status") or "").lower()
            if same_document and normalized_status in {
                "handling", "processing", "failed",
            }:
                metadata = info.get("metadata") or {}
                metadata = dict(metadata) if isinstance(metadata, dict) else {}
                existing_markers = {
                    str(value)
                    for value in (info.get("track_id"), metadata.get("task_id"))
                    if value
                }
                if existing_markers and task_id not in existing_markers:
                    continue
                existing_hash = str(metadata.get("file_hash") or "")
                if existing_hash and file_hash and existing_hash != file_hash:
                    continue
                # A terminal failed row without task/hash provenance belongs
                # to an older or unknown upload. Never stamp it with the
                # current retry markers based on filename alone.
                if normalized_status == "failed" and not (
                    existing_markers or existing_hash
                ):
                    continue
                if normalized_status == "failed" and not (
                    metadata.get("cleanup_pending") is True
                    and metadata.get("residual_data") is True
                ):
                    # Preserve ordinary parser failures; this hook only owns
                    # incomplete worker states that require cleanup.
                    continue
                info["status"] = "failed"
                info["error_msg"] = "处理中断：子进程异常退出或超时"
                metadata.update({
                    "content_ready": False,
                    "multimodal_processed": False,
                    "failure_stage": "worker_timeout",
                    "cleanup_pending": True,
                    "residual_data": True,
                    "last_error": str(error_message or "处理中断：子进程异常退出或超时")[:4000],
                    "task_id": task_id,
                    "file_hash": file_hash,
                })
                multimodal_chunks = metadata.get("multimodal_chunks")
                if isinstance(multimodal_chunks, dict):
                    residual_ids = [str(value) for value in multimodal_chunks if value]
                    if residual_ids:
                        metadata.update({
                            "residual_multimodal_chunk_ids": residual_ids,
                            "cleanup_pending": True,
                            "residual_data": True,
                        })
                info["metadata"] = metadata
                if chunking_strategy:
                    metadata["chunking_strategy"] = chunking_strategy
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


def _is_retryable_graph_failure(error: str) -> bool:
    from raganything.services.document_repair import _is_retryable_error

    return _is_retryable_error(RuntimeError(str(error or "")))


async def _load_persisted_chunk_ids_for_document(
    kb_name: str,
    doc_id: str,
) -> set[str] | None:
    """Load the durable chunk IDs for one document when an authoritative store is available.

    ``doc_status.chunks_list`` is only a declaration.  A worker can persist
    multimodal chunks before it reaches the Stage 7 status update, leaving
    extra rows that must keep a failed document out of the degraded/tagging
    path.  Return ``None`` when the local backend cannot identify document
    ownership, so legacy JSON fixtures without ``full_doc_id`` remain
    compatible while PostgreSQL gets a strict set comparison.
    """
    workspace = "./rag_storage" if kb_name == "default" else f"./rag_storage_{kb_name}"

    if _pg_storage_ready():
        try:
            from raganything.services.pg_state_repo import get_pg_pool

            rows = await get_pg_pool().fetch(
                "SELECT id FROM LIGHTRAG_DOC_CHUNKS "
                "WHERE workspace=$1 AND full_doc_id=$2",
                workspace,
                doc_id,
            )
            return {str(row["id"]) for row in rows if row.get("id")}
        except Exception:
            kb_logger.warning(
                "Failed to load persisted chunk IDs for degraded document "
                "KB=%s doc=%s",
                kb_name,
                doc_id,
                exc_info=True,
            )
            # Do not turn a transient PG read failure into an unsafe degraded
            # transition.  The caller treats ``None`` as unverifiable.
            return None

    # JSON-backed stores may expose ownership on each chunk record.  Avoid
    # comparing every chunk in a KB when that field is absent because the
    # fallback loader intentionally aggregates records across documents.
    try:
        text_chunks = await _load_text_chunks_json(kb_name)
    except Exception:
        return None
    if not isinstance(text_chunks, dict):
        return None
    owned_records = {
        str(chunk_id)
        for chunk_id, chunk in text_chunks.items()
        if isinstance(chunk, dict) and str(chunk.get("full_doc_id") or "") == doc_id
    }
    has_ownership_fields = any(
        isinstance(chunk, dict) and "full_doc_id" in chunk
        for chunk in text_chunks.values()
    )
    return owned_records if has_ownership_fields else None


async def _mark_degraded_document(
    kb_name: str,
    doc_id: str,
    info: dict[str, Any],
    *,
    error_message: str,
) -> dict[str, Any] | None:
    """Persist degraded metadata only after every declared text chunk is readable."""
    metadata = info.get("metadata") or {}
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    failure_stage = str(metadata.get("failure_stage") or "").lower()
    marker_required = bool(
        metadata.get("multimodal_chunks")
        or metadata.get("residual_multimodal_chunk_ids")
        or failure_stage in {"multimodal", "worker_timeout", "finalize"}
    )
    if (
        metadata.get("content_ready") is False
        or metadata.get("multimodal_processed") is False
        or metadata.get("cleanup_pending") is True
        or (marker_required and metadata.get("multimodal_processed") is not True)
    ):
        kb_logger.warning(
            "Document content quality gate rejected incomplete worker state: "
            "kb=%s doc=%s failure_stage=%s",
            kb_name,
            doc_id,
            metadata.get("failure_stage", "unknown"),
        )
        return None

    chunk_ids = [str(value) for value in info.get("chunks_list", []) if value]
    try:
        expected_count = int(info.get("chunks_count") or len(chunk_ids))
    except (TypeError, ValueError):
        expected_count = len(chunk_ids)
    if expected_count <= 0 or len(chunk_ids) != expected_count:
        return None

    persisted_chunk_ids = await _load_persisted_chunk_ids_for_document(
        kb_name, doc_id,
    )
    if persisted_chunk_ids is None and _pg_storage_ready():
        kb_logger.warning(
            "Document content quality gate rejected unverifiable persisted "
            "chunks: kb=%s doc=%s",
            kb_name,
            doc_id,
        )
        return None
    if persisted_chunk_ids is not None and persisted_chunk_ids != set(chunk_ids):
        kb_logger.warning(
            "Document content quality gate rejected chunk-set mismatch: "
            "kb=%s doc=%s declared=%d persisted=%d extra=%d missing=%d",
            kb_name,
            doc_id,
            len(chunk_ids),
            len(persisted_chunk_ids),
            len(persisted_chunk_ids - set(chunk_ids)),
            len(set(chunk_ids) - persisted_chunk_ids),
        )
        return None

    text_chunks = await _load_text_chunks_json(kb_name)
    from raganything.services.document_quality import evaluate_content_readiness
    quality = await evaluate_content_readiness(kb_name, chunk_ids, text_chunks)
    if not quality["ready"]:
        kb_logger.warning(
            "Document content quality gate rejected degraded state: kb=%s doc=%s quality=%s",
            kb_name, doc_id, quality,
        )
        return None

    existing_failed_ids = metadata.get("failed_chunk_ids")
    if isinstance(existing_failed_ids, list):
        failed_chunk_ids = [
            str(value) for value in existing_failed_ids if str(value) in text_chunks
        ]
    else:
        failed_chunk_ids = [
            chunk_id
            for chunk_id in chunk_ids
            if not (text_chunks.get(chunk_id) or {}).get("llm_cache_list")
        ]
    try:
        retry_count = max(0, int(metadata.get("retry_count") or 0))
    except (TypeError, ValueError):
        retry_count = 0

    metadata.update({
        "content_ready": True,
        # Legacy text-only degraded documents predate the durable marker. They
        # have no multimodal residue, so normalize them to an explicit success
        # marker before allowing tagging.
        "multimodal_processed": metadata.get("multimodal_processed") is not False,
        "graph_status": "pending",
        "failure_stage": "entity_extraction",
        "retryable": _is_retryable_graph_failure(error_message),
        "failed_chunk_ids": failed_chunk_ids,
        "retry_count": retry_count,
        "last_error": str(error_message or "")[:4000],
    })

    try:
        rag = kb_instances.get(kb_name)
        if rag is None:
            rag = await get_kb(kb_name)
        if rag is None or not getattr(rag, "lightrag", None):
            return None
        await rag.lightrag.doc_status.upsert({
            doc_id: {**info, "status": "failed", "metadata": metadata},
        })
        await rag.lightrag.doc_status.index_done_callback()
    except Exception:
        kb_logger.warning(
            "Failed to persist degraded document state: KB=%s doc=%s",
            kb_name, doc_id, exc_info=True,
        )
        return None
    return metadata


async def _find_degraded_document(
    kb_name: str,
    filename: str,
    error_message: str,
    *,
    task_id: str = "",
    file_hash: str = "",
) -> tuple[str, dict[str, Any]] | None:
    """Find and validate the newest failed document matching an upload."""
    data = await _load_doc_status_json(kb_name)
    fname = os.path.basename(filename)
    matches: list[tuple[str, dict[str, Any], bool]] = []
    for doc_id, info in (data or {}).items():
        if not isinstance(info, dict) or str(info.get("status") or "").lower() != "failed":
            continue
        stored_base = os.path.basename(str(info.get("file_path") or ""))
        is_exact = stored_base == fname
        is_prefixed = (
            stored_base.endswith("_" + fname)
            and len(stored_base) - len(fname) == 9
        )
        if is_exact or is_prefixed:
            metadata = info.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            candidate_markers = {
                str(value)
                for value in (info.get("track_id"), metadata.get("task_id"))
                if value
            }
            candidate_hash = str(metadata.get("file_hash") or "")
            if task_id or file_hash:
                # Once the caller has provenance, a filename match by itself
                # is insufficient to enter degraded/tagging recovery.
                if task_id and candidate_markers and task_id not in candidate_markers:
                    continue
                if file_hash and candidate_hash and candidate_hash != file_hash:
                    continue
                if not candidate_markers and not candidate_hash:
                    continue
            matches.append((str(doc_id), info, is_exact))
    matches.sort(
        key=lambda match: (
            match[2],
            str(match[1].get("updated_at") or match[1].get("created_at") or ""),
        ),
        reverse=True,
    )
    if not matches:
        return None
    doc_id, info, _is_exact = matches[0]
    metadata = await _mark_degraded_document(
        kb_name,
        doc_id,
        info,
        error_message=info.get("error_msg") or error_message,
    )
    return (doc_id, metadata) if metadata is not None else None


async def _finalize_failed_upload(
    task_id: str,
    kb_name: str,
    filename: str,
    user_id: int,
    error_message: str,
    file_hash: str | None,
    chunking_strategy: str = "",
    claim_owner: str | None = None,
    claim_generation: int | None = None,
    *,
    verified_degraded: tuple[str, dict[str, Any]] | None = None,
) -> None:
    """Persist document failure before making its task terminal.

    Recovery treats non-terminal task rows as a KB-wide liveness guard. Keep
    that guard in place until the matching document is failed (or a retryable
    placeholder was created), so periodic recovery cannot complete it in the
    middle of failure handling.
    """
    from raganything.services.ws_service import add_event
    from raganything.services.state_service import complete_task, fail_task

    await _fix_stuck_doc_status(
        kb_name,
        filename,
        error_message,
        task_id,
        chunking_strategy,
        file_hash or "",
    )

    degraded = verified_degraded
    if degraded is None:
        degraded = await _find_degraded_document(
            kb_name,
            filename,
            error_message,
            task_id=task_id,
            file_hash=file_hash or "",
        )
    if degraded is not None:
        doc_id, metadata = degraded
        warning = "文本内容已入库，知识图谱抽取待补全"
        if metadata.get("retryable") is True:
            from raganything.services.document_repair import enqueue_repair

            await enqueue_repair(
                kb_name,
                doc_id,
                error=metadata.get("last_error") or error_message,
            )
        try:
            from raganything.services.document_tagging import (
                enqueue_document_tagging,
                wait_for_document_tagging,
            )

            await enqueue_document_tagging(
                kb_name,
                doc_id,
                filename=filename,
                user_id=user_id,
                task_id=task_id,
            )
        except Exception as exc:
            await _defer_tagging_schedule(
                task_id,
                kb_name,
                filename,
                doc_id,
                f"自动标签任务暂时无法入队: {exc}",
                file_hash,
            )
            return
        try:
            tag_health = await wait_for_document_tagging(kb_name, doc_id)
        except TimeoutError as exc:
            await _defer_tagging_schedule(
                task_id,
                kb_name,
                filename,
                doc_id,
                f"自动标签仍在后台处理中: {exc}",
                file_hash,
            )
            return
        if tag_health.get("tag_status") in {"failed", "disabled"}:
            await _finalize_tagging_failure(
                task_id,
                kb_name,
                filename,
                user_id,
                doc_id,
                tag_health.get("tag_error_message")
                or "文档正文已入库，但自动标签未完成",
                file_hash,
            )
            return
        upload_row = await pg_update_upload_status_by_task_id(
            task_id,
            "completed",
            kb_name=kb_name,
            error_message=warning,
            outcome="degraded",
            warning_message=warning,
            claim_owner=claim_owner,
            claim_generation=claim_generation,
        )
        if claim_owner is not None and upload_row is None:
            kb_logger.info("Ignoring stale degraded completion: task=%s", task_id)
            return
        await complete_task(task_id, outcome="degraded", warning=warning)
        await add_event(
            "upload_complete", file=filename, task_id=task_id, kb=kb_name,
            outcome="degraded", warning=warning, doc_id=doc_id, user_id=user_id,
        )
        if file_hash is not None:
            _unregister_processing_file(kb_name, file_hash)
        return

    upload_row = await pg_update_upload_status_by_task_id(
        task_id,
        "failed",
        kb_name=kb_name,
        error_message=error_message,
        claim_owner=claim_owner,
        claim_generation=claim_generation,
    )
    if claim_owner is not None and upload_row is None:
        kb_logger.info("Ignoring stale upload failure: task=%s", task_id)
        return
    await fail_task(task_id, error_message)
    await add_event(
        "upload_error", file=filename, task_id=task_id,
        error=error_message, user_id=user_id,
    )
    if file_hash is not None:
        _unregister_processing_file(kb_name, file_hash)


# ── Document Upload Processing ─────────────────────────────

class DocumentProcessingFailedError(RuntimeError):
    """The worker persisted an explicit failed document status."""


class DocumentPartiallyProcessedError(DocumentProcessingFailedError):
    """Text chunks are durable, but graph enrichment did not finish."""

    def __init__(self, message: str, *, doc_id: str, metadata: dict[str, Any]):
        super().__init__(message)
        self.doc_id = doc_id
        self.metadata = metadata


class DocumentStatusPendingError(RuntimeError):
    """The worker succeeded, but its PG document row is not visible yet."""


class DocumentTaggingStageError(RuntimeError):
    """The document body is durable, but required automatic tagging failed."""

    def __init__(self, message: str, *, doc_id: str):
        super().__init__(message)
        self.doc_id = doc_id


class DocumentTaggingSchedulePendingError(RuntimeError):
    """The processed document is waiting for its durable tag job to be created."""

    def __init__(self, message: str, *, doc_id: str):
        super().__init__(message)
        self.doc_id = doc_id


async def _finalize_tagging_failure(
    task_id: str,
    kb_name: str,
    filename: str,
    user_id: int,
    doc_id: str,
    error_message: str,
    file_hash: str | None,
    *,
    claim_owner: str | None = None,
    claim_generation: int | None = None,
) -> None:
    """Fail only the upload/tag barrier while preserving the processed document."""
    from raganything.services.state_service import fail_task
    from raganything.services.ws_service import add_event, ws_broadcast

    upload_row = await pg_update_upload_status_by_task_id(
        task_id,
        "failed",
        kb_name=kb_name,
        error_message=error_message,
        outcome="terminal_failed",
        claim_owner=claim_owner,
        claim_generation=claim_generation,
    )
    if claim_owner is not None and upload_row is None:
        kb_logger.info("Ignoring stale tagging failure: task=%s", task_id)
        return
    await fail_task(
        task_id,
        error_message,
        outcome="terminal_failed",
        failure_stage="tagging",
        retryable=False,
    )
    await add_event(
        "upload_error",
        file=filename,
        task_id=task_id,
        kb=kb_name,
        doc_id=doc_id,
        error=error_message,
        failure_stage="tagging",
        user_id=user_id,
    )
    await ws_broadcast({
        "type": "upload_error",
        "task_id": task_id,
        "filename": filename,
        "kb": kb_name,
        "doc_id": doc_id,
        "error": error_message,
        "failure_stage": "tagging",
    })
    if file_hash is not None:
        _unregister_processing_file(kb_name, file_hash)


async def _defer_tagging_schedule(
    task_id: str,
    kb_name: str,
    filename: str,
    doc_id: str,
    error_message: str,
    file_hash: str | None,
    *,
    claim_owner: str | None = None,
    claim_generation: int | None = None,
) -> None:
    """Leave upload and document non-terminal until reconciliation creates the job."""
    from raganything.services.state_service import defer_task
    from raganything.services.ws_service import ws_broadcast

    upload_row = await pg_update_upload_status_by_task_id(
        task_id,
        "retry_wait",
        kb_name=kb_name,
        error_message=error_message,
        claim_owner=claim_owner,
        claim_generation=claim_generation,
    )
    if claim_owner is not None and upload_row is None:
        kb_logger.info("Ignoring stale tagging deferral: task=%s", task_id)
        return
    await defer_task(task_id, error_message, failure_stage="tagging")
    await ws_broadcast({
        "type": "upload_retry_wait",
        "task_id": task_id,
        "filename": filename,
        "kb": kb_name,
        "doc_id": doc_id,
        "error": error_message,
        "failure_stage": "tagging",
    })
    if file_hash is not None:
        _unregister_processing_file(kb_name, file_hash)


async def _verify_document_persisted(kb_name: str, filename: str) -> str | None:
    """Verify that a processed document has chunks in doc_status.

    Uses PG dispatch when PG storage is active, file fallback otherwise.

    PG absence and non-terminal rows are reported as temporarily pending so
    the upload can complete while automatic tagging retries in the background.
    Explicit failures and terminal zero-chunk rows remain hard failures.
    """
    data = await _load_doc_status_json(kb_name)
    if not data:
        if _pg_storage_ready():
            raise DocumentStatusPendingError(
                f"PG doc_status 暂时无数据 (KB={kb_name}, file={filename})"
            )
        raise RuntimeError(
            f"文档处理异常：doc_status 无数据 (KB={kb_name})"
        )

    fname = os.path.basename(filename)
    matches: list[tuple[str, dict[str, Any], bool]] = []
    for doc_id, info in data.items():
        if not isinstance(info, dict):
            continue
        stored_raw = info.get("file_path", "")
        stored_base = os.path.basename(stored_raw)
        # Robust match: handles hash-prefixed uploads (8-hex + "_" + original)
        # Length guard: prefix is exactly 9 chars (8 hex + 1 underscore)
        is_exact = stored_base == fname
        is_prefixed = (
            stored_base.endswith("_" + fname)
            and len(stored_base) - len(fname) == 9
        )
        if is_exact or is_prefixed:
            matches.append((str(doc_id), info, is_exact))
    if matches:
        # Exact staged filenames win. For repeated display names, the newest
        # persisted status is the current upload rather than an older document.
        matches.sort(
            key=lambda match: (
                match[2],
                str(match[1].get("updated_at") or match[1].get("created_at") or ""),
            ),
            reverse=True,
        )
        doc_id, info, _is_exact = matches[0]
        chunks_list = info.get("chunks_list") or []
        chunks = info.get("chunks_count")
        if chunks is None:
            chunks = len(chunks_list)
        try:
            chunks = int(chunks or 0)
        except (TypeError, ValueError):
            chunks = len(chunks_list)
        status = info.get("status", "?")
        normalized_status = str(status or "").lower()
        if normalized_status == "failed":
            degraded = await _mark_degraded_document(
                kb_name, doc_id, info, error_message=info.get("error_msg") or "",
            )
            if degraded is not None:
                raise DocumentPartiallyProcessedError(
                    f"文档文本已入库，图谱抽取待补全，chunks={chunks} "
                    f"(doc_id={doc_id[:16]})",
                    doc_id=doc_id,
                    metadata=degraded,
                )
            raise DocumentProcessingFailedError(
                f"文档处理异常：status=failed, chunks={chunks} (doc_id={doc_id[:16]})"
            )
        if chunks == 0:
            if _pg_storage_ready() and normalized_status in {
                "", "?", "pending", "queued", "processing", "handling",
            }:
                raise DocumentStatusPendingError(
                    f"PG 文档状态尚未完成：status={status}, chunks=0 "
                    f"(doc_id={doc_id[:16]})"
                )
            raise DocumentProcessingFailedError(
                f"文档处理异常：chunks=0, status={status} (doc_id={doc_id[:16]})"
            )
        return doc_id
    if _pg_storage_ready():
        raise DocumentStatusPendingError(
            f"PG doc_status 中暂未找到匹配记录 ({fname})"
        )
    raise RuntimeError(
        f"文档处理异常：doc_status 中未找到匹配记录 ({fname})"
    )


async def _resolve_uploaded_document_id(
    kb_name: str,
    filename: str,
    *,
    attempts: int = 5,
    retry_delay: float = 0.5,
) -> str | None:
    """Resolve a worker-written document without reusing the pre-worker cache."""
    pending_error: DocumentStatusPendingError | None = None
    total_attempts = max(1, int(attempts))
    # The subprocess owns the durable write. The cached server instance may
    # still hold finalized PG storage, so invalidate it once before reloading.
    if kb_name in kb_instances:
        del kb_instances[kb_name]
        kb_logger.info(
            "[KB] 清除 Worker 前缓存实例: %s（重新读取文档状态）", kb_name,
        )
    for attempt in range(total_attempts):
        try:
            document_id = await _verify_document_persisted(kb_name, filename)
        except DocumentProcessingFailedError:
            raise
        except DocumentStatusPendingError as exc:
            pending_error = exc
            document_id = None
        else:
            # Keep compatibility with storage adapters that signal pending as None.
            if document_id is None:
                pending_error = DocumentStatusPendingError(
                    f"文档状态暂时不可见 (KB={kb_name}, file={filename})"
                )
        if document_id:
            return document_id
        if attempt + 1 < total_attempts:
            delay = max(0.0, float(retry_delay)) * min(attempt + 1, 3)
            kb_logger.info(
                "[VERIFY] 文档状态尚不可见，准备重试 %s/%s (KB=%s, file=%s)",
                attempt + 1, total_attempts - 1, kb_name, filename,
            )
            await asyncio.sleep(delay)

    if pending_error is not None:
        kb_logger.warning(
            "[VERIFY] 文档状态重试耗尽，转入后台补偿 (KB=%s, file=%s): %s",
            kb_name, filename, pending_error,
        )
    return None


async def _cleanup_retry_document_residue(
    kb_name: str,
    filename: str,
    task_id: str,
    file_hash: str,
    *,
    retry_job_id: int | None,
) -> list[str]:
    """Remove incomplete data before a content-hash retry reuses its doc ID."""
    if retry_job_id is None:
        return []

    def _status_text(value: Any) -> str:
        return str(getattr(value, "value", value) or "").lower()

    search_name = os.path.basename(filename)
    async with _retry_cleanup_lock(kb_name, search_name):
        statuses = await _load_doc_status_json(kb_name)
        candidates: list[tuple[str, dict[str, Any]]] = []
        for doc_id, info in (statuses or {}).items():
            if not isinstance(info, dict):
                continue
            if _status_text(info.get("status")) != "failed":
                continue
            metadata = info.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if (
                metadata.get("cleanup_pending") is not True
                or metadata.get("residual_data") is not True
            ):
                continue
            stored_name = os.path.basename(str(info.get("file_path") or ""))
            if not (
                stored_name == search_name
                or (
                    stored_name.endswith("_" + search_name)
                    and len(stored_name) - len(search_name) == 9
                )
            ):
                continue
            markers = {
                str(value)
                for value in (info.get("track_id"), metadata.get("task_id"))
                if value
            }
            if markers and task_id not in markers:
                continue
            previous_hash = str(metadata.get("file_hash") or "")
            if previous_hash and file_hash and previous_hash != file_hash:
                continue
            candidates.append((str(doc_id), info))

        if not candidates:
            return []

        unscoped_candidates = [
            info for _doc_id, info in candidates
            if not (
                info.get("track_id")
                or (
                    isinstance(info.get("metadata"), dict)
                    and info["metadata"].get("task_id")
                )
                or (
                    isinstance(info.get("metadata"), dict)
                    and info["metadata"].get("file_hash")
                )
            )
        ]
        if unscoped_candidates:
            raise WorkerProcessError({
                "message": "无法确认重试残留归属（缺少 task_id/file_hash），重试已暂缓",
                "stage": "cleanup",
                "root_type": "RetryResidueCleanupUnscoped",
                "retryable": True,
            })

        # The current retry is itself active.  Only block cleanup when another
        # task for the same filename is also active.
        if _pg_storage_ready():
            from raganything.services.pg_state_repo import get_pg_pool

            active_conflict = await get_pg_pool().fetchval(
                "SELECT EXISTS(SELECT 1 FROM uploaded_files "
                "WHERE kb_name=$1 AND filename=$2 "
                "AND status IN ('queued','processing','retry_wait') "
                "AND task_id IS DISTINCT FROM $3)",
                kb_name,
                search_name,
                task_id,
            )
            if active_conflict:
                raise WorkerProcessError({
                    "message": "无法清理重试残留：同名文件仍有其他活动上传",
                    "stage": "cleanup",
                    "root_type": "RetryResidueCleanupConflict",
                    "retryable": True,
                })

        rag = kb_instances.get(kb_name)
        if rag is None:
            rag = await get_kb(kb_name)
        lightrag = getattr(rag, "lightrag", None) if rag is not None else None
        if lightrag is None:
            raise WorkerProcessError({
                "message": "无法清理重试残留：知识库存储不可用",
                "stage": "cleanup",
                "root_type": "RetryResidueCleanupUnavailable",
                "retryable": True,
            })

        workspace = "./rag_storage" if kb_name == "default" else f"./rag_storage_{kb_name}"
        cleaned: list[str] = []
        for doc_id, _info in candidates:
            current = await lightrag.doc_status.get_by_id(doc_id)
            if not isinstance(current, dict):
                raise WorkerProcessError({
                    "message": f"无法清理重试残留：文档状态不可见 ({doc_id})",
                    "stage": "cleanup",
                    "root_type": "RetryResidueStatusUnavailable",
                    "retryable": True,
                })
            current_metadata = current.get("metadata")
            current_metadata = (
                dict(current_metadata) if isinstance(current_metadata, dict) else {}
            )
            if (
                _status_text(current.get("status")) != "failed"
                or current_metadata.get("cleanup_pending") is not True
                or current_metadata.get("residual_data") is not True
            ):
                continue

            declared_ids = {
                str(value) for value in current.get("chunks_list") or [] if value
            }
            persisted_ids: set[str] = set()
            if _pg_storage_ready():
                from raganything.services.pg_state_repo import get_pg_pool

                rows = await get_pg_pool().fetch(
                    "SELECT id FROM LIGHTRAG_DOC_CHUNKS "
                    "WHERE workspace=$1 AND full_doc_id=$2",
                    workspace,
                    doc_id,
                )
                persisted_ids = {str(row["id"]) for row in rows if row.get("id")}
            all_ids = sorted(declared_ids | persisted_ids)
            current_ids = [
                str(value) for value in current.get("chunks_list") or [] if value
            ]
            if all_ids != current_ids:
                await lightrag.doc_status.upsert({
                    doc_id: {
                        **current,
                        "chunks_list": all_ids,
                        "chunks_count": len(all_ids),
                        "metadata": current_metadata,
                    }
                })
                await lightrag.doc_status.index_done_callback()

            try:
                result = await lightrag.adelete_by_doc_id(
                    doc_id, delete_llm_cache=True,
                )
                result_status = _status_text(getattr(result, "status", ""))
                if result_status != "success":
                    raise RuntimeError(
                        f"LightRAG cleanup returned {result_status or 'unknown'}"
                    )
                vision_repo = getattr(lightrag, "image_vision_repo", None)
                if vision_repo is not None and hasattr(vision_repo, "delete_by_doc_id"):
                    await vision_repo.delete_by_doc_id(doc_id)
                    if hasattr(vision_repo, "flush"):
                        await vision_repo.flush()
                cache = getattr(rag, "multimodal_status_cache", None)
                if cache is not None and hasattr(cache, "delete"):
                    await cache.delete([doc_id])
                    if hasattr(cache, "index_done_callback"):
                        await cache.index_done_callback()
                cleaned.append(doc_id)
            except Exception as exc:
                # Keep the marker so a later retry can attempt cleanup again.
                try:
                    latest = await lightrag.doc_status.get_by_id(doc_id)
                    if isinstance(latest, dict):
                        latest_metadata = latest.get("metadata")
                        latest_metadata = (
                            dict(latest_metadata)
                            if isinstance(latest_metadata, dict)
                            else {}
                        )
                        latest_metadata.update({
                            "content_ready": False,
                            "multimodal_processed": False,
                            "cleanup_pending": True,
                            "residual_data": True,
                            "failure_stage": "cleanup",
                            "last_error": str(exc)[:4000],
                            "task_id": task_id,
                            "file_hash": file_hash,
                        })
                        await lightrag.doc_status.upsert({
                            doc_id: {
                                **latest,
                                "status": DocStatus.FAILED,
                                "metadata": latest_metadata,
                            }
                        })
                        await lightrag.doc_status.index_done_callback()
                except Exception:
                    kb_logger.warning(
                        "Unable to preserve retry cleanup marker for doc=%s",
                        doc_id,
                        exc_info=True,
                    )
                raise WorkerProcessError({
                    "message": f"重试前清理文档残留失败: {exc}",
                    "stage": "cleanup",
                    "root_type": "RetryResidueCleanupError",
                    "retryable": True,
                }) from exc
        return cleaned


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


def _multimodal_tag_evidence(status_info: dict[str, Any], chunk_id: str) -> str:
    metadata = status_info.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    chunks = metadata.get("multimodal_chunks")
    if not isinstance(chunks, dict):
        return ""
    value = chunks.get(chunk_id)
    if not isinstance(value, dict):
        return ""
    evidence: list[str] = []
    for key in (
        "caption", "description", "summary", "ocr_text", "text",
        "table_content", "context", "nearby_heading", "title",
    ):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            evidence.append(item.strip())
        elif isinstance(item, list):
            evidence.extend(str(entry).strip() for entry in item if str(entry).strip())
    return "\n".join(evidence)


def _automatic_tag_chunk_records(
    records: list[dict[str, Any]], status_info: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize persisted records for the local automatic tag planner."""
    normalized: list[dict[str, Any]] = []
    for record in records:
        chunk = dict(record)
        chunk_id = _automatic_tag_chunk_id(chunk)
        if not chunk_id:
            continue
        chunk["chunk_id"] = chunk_id
        semantic_evidence = _multimodal_tag_evidence(status_info or {}, chunk_id)
        if semantic_evidence:
            chunk["content"] = "\n".join(
                value for value in (str(chunk.get("content") or ""), semantic_evidence)
                if value.strip()
            )
        normalized.append(chunk)
    return normalized


async def _load_automatic_tag_chunks(
    kb_name: str, document_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load one document's authoritative chunk set without repairing status."""
    status_info = await _load_doc_status_by_id(kb_name, document_id)
    if not isinstance(status_info, dict):
        raise RuntimeError(
            f"document status is not visible for automatic tagging: {document_id}"
        )

    chunk_ids = [
        str(value) for value in status_info.get("chunks_list") or [] if value
    ]
    if not chunk_ids:
        raise RuntimeError(
            f"document status has no chunk IDs for automatic tagging: {document_id}"
        )

    instance = await get_kb(kb_name)
    records = await instance.lightrag.text_chunks.get_by_ids(chunk_ids)
    chunks = _automatic_tag_chunk_records(
        [dict(record) for record in (records or []) if isinstance(record, dict)],
        status_info,
    )
    expected_ids = set(chunk_ids)
    loaded_ids = {chunk["chunk_id"] for chunk in chunks}
    if loaded_ids != expected_ids:
        raise RuntimeError(
            "persisted chunks are not fully visible for automatic tagging: "
            f"expected={len(expected_ids)}, loaded={len(loaded_ids)}"
        )
    return chunks, {
        "chunk_count": len(chunks),
        "status_retries": 0,
        "status_repaired": False,
        "chunk_source": "doc_status",
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
        automatic_tagging_settings,
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
    async with _auto_tag_planning_semaphore:
        plan = await asyncio.to_thread(
            build_automatic_tag_plan,
            chunks,
            filename=filename,
            **automatic_tagging_settings(),
        )
    result = await replace_automatic_document_tags(
        kb_name,
        document_id,
        plan.document_tags,
        plan.chunk_tags,
        user_id=user_id,
        document_tag_names_by_chunk=plan.document_tags_by_chunk,
    )
    raw_persisted_ids = result.get("tagged_chunk_ids")
    if not isinstance(raw_persisted_ids, (list, tuple, set)):
        raise RuntimeError("automatic tag persistence did not return coverage evidence")
    persisted_tagged_ids = {str(chunk_id) for chunk_id in raw_persisted_ids}
    tagged_chunk_count = len(set(plan.eligible_chunk_ids) & persisted_tagged_ids)
    return {
        **result,
        **recovery,
        "eligible_chunk_count": len(plan.eligible_chunk_ids),
        "tagged_chunk_count": tagged_chunk_count,
        "not_applicable_count": len(plan.not_applicable_chunk_ids),
        "content_fingerprint": plan.content_fingerprint,
    }


async def _retry_deferred_uploaded_document_tags(
    kb_name: str,
    persisted_filename: str,
    *,
    display_filename: str = "",
    user_id: int,
) -> None:
    """Compensate an upload whose PG document status was temporarily hidden."""
    try:
        document_id = await _resolve_uploaded_document_id(
            kb_name, persisted_filename, attempts=10, retry_delay=2.0,
        )
        if not document_id:
            kb_logger.error(
                "[AUTO-TAGS] deferred retry exhausted; KB=%s file=%s",
                kb_name, persisted_filename,
            )
            return
        result = await _generate_uploaded_document_tags(
            kb_name,
            document_id,
            filename=display_filename or persisted_filename,
            user_id=user_id,
        )
        kb_logger.info(
            "[AUTO-TAGS] deferred generation completed KB=%s doc=%s file=%s "
            "source=%s assigned=%s",
            kb_name, document_id, display_filename or persisted_filename,
            result["chunk_source"], result["assigned"],
        )
    except Exception:
        kb_logger.exception(
            "[AUTO-TAGS] deferred generation failed; KB=%s file=%s",
            kb_name, persisted_filename,
        )


def _schedule_deferred_uploaded_document_tags(
    kb_name: str,
    persisted_filename: str,
    *,
    display_filename: str = "",
    user_id: int,
) -> None:
    task = asyncio.create_task(
        _retry_deferred_uploaded_document_tags(
            kb_name,
            persisted_filename,
            display_filename=display_filename,
            user_id=user_id,
        )
    )
    _deferred_auto_tag_tasks[task] = kb_name
    task.add_done_callback(lambda completed: _deferred_auto_tag_tasks.pop(completed, None))


async def _cancel_deferred_auto_tag_tasks(kb_name: str | None = None) -> None:
    """Cancel tracked compensation before its KB or the process shuts down."""
    tasks = [
        task for task, task_kb in list(_deferred_auto_tag_tasks.items())
        if kb_name is None or task_kb == kb_name
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _process_uploaded_file(
    task_id: str, file_path: str, filename: str,
    kb_name: str = "default", chunking_strategy: str = "", user_id: int = 0,
    enable_image: bool | None = None,
    enable_table: bool | None = None,
    enable_equation: bool | None = None,
    enable_video: bool | None = None,
    vision_vlm_profile_id: str | None = None,
    vision_vlm_profile_fingerprint: str | None = None,
    settings_snapshot_id: str | None = None,
    retry_job_id: int | None = None,
    retry_lease_token: str | None = None,
    claim_owner: str | None = None,
    claim_generation: int | None = None,
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

    if await _upload_is_cancelling(task_id, kb_name):
        return

    # The worker is deliberately driven by the enqueue-time PG snapshot.  A
    # missing snapshot is a deterministic failure, not permission to use
    # process environment or changed user preferences.
    from raganything.services.user_settings import get_task_settings_snapshot
    snapshot = await get_task_settings_snapshot(task_id)
    ingestion = (snapshot.get("settings") or {}).get("ingestion") or {}
    actual_strategy = ingestion.get("chunking_strategy")
    if not isinstance(actual_strategy, str) or not actual_strategy:
        raise RuntimeError("settings_snapshot_invalid")
    # Queue fields are transport metadata only. The durable snapshot is the
    # sole configuration authority for the queued task and every retry.
    # Keep the profile and snapshot identifiers in the callable contract so
    # queue task dictionaries can be expanded without altering that authority.
    enable_image = ingestion.get("enable_image")
    enable_table = ingestion.get("enable_table")
    enable_equation = ingestion.get("enable_equation")
    enable_video = ingestion.get("enable_video")
    task_data = {
        "id": task_id, "file": filename, "status": "processing",
        "started_at": datetime.now().isoformat(), "progress": 0,
        "kb": kb_name, "user_id": user_id,
        "phase": "initializing",
        "phase_status": "start",
        "message": "初始化处理环境",
        "chunking_strategy": actual_strategy,
        "settings_revision": snapshot.get("revision"),
        "settings_fingerprint": snapshot.get("fingerprint"),
    }
    await upsert_task_state(task_id, task_data)
    await add_event("upload_start", file=filename, task_id=task_id, user_id=user_id)
    # Register for dedup tracking (inside try — file I/O can fail)
    file_hash = None
    worker_progress_state = {"track": "text"}
    worker_slot: asyncio.Semaphore | None = None
    worker_slot_acquired = False
    try:
        # Compute file hash and register for dedup (may fail if file was removed)
        file_hash = _compute_file_hash(file_path)
        _register_processing_file(kb_name, file_hash, task_id)

        # Update PG uploaded_files status → processing
        processing_row = await pg_update_upload_status_by_task_id(
            task_id,
            "processing",
            kb_name=kb_name,
            error_message="",
            claim_owner=claim_owner,
            claim_generation=claim_generation,
        )
        if claim_owner is not None and processing_row is None:
            raise RuntimeError("upload_claim_lost")
        await _cleanup_retry_document_residue(
            kb_name,
            filename,
            task_id,
            file_hash or "",
            retry_job_id=retry_job_id,
        )
        kb_logger.info(f"[UPLOAD] 任务={task_id} 文件={filename} KB={kb_name} 策略={actual_strategy}")

        worker_script = Path(__file__).parent.parent.parent / "process_worker.py"
        cmd = [
            sys.executable, str(worker_script),
            "--file", str(Path(file_path).resolve()),
            "--kb", kb_name,
            "--strategy", actual_strategy,
            "--task-id", task_id,
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

        worker_slot = _get_ocr_worker_slot()
        await worker_slot.acquire()
        worker_slot_acquired = True
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
        worker_started_at = time.monotonic()
        worker_progress_state["last_progress_at"] = worker_started_at
        worker_progress_event = asyncio.Event()

        async def _read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    worker_output_lines.append(text)
                    if len(worker_output_lines) > 2000:
                        del worker_output_lines[:-1000]
                    kb_logger.info(f"[WORKER:{task_id}] {text}")
                    progress_update = _parse_worker_progress_line(text, worker_progress_state)
                    if progress_update:
                        # A parsed page/chunk/stage update is a real Worker
                        # heartbeat, even if the upload state was concurrently
                        # removed during shutdown.
                        worker_progress_state["last_progress_at"] = time.monotonic()
                        worker_progress_state["last_progress"] = dict(progress_update)
                        worker_progress_event.set()
                        if task_id in processing_tasks:
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
            idle_timeout_sec, max_elapsed_sec = _worker_watchdog_config()
            await _wait_for_worker_with_watchdog(
                proc,
                worker_progress_event,
                worker_progress_state,
                idle_timeout=idle_timeout_sec,
                max_elapsed=max_elapsed_sec,
                started_at=worker_started_at,
            )
        except asyncio.TimeoutError:
            elapsed_sec = max(0.0, time.monotonic() - worker_started_at)
            timeout_kind = worker_progress_state.get("watchdog_timeout", "idle")
            last_progress = worker_progress_state.get("last_progress") or {}
            resources_before_kill = _worker_resource_snapshot(proc)
            returncode_before_kill = proc.returncode
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    # The child can exit between the watchdog decision and
                    # kill(); still collect its final return code/output.
                    pass
            await proc.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            output_tail = "\n".join(worker_output_lines[-20:])[-4000:]
            kb_logger.error(
                "[WORKER-TIMEOUT] task=%s kb=%s file=%s kind=%s stage=%s "
                "elapsed=%.1fs idle_timeout=%.1fs max_timeout=%.1fs "
                "last_progress=%s returncode_before_kill=%s returncode=%s "
                "resources=%s output_tail=%r",
                task_id,
                kb_name,
                filename,
                timeout_kind,
                worker_progress_state.get("track", "unknown"),
                elapsed_sec,
                idle_timeout_sec,
                max_elapsed_sec,
                last_progress,
                returncode_before_kill,
                proc.returncode,
                resources_before_kill,
                output_tail,
             )
            raise WorkerProcessError({
                "message": (
                    f"子进程处理因{('总时长' if timeout_kind == 'max_elapsed' else '无进度')}超时 "
                    f"（已运行 {elapsed_sec / 60:.1f} 分钟，"
                    f"空闲阈值 {idle_timeout_sec / 60:.1f} 分钟）"
                ),
                "stage": "timeout",
                "root_type": "WorkerWatchdogTimeout",
                "retryable": True,
                "secondary": [
                    f"last_progress={last_progress}",
                    f"resources={resources_before_kill}",
                    f"output_tail={output_tail[-2000:]}",
                ],
            })
        await stdout_task
        await stderr_task
        worker_slot.release()
        worker_slot_acquired = False

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
                conflict_lines = [
                    line for line in worker_output_lines
                    if "already being processed" in line or "active processor" in line
                ]
                conflict_detail = conflict_lines[0] if conflict_lines else "文件正在被另一个 Worker 处理"
                raise RuntimeError(f"处理冲突: {conflict_detail}")
            raise WorkerProcessError(
                _parse_worker_error(worker_output_lines, proc.returncode)
            )

        if worker_has_errors:
            error_lines = [
                line for line in worker_output_lines
                if "ERROR:" in line and "Merging" in line
            ]
            error_detail = error_lines[0] if error_lines else "Merging stage failed"
            raise RuntimeError(f"子进程实体提取失败 (chunks=0): {error_detail}")

        # Verify data was actually persisted: the worker may exit 0 even when
        # LightRAG internally marked the document as failed.
        persisted_filename = os.path.basename(file_path)
        document_id = await _resolve_uploaded_document_id(
            kb_name, persisted_filename,
        )

        await emit_progress(task_id, 96, "文档主体处理完成，正在生成标签")
        # Tags are the final upload stage. Keep the task non-terminal until the
        # durable tag job reaches a successful or explicit terminal state.
        if document_id:
            try:
                from raganything.services.document_tagging import (
                    enqueue_document_tagging,
                    wait_for_document_tagging,
                )

                try:
                    tag_job = await enqueue_document_tagging(
                        kb_name,
                        document_id,
                        filename=filename,
                        user_id=user_id,
                        task_id=task_id,
                    )
                except Exception as exc:
                    raise DocumentTaggingSchedulePendingError(
                        f"自动标签任务暂时无法入队: {exc}", doc_id=document_id,
                    ) from exc
                kb_logger.info(
                    "[AUTO-TAGS] queued KB=%s doc=%s file=%s job=%s status=%s",
                    kb_name, document_id, filename, tag_job["id"], tag_job["status"],
                )
                await emit_progress(task_id, 97, "标签生成中")
                try:
                    tag_health = await wait_for_document_tagging(kb_name, document_id)
                except TimeoutError as exc:
                    raise DocumentTaggingSchedulePendingError(
                        f"自动标签仍在后台处理中: {exc}", doc_id=document_id,
                    ) from exc
                else:
                    if tag_health.get("tag_status") in {"failed", "disabled"}:
                        raise DocumentTaggingStageError(
                            tag_health.get("tag_error_message")
                            or "文档主体已处理，但自动标签未完成",
                            doc_id=document_id,
                        )
            except (DocumentTaggingStageError, DocumentTaggingSchedulePendingError):
                raise
            except Exception as exc:
                raise DocumentTaggingStageError(
                    f"自动标签阶段失败: {exc}", doc_id=document_id,
                ) from exc
        else:
            raise RuntimeError(
                f"无法确认文档 ID，不能确认自动标签是否完成: {filename}"
            )
        if retry_job_id is not None and not retry_lease_token:
            kb_logger.warning("Ignoring retry without lease: job=%s", retry_job_id)
            return
        await persist_document_processing_snapshot(
            kb_name, persisted_filename, task_id, snapshot
        )
        upload_row = await pg_update_upload_status_by_task_id(
            task_id,
            "completed",
            kb_name=kb_name,
            error_message="",
            outcome="",
            warning_message="",
            claim_owner=claim_owner,
            claim_generation=claim_generation,
        )
        if claim_owner is not None and upload_row is None:
            kb_logger.info("Ignoring stale upload completion: task=%s", task_id)
            return
        if retry_job_id is not None:
            from raganything.services.upload_retry import complete_upload_retry

            if not await complete_upload_retry(retry_job_id, retry_lease_token):
                kb_logger.warning(
                    "Retry lease lost after upload completion: job=%s task=%s",
                    retry_job_id, task_id,
                )
        await emit_progress(task_id, 100, "处理完成（含标签）")
        await complete_task(task_id)
        if task_id in processing_tasks:
            processing_tasks[task_id]["chunking_strategy"] = actual_strategy
        await add_event(
            "upload_complete", file=filename, task_id=task_id, kb=kb_name,
            user_id=user_id, outcome="", warning="",
        )
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
        if kb_name in _kbs_being_deleted or await _upload_is_cancelling(task_id, kb_name):
            kb_logger.warning(
                f"[UPLOAD] KB '{kb_name}' 已被删除，跳过失败状态写入: "
                f"file={filename} task={task_id}"
            )
            return

        if isinstance(e, DocumentTaggingSchedulePendingError):
            if retry_job_id is not None and retry_lease_token:
                try:
                    from raganything.services.upload_retry import complete_upload_retry

                    await complete_upload_retry(retry_job_id, retry_lease_token)
                except Exception:
                    kb_logger.warning(
                        "Unable to close upload retry while tagging waits for scheduling: job=%s",
                        retry_job_id,
                        exc_info=True,
                    )
            await _defer_tagging_schedule(
                task_id,
                kb_name,
                filename,
                e.doc_id,
                str(e),
                file_hash,
                claim_owner=claim_owner,
                claim_generation=claim_generation,
            )
            return

        if isinstance(e, DocumentTaggingStageError):
            if retry_job_id is not None and retry_lease_token:
                try:
                    from raganything.services.upload_retry import complete_upload_retry

                    await complete_upload_retry(retry_job_id, retry_lease_token)
                except Exception:
                    kb_logger.warning(
                        "Unable to close upload retry after terminal tagging failure: job=%s",
                        retry_job_id,
                        exc_info=True,
                    )
            await _finalize_tagging_failure(
                task_id,
                kb_name,
                filename,
                user_id,
                e.doc_id,
                str(e),
                file_hash,
                claim_owner=claim_owner,
                claim_generation=claim_generation,
            )
            return

        if isinstance(e, DocumentPartiallyProcessedError):
            await _finalize_failed_upload(
                task_id,
                kb_name,
                filename,
                user_id,
                str(e),
                file_hash,
                actual_strategy,
                claim_owner,
                claim_generation,
                verified_degraded=(e.doc_id, e.metadata),
            )
            return

        if isinstance(e, WorkerProcessError) and e.stage in {"embedding", "vlm_ocr"}:
            try:
                residual_doc_id = await _resolve_uploaded_document_id(
                    kb_name, os.path.basename(file_path),
                )
                if residual_doc_id:
                    from raganything.services.document_quality import (
                        cleanup_failed_invalid_residue,
                    )

                    await cleanup_failed_invalid_residue(
                        kb_dir(kb_name),
                        residual_doc_id,
                        expected_filename=filename,
                        allow_task_id=task_id,
                        require_zero_vectors=False,
                        require_path_placeholders=False,
                    )
            except ValueError as cleanup_error:
                kb_logger.info(
                    "Partial upload cleanup skipped: task=%s reason=%s",
                    task_id, cleanup_error,
                )
            except Exception:
                kb_logger.warning(
                    "Partial upload cleanup failed: task=%s", task_id,
                    exc_info=True,
                )

        if isinstance(e, WorkerProcessError) and e.stage in {
            "multimodal", "finalize", "timeout",
        }:
            # Retry scheduling must not bypass document failure persistence.
            # Mark the row incomplete first so tagging/degraded recovery cannot
            # consume chunks written before the worker stopped.
            await _fix_stuck_doc_status(
                kb_name,
                filename,
                str(e),
                task_id,
                actual_strategy,
                file_hash or "",
            )

        if isinstance(e, WorkerProcessError) and e.retryable:
            from raganything.services.upload_retry import schedule_upload_retry

            retry_job = await schedule_upload_retry(
                task_id=task_id,
                kb_name=kb_name,
                file_path=file_path,
                filename=filename,
                file_hash=file_hash or "",
                user_id=user_id,
                stage=e.stage,
                root_type=e.root_type,
                error=str(e),
                chunking_strategy=actual_strategy,
                enable_image=enable_image,
                enable_table=enable_table,
                enable_equation=enable_equation,
                enable_video=enable_video,
                retry_job_id=retry_job_id,
                lease_token=retry_lease_token,
                claim_owner=claim_owner,
                claim_generation=claim_generation,
            )
            if retry_job is not None:
                retry_count = int(retry_job.get("attempt_count") or 0)
                max_retries = int(retry_job.get("max_attempts") or 5)
                retry_status = str(retry_job.get("status") or "retry_wait")
                task = processing_tasks.setdefault(task_id, {"id": task_id})
                task.update({
                    "status": "failed" if retry_status == "terminal_failed" else "retry_wait",
                    "retryable": retry_status != "terminal_failed",
                    "failure_stage": e.stage,
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "next_retry_at": (
                        retry_job["next_attempt_at"].isoformat()
                        if retry_job.get("next_attempt_at") else None
                    ),
                    "error": str(e),
                    "error_message": str(e),
                })
                await ws_broadcast({
                    "type": "upload_retry_wait",
                    "task_id": task_id,
                    "filename": filename,
                    "kb": kb_name,
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "next_retry_at": task.get("next_retry_at"),
                })
                if file_hash is not None:
                    _unregister_processing_file(kb_name, file_hash)
                return

        if isinstance(e, WorkerProcessError) and e.stage in {
            "model_preflight", "embedding", "vlm_ocr", "ocr",
        }:
            from raganything.services.state_service import fail_task

            upload_row = await pg_update_upload_status_by_task_id(
                task_id,
                "failed",
                kb_name=kb_name,
                error_message=str(e),
                claim_owner=claim_owner,
                claim_generation=claim_generation,
            )
            if claim_owner is None or upload_row is not None:
                await fail_task(
                    task_id,
                    str(e),
                    failure_stage=e.stage,
                    retryable=False if e.stage == "ocr" else e.retryable,
                )
                await add_event(
                    "upload_error", file=filename, task_id=task_id,
                    error=str(e), failure_stage=e.stage, user_id=user_id,
                )
            if file_hash is not None:
                _unregister_processing_file(kb_name, file_hash)
            return

        await _finalize_failed_upload(
            task_id,
            kb_name,
            filename,
            user_id,
            str(e),
            file_hash,
            actual_strategy,
            claim_owner,
            claim_generation,
        )
    finally:
        if worker_slot_acquired and worker_slot is not None:
            worker_slot.release()


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
            claim_owner = ""
            claim_generation: int | None = None
            if task_id:
                upload_record = await pg_get_upload_by_task_id(
                    task_id,
                    kb_name=kb_name,
                    is_admin=True,
                )
                if upload_record is None:
                    _queued_task_ids.discard(task_id)
                    kb_logger.error(
                        "[QUEUE] Rejecting task without durable upload record: task=%s kb=%s",
                        task_id,
                        kb_name,
                    )
                    continue
                if upload_record and upload_record.get("status") in {"deleted", "cancelling"}:
                    _queued_task_ids.discard(task_id)
                    _unregister_processing_file(kb_name, upload_record.get("file_hash", ""))
                    kb_logger.info(
                        f"[QUEUE] 璺宠繃宸插垹闄ょ殑浠诲姟: task={task_id} kb={kb_name}"
                    )
                    continue
                if upload_record and upload_record.get("status") == "queued":
                    claim_owner = f"upload:{os.getpid()}:{uuid.uuid4()}"
                    claim_generation = await pg_claim_upload_task(
                        task_id, kb_name, claim_owner
                    )
                    if claim_generation is None:
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
                        _queued_task_ids.discard(task_id)
                        kb_logger.info(
                            "[QUEUE] Claim lost task=%s status=%s kb=%s",
                            task_id,
                            refreshed.get("status") if refreshed else "missing",
                            kb_name,
                        )
                        continue
                    _queued_task_ids.discard(task_id)
                elif upload_record and upload_record.get("status") != "queued":
                    _queued_task_ids.discard(task_id)
                    kb_logger.info(
                        "[QUEUE] Skipping already claimed task=%s status=%s kb=%s",
                        task_id,
                        upload_record.get("status"),
                        kb_name,
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
                if task_id:
                    _queued_task_ids.discard(task_id)
                from raganything.services.kb_mutation import run_kb_mutation_with_lease
                from raganything.services.kb_corpus_revision import run_corpus_mutation

                async def process_claimed_upload() -> None:
                    await _process_uploaded_file(
                        **task_info,
                        claim_owner=claim_owner or None,
                        claim_generation=claim_generation,
                    )

                processing_task = asyncio.create_task(
                    run_kb_mutation_with_lease(
                        kb_name,
                        task_id,
                        lambda: run_corpus_mutation(
                            kb_name, task_id, "upload", process_claimed_upload
                        ),
                        mutation_kind="upload",
                    )
                )
                if task_id:
                    _active_upload_execution[task_id] = processing_task
                claim_lost = asyncio.Event()

                async def heartbeat_claim() -> None:
                    if not task_id or claim_generation is None:
                        return
                    try:
                        while True:
                            await asyncio.sleep(15)
                            if not await pg_heartbeat_upload_claim(
                                task_id, kb_name, claim_owner, claim_generation
                            ):
                                claim_lost.set()
                                processing_task.cancel()
                                return
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        claim_lost.set()
                        processing_task.cancel()

                claim_heartbeat = asyncio.create_task(heartbeat_claim())
                try:
                    await processing_task
                except asyncio.CancelledError as exc:
                    if claim_lost.is_set():
                        raise RuntimeError("upload_claim_lost") from exc
                    raise
                finally:
                    if task_id:
                        _active_upload_execution.pop(task_id, None)
                    claim_heartbeat.cancel()
                    await asyncio.gather(claim_heartbeat, return_exceptions=True)
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
_queued_task_ids: set[str] = set()


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
            def _log_drain_failure(completed: asyncio.Task) -> None:
                if completed.cancelled():
                    return
                error = completed.exception()
                if error is not None:
                    kb_logger.error(
                        "[QUEUE] Drain failed: %s",
                        kb_name,
                        exc_info=(type(error), error, error.__traceback__),
                    )

            task.add_done_callback(_log_drain_failure)

    return queue, qsize


async def _enqueue_upload_task(task_info: dict[str, Any]) -> tuple[asyncio.Queue, int]:
    """Add one durable upload task to the process-local wakeup queue once."""
    kb_name = str(task_info.get("kb_name") or "")
    task_id = str(task_info.get("task_id") or "")
    queue, qsize = await _ensure_queue_draining(kb_name)
    if not task_id or task_id not in _queued_task_ids:
        if task_id:
            _queued_task_ids.add(task_id)
        queue.put_nowait(task_info)
    return queue, qsize


async def resume_queued_upload_tasks() -> int:
    """Rebuild process-local wakeups from the durable PostgreSQL queue."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        if hasattr(conn, "execute"):
            await conn.execute(
                "UPDATE uploaded_files SET status='queued',processing_owner=NULL,"
                "processing_heartbeat_at=NULL,updated_at=NOW() WHERE status='processing' "
                "AND (processing_heartbeat_at IS NULL OR processing_heartbeat_at < NOW()-INTERVAL '5 minutes')"
            )
        rows = await conn.fetch(
            "SELECT u.task_id,u.file_path,u.filename,u.kb_name,u.uploaded_by,"
            "s.task_id AS snapshot_task_id "
            "FROM uploaded_files u LEFT JOIN task_settings_snapshots s ON s.task_id=u.task_id "
            "WHERE u.status='queued' AND u.task_id IS NOT NULL "
            "ORDER BY u.created_at,u.id"
        )
    resumed = 0
    for row in rows:
        task_id = str(row["task_id"])
        kb_name = str(row["kb_name"])
        file_path = str(row["file_path"])
        if row["snapshot_task_id"] is None or not Path(file_path).is_file():
            error_code = "settings_snapshot_missing" if row["snapshot_task_id"] is None else "upload_file_missing"
            await pg_update_upload_status_by_task_id(
                task_id,
                "failed",
                kb_name=kb_name,
                expected_current_status="queued",
                error_message=error_code,
            )
            continue
        if task_id in _queued_task_ids:
            continue
        await _enqueue_upload_task({
            "task_id": task_id,
            "file_path": file_path,
            "filename": str(row["filename"]),
            "kb_name": kb_name,
            "chunking_strategy": "",
            "user_id": int(row["uploaded_by"] or 0),
        })
        resumed += 1
    return resumed


async def durable_upload_queue_loop(interval_seconds: float = 5.0) -> None:
    while True:
        try:
            await resume_queued_upload_tasks()
        except asyncio.CancelledError:
            raise
        except Exception:
            kb_logger.warning("Durable upload queue scan failed", exc_info=True)
        await asyncio.sleep(interval_seconds)


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

async def _reprocess_multimodal_for_kb_unbounded(
    kb_name: str,
    user_id: int = 1,
    task_id: str | None = None,
):
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

    if not task_id:
        raise RuntimeError("settings_snapshot_missing")
    from raganything.services.user_settings import get_task_settings_snapshot

    snapshot = await get_task_settings_snapshot(task_id)
    settings = snapshot.get("settings")
    if not isinstance(settings, dict):
        raise RuntimeError("settings_snapshot_invalid")
    instance = await get_kb(kb_name, task_settings=settings)
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
                if not await instance._mark_multimodal_processing_complete(doc_id):
                    raise RuntimeError(
                        "multimodal completion marker could not be persisted"
                    )
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
    await instance.finalize_storages()
    return result


async def _reprocess_multimodal_for_kb(
    kb_name: str,
    user_id: int = 1,
    task_id: str | None = None,
):
    if not task_id:
        raise RuntimeError("settings_snapshot_missing")
    from raganything.services.user_settings import run_ingestion_with_quota
    from raganything.services.kb_mutation import run_kb_mutation_with_lease
    from raganything.services.kb_corpus_revision import run_corpus_mutation

    return await run_ingestion_with_quota(
        task_id,
        lambda: run_kb_mutation_with_lease(
            kb_name,
            task_id,
            lambda: run_corpus_mutation(
                kb_name,
                task_id,
                "reprocess",
                lambda: _reprocess_multimodal_for_kb_unbounded(
                    kb_name,
                    user_id=user_id,
                    task_id=task_id,
                ),
            ),
            mutation_kind="reprocess",
        ),
    )


__all__ = [
    "kb_instances",
    "active_kb",
    "KB_META_FILE",
    "load_kb_meta",
    "save_kb_meta",
    "kb_dir",
    "get_kb",
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
