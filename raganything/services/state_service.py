# -*- coding: utf-8 -*-
"""
RAG-Anything State Service — PG-primary with in-memory read cache.

Layer: Service
Primary Responsibility: Thread-safe state management —
    processing task status (PG), query history (PG), conversation manager reference.

All writes go through PostgreSQL. The ``processing_tasks`` dict is populated
from PG at startup and updated by the PG-aware functions below. Direct dict
writes from other modules are deprecated — use the public functions instead.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

state_logger = logging.getLogger("rag_server.state")

# ── State ──────────────────────────────────────────────────

processing_tasks: dict[str, dict] = {}
"""In-flight document processing tasks (read cache, synced from PG).

.. deprecated:: direct write
    Use ``upsert_task_state()`` / ``complete_task()`` / ``delete_task()``
    / ``update_task_progress()`` instead of writing to this dict directly.
    Direct reads are still safe but may be stale if PG writes happen from
    another worker.
"""

query_history: list[dict] = []
"""Deprecated.  Kept for backward-compat imports.  Use ``record_query()``
and ``get_query_history()`` (PG-backed) instead.
"""


# ── Concurrency Guards ────────────────────────────────────

_task_lock: asyncio.Lock | None = None
"""Lock for processing_tasks mutations (lazily initialized per event loop)."""


def _get_task_lock() -> asyncio.Lock:
    """Return the task-state lock, creating it lazily per event loop."""
    global _task_lock
    if _task_lock is None:
        _task_lock = asyncio.Lock()
    return _task_lock


# ═══════════════════════════════════════════════════════════════
# PG readiness
# ═══════════════════════════════════════════════════════════════

def _task_pg_ready() -> bool:
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False


# ═══════════════════════════════════════════════════════════════
# PG-backed task state helpers
# ═══════════════════════════════════════════════════════════════

async def _pg_upsert_task(task_id: str, task_data: dict) -> None:
    """Write task state to PG (upsert)."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO processing_tasks
               (task_id, kb_name, file_name, file_hash, user_id,
               status, progress, phase, phase_status,
                chunking_strategy, error_message, message, outcome,
                warning_message, started_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NOW())
               ON CONFLICT (task_id) DO UPDATE SET
                kb_name=$2, file_name=$3, file_hash=$4, user_id=$5,
                status=$6, progress=$7, phase=$8, phase_status=$9,
                chunking_strategy=$10, error_message=$11, message=$12,
                outcome=$13, warning_message=$14,
                updated_at=NOW()""",
            task_id,
            task_data.get("kb", task_data.get("kb_name", "default")),
            task_data.get("file", task_data.get("file_name", "")),
            task_data.get("file_hash", ""),
            task_data.get("user_id", 0),
            task_data.get("status", "pending"),
            task_data.get("progress", 0),
            task_data.get("phase", ""),
            task_data.get("phase_status", ""),
            task_data.get("chunking_strategy", ""),
            task_data.get("error", ""),
            task_data.get("message", ""),
            task_data.get("outcome", ""),
            task_data.get("warning_message", task_data.get("warning", "")),
        )


async def _pg_complete_task(task_id: str, *, outcome: str = "", warning: str = ""):
    """Mark task as completed in PG."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE processing_tasks SET status='completed', progress=100, "
            "error_message='', failure_stage='', retryable=FALSE, "
            "outcome=COALESCE(NULLIF($2, ''), outcome), "
            "warning_message=COALESCE(NULLIF($3, ''), warning_message), "
            "completed_at=NOW(), updated_at=NOW() "
            "WHERE task_id=$1 AND status <> 'cancelling'",
            task_id, outcome, warning,
        )


async def _pg_fail_task(
    task_id: str, error: str, *, outcome: str = "", warning: str = "",
    failure_stage: str = "", retryable: bool | None = None,
) -> None:
    """Atomically finalize a task while preserving progress/phase/message."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE processing_tasks SET status='failed', error_message=$2, "
            "outcome=COALESCE(NULLIF($3, ''), outcome), "
            "warning_message=COALESCE(NULLIF($4, ''), warning_message), "
            "failure_stage=COALESCE(NULLIF($5, ''), failure_stage), "
            "retryable=COALESCE($6, retryable), "
            "completed_at=NOW(), updated_at=NOW() "
            "WHERE task_id=$1 AND status <> 'cancelling'",
            task_id, error, outcome, warning, failure_stage, retryable,
        )


async def _pg_defer_task(task_id: str, error: str, *, failure_stage: str) -> None:
    """Persist a recoverable non-terminal task state without losing progress."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE processing_tasks SET status='retry_wait', error_message=$2, "
            "failure_stage=$3, retryable=TRUE, completed_at=NULL, updated_at=NOW() "
            "WHERE task_id=$1 AND status NOT IN ('completed', 'failed')",
            task_id,
            error,
            failure_stage,
        )


async def _pg_delete_task(task_id: str):
    """Delete task from PG."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM processing_tasks WHERE task_id=$1", task_id)


async def _pg_update_task_progress(task_id: str, progress: int, message: str = "",
                                   phase: str = "", phase_status: str = "") -> None:
    """Update task progress/phase fields in PG without touching other columns."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE processing_tasks SET progress=$2, "
            "message=CASE WHEN $3 <> '' THEN $3 ELSE message END, "
            "phase=CASE WHEN $4 <> '' THEN $4 ELSE phase END, "
            "phase_status=CASE WHEN $5 <> '' THEN $5 ELSE phase_status END, "
            "updated_at=NOW() WHERE task_id=$1 "
            "AND status NOT IN ('completed', 'failed', 'cancelling')",
            task_id, progress, message, phase, phase_status,
        )


# ═══════════════════════════════════════════════════════════════
# Public task state API
# ═══════════════════════════════════════════════════════════════

async def upsert_task_state(task_id: str, task_data: dict) -> None:
    """Create or update a processing task — PG + local cache.

    Args:
        task_id: Task identifier
        task_data: Dict with keys: kb/kb_name, file/file_name, file_hash,
                   user_id, status, progress, phase, phase_status,
                   chunking_strategy, error, message
    """
    task_data["id"] = task_id
    async with _get_task_lock():
        processing_tasks[task_id] = task_data
    if _task_pg_ready():
        await _pg_upsert_task(task_id, task_data)


async def complete_task(
    task_id: str, *, outcome: str = "", warning: str = "",
    warning_message: str | None = None,
) -> None:
    """Mark task completed — PG + local cache."""
    effective_warning = warning if warning_message is None else warning_message
    async with _get_task_lock():
        if task_id in processing_tasks and processing_tasks[task_id].get("status") != "cancelling":
            task = processing_tasks[task_id]
            task["status"] = "completed"
            task["progress"] = 100
            task["error"] = ""
            task["error_message"] = ""
            task["failure_stage"] = ""
            task["retryable"] = False
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            if outcome:
                task["outcome"] = outcome
            if effective_warning:
                task["warning"] = effective_warning
                task["warning_message"] = effective_warning
    if _task_pg_ready():
        await _pg_complete_task(task_id, outcome=outcome, warning=effective_warning)


async def fail_task(
    task_id: str,
    error: str,
    *,
    outcome: str = "",
    warning: str = "",
    warning_message: str | None = None,
    failure_stage: str = "",
    retryable: bool | None = None,
) -> None:
    """Atomically mark a task failed without resetting progress or phase fields."""
    effective_warning = warning if warning_message is None else warning_message
    async with _get_task_lock():
        task = processing_tasks.setdefault(task_id, {"id": task_id})
        if task.get("status") == "cancelling":
            return
        task["status"] = "failed"
        task["error"] = error
        task["error_message"] = error
        task["completed_at"] = datetime.now(timezone.utc).isoformat()
        if outcome:
            task["outcome"] = outcome
        if effective_warning:
            task["warning"] = effective_warning
            task["warning_message"] = effective_warning
        if failure_stage:
            task["failure_stage"] = failure_stage
        if retryable is not None:
            task["retryable"] = retryable
    if _task_pg_ready():
        await _pg_fail_task(
            task_id,
            error,
            outcome=outcome,
            warning=effective_warning,
            failure_stage=failure_stage,
            retryable=retryable,
        )


async def defer_task(task_id: str, error: str, *, failure_stage: str) -> None:
    """Keep a task recoverable while a durable downstream job is unavailable."""
    async with _get_task_lock():
        task = processing_tasks.setdefault(task_id, {"id": task_id})
        if task.get("status") not in {"completed", "failed", "cancelling"}:
            task.update({
                "status": "retry_wait",
                "error": error,
                "error_message": error,
                "failure_stage": failure_stage,
                "retryable": True,
            })
            task.pop("completed_at", None)
    if _task_pg_ready():
        await _pg_defer_task(task_id, error, failure_stage=failure_stage)


async def delete_task(task_id: str) -> None:
    """Remove task — PG + local cache."""
    async with _get_task_lock():
        processing_tasks.pop(task_id, None)
    if _task_pg_ready():
        await _pg_delete_task(task_id)


async def update_task_progress(task_id: str, progress: int, message: str = "",
                               phase: str = "", phase_status: str = "") -> None:
    """Update progress/phase of a task — PG + local cache.

    This is the canonical function for real-time progress updates. It replaces
    direct ``processing_tasks[task_id]["progress"] = N`` patterns.

    Args:
        task_id: Task identifier
        progress: Progress percentage (0-100)
        message: Human-readable status message
        phase: Current processing phase (parsing|chunking|embedding|graph)
        phase_status: Phase-specific status detail
    """
    async with _get_task_lock():
        task = processing_tasks.get(task_id)
        if task is not None and task.get("status") not in {"completed", "failed", "cancelling"}:
            task["progress"] = progress
            if message:
                task["message"] = message
            if phase:
                task["phase"] = phase
            if phase_status:
                task["phase_status"] = phase_status
    if _task_pg_ready():
        await _pg_update_task_progress(task_id, progress, message, phase, phase_status)


async def get_task_status(task_id: str) -> dict[str, Any] | None:
    """Get the status of a processing task — PG-first, local cache fallback.

    Args:
        task_id: Task identifier

    Returns:
        Task status dict or None if not found
    """
    if _task_pg_ready():
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM processing_tasks WHERE task_id=$1", task_id
            )
            if row:
                d = dict(row)
                # Normalize column names to match legacy dict keys
                d.setdefault("id", d.get("task_id", task_id))
                d.setdefault("file", d.get("file_name", ""))
                d.setdefault("kb", d.get("kb_name", "default"))
                d.setdefault("error", d.get("error_message", ""))
                d.setdefault("warning", d.get("warning_message", ""))
                return d
    return processing_tasks.get(task_id)


async def get_all_tasks() -> list[dict[str, Any]]:
    """Get all active processing tasks — PG-first, local cache fallback.

    Returns:
        List of task status dicts, newest first
    """
    if _task_pg_ready():
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM processing_tasks "
                "WHERE status NOT IN ('completed','failed') "
                "ORDER BY updated_at DESC"
            )
            if rows:
                result = []
                for r in rows:
                    d = dict(r)
                    d.setdefault("id", d.get("task_id", ""))
                    d.setdefault("file", d.get("file_name", ""))
                    d.setdefault("kb", d.get("kb_name", "default"))
                    d.setdefault("error", d.get("error_message", ""))
                    d.setdefault("warning", d.get("warning_message", ""))
                    result.append(d)
                # Also sync to local cache
                async with _get_task_lock():
                    for d in result:
                        tid = d.get("id") or d.get("task_id", "")
                        if tid and tid not in processing_tasks:
                            processing_tasks[tid] = d
                return result

    # Fallback: local cache
    return sorted(
        processing_tasks.values(),
        key=lambda t: t.get("started_at", ""),
        reverse=True,
    )


async def cleanup_completed_tasks() -> None:
    """Remove completed/failed tasks from PG (and local cache)."""
    if _task_pg_ready():
        from raganything.services.pg_state_repo import get_pg_pool
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM processing_tasks WHERE status IN ('completed','failed')"
            )
    async with _get_task_lock():
        to_remove = []
        for task_id, task in processing_tasks.items():
            if task.get("status") in ("completed", "failed"):
                to_remove.append(task_id)
        for task_id in to_remove:
            del processing_tasks[task_id]
        if to_remove:
            state_logger.info(f"Cleaned up {len(to_remove)} completed/failed task records")


async def load_tasks_from_pg() -> list[dict]:
    """Load active (non-terminal) tasks from PG for crash recovery.

    Also populates the ``processing_tasks`` dict cache.
    """
    if not _task_pg_ready():
        return []
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM processing_tasks "
            "WHERE status NOT IN ('completed','failed') "
            "ORDER BY updated_at DESC"
        )
    result = []
    async with _get_task_lock():
        for r in rows:
            d = dict(r)
            tid = d.get("task_id", "")
            d.setdefault("id", tid)
            d.setdefault("file", d.get("file_name", ""))
            d.setdefault("kb", d.get("kb_name", "default"))
            d.setdefault("error", d.get("error_message", ""))
            d.setdefault("warning", d.get("warning_message", ""))
            # Normalize timestamp fields
            for ts_field in ("started_at", "updated_at", "completed_at"):
                val = d.get(ts_field)
                if isinstance(val, datetime):
                    d[ts_field] = val.isoformat()
            processing_tasks[tid] = d
            result.append(d)
    state_logger.info(f"Loaded {len(result)} active tasks from PG")
    return result


# ═══════════════════════════════════════════════════════════════
# Query History — PG-backed only
# ═══════════════════════════════════════════════════════════════

async def record_query(entry: dict, max_history: int = 1000):
    """Record a query result to PG ``query_history`` table.

    Args:
        entry: Query record dict with keys: id, query, answer, elapsed, kb,
               mode, agent_mode, time, user_id, username, reasoning_trace,
               images, agent_id, thread_id, fallback
        max_history: Ignored (PG pruning via ``prune_query_history``).
    """
    if not _task_pg_ready():
        state_logger.warning("PG unavailable — query not recorded")
        return

    from raganything.services.pg_state_repo import (
        insert_query_history, prune_query_history
    )
    await insert_query_history(entry)
    # Prune to keep the table bounded
    await prune_query_history(max_history)


async def get_query_history(limit: int = 50, user_id: int = None) -> list[dict]:
    """Get recent query history from PG.

    Args:
        limit: Maximum number of records to return
        user_id: Optional user filter

    Returns:
        List of recent query records (most recent first)
    """
    if not _task_pg_ready():
        return []

    from raganything.services.pg_state_repo import get_query_history as _pg_get_history
    return await _pg_get_history(limit=limit, user_id=user_id)


# ═══════════════════════════════════════════════════════════════
# Deprecated — kept for backward-compat imports
# ═══════════════════════════════════════════════════════════════

QUERY_HISTORY_FILE = None  # type: ignore
"""Deprecated.  Query history is now PG-backed.  This attribute is kept
only to prevent ``ImportError`` in modules that still reference it.
"""


def load_query_history() -> None:
    """Deprecated.  Query history is loaded from PG at startup.

    Kept for backward-compat with ``server.py`` imports.
    """
    state_logger.info("Query history: PG backend (load_query_history is a no-op)")


def save_query_history() -> None:
    """Deprecated.  Query history is persisted to PG on every write.

    Kept for backward-compat with ``server.py`` imports.
    """


__all__ = [
    "processing_tasks",
    "query_history",
    "QUERY_HISTORY_FILE",
    "load_query_history",
    "save_query_history",
    "record_query",
    "get_query_history",
    "get_task_status",
    "get_all_tasks",
    "cleanup_completed_tasks",
    "upsert_task_state",
    "complete_task",
    "fail_task",
    "defer_task",
    "delete_task",
    "update_task_progress",
    "load_tasks_from_pg",
]
