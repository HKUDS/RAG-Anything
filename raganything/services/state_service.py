# -*- coding: utf-8 -*-
"""
RAG-Anything In-Memory State Service.

Layer: Service
Primary Responsibility: Thread-safe in-memory state management —
    processing task status, query history, conversation manager reference.
Key Dependencies: stdlib (json, asyncio, pathlib)

Extracted from routers/shared.py. All server-level mutable state is centralized here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

state_logger = logging.getLogger("rag_server.state")

# ── State ──────────────────────────────────────────────────

processing_tasks: dict[str, dict] = {}
"""In-flight document processing tasks: task_id → {id, file, status, progress, ...}."""

query_history: list[dict] = []
"""Query history records: [{query, answer, elapsed, kb, mode, time, user_id}, ...]."""

conversation_manager: Optional[object] = None
"""ConversationManager singleton for agent chat sessions."""

QUERY_HISTORY_FILE = Path("./query_history.json")
"""Persistence file for query history."""

# ── Concurrency Guards ────────────────────────────────────

_query_lock: asyncio.Lock | None = None
"""Lock for query_history mutations (lazily initialized per event loop)."""

_task_lock: asyncio.Lock | None = None
"""Lock for processing_tasks mutations (lazily initialized per event loop)."""


def _get_query_lock() -> asyncio.Lock:
    """Return the query-history lock, creating it lazily per event loop."""
    global _query_lock
    if _query_lock is None:
        _query_lock = asyncio.Lock()
    return _query_lock


def _get_task_lock() -> asyncio.Lock:
    """Return the task-state lock, creating it lazily per event loop."""
    global _task_lock
    if _task_lock is None:
        _task_lock = asyncio.Lock()
    return _task_lock


# ── Query History Persistence ──────────────────────────────

def load_query_history() -> None:
    """Load query history from JSON file into memory."""
    global query_history
    try:
        if QUERY_HISTORY_FILE.exists():
            data = json.loads(QUERY_HISTORY_FILE.read_text(encoding="utf-8"))
            query_history = data if isinstance(data, list) else []
            state_logger.info(f"Loaded {len(query_history)} query history records")
    except Exception as e:
        state_logger.warning(f"Failed to load query history: {e}")
        query_history = []


async def _save_query_history_internal() -> None:
    """Persist query history to JSON file atomically (tmp + replace).

    Runs file I/O in a thread-pool executor to avoid blocking the event loop.
    Must be called while holding ``_query_lock``.
    """
    loop = asyncio.get_running_loop()

    def _write() -> None:
        try:
            tmp = QUERY_HISTORY_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(query_history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(QUERY_HISTORY_FILE)
        except Exception as e:
            state_logger.warning(f"Failed to save query history: {e}")

    await loop.run_in_executor(None, _write)


def save_query_history() -> None:
    """Persist query history to JSON file atomically (tmp + replace).

    .. deprecated::
        Prefer ``record_query()`` which acquires the lock internally.
        Direct calls bypass the lock and risk concurrent-write corruption.
    """
    try:
        tmp = QUERY_HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(query_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(QUERY_HISTORY_FILE)
    except Exception as e:
        state_logger.warning(f"Failed to save query history: {e}")


async def record_query(entry: dict, max_history: int = 1000):
    """Record a query result and persist — async, lock-protected.

    Args:
        entry: Query record dict with keys: query, answer, elapsed, kb, mode, time, user_id
        max_history: Maximum entries to keep in memory and on disk (default 1000)
    """
    async with _get_query_lock():
        query_history.append(entry)
        # Keep max entries in memory
        if len(query_history) > max_history:
            query_history[:] = query_history[-max_history:]
        await _save_query_history_internal()


def get_query_history(limit: int = 50, user_id: int = None) -> list[dict]:
    """Get recent query history, optionally filtered by user.

    Args:
        limit: Maximum number of records to return
        user_id: Optional user filter

    Returns:
        List of recent query records (most recent first)
    """
    filtered = query_history
    if user_id is not None:
        filtered = [q for q in filtered if q.get("user_id") == user_id]
    return list(reversed(filtered[-limit:]))


# ── Task Status ────────────────────────────────────────────

def get_task_status(task_id: str) -> dict[str, Any] | None:
    """Get the status of a processing task.

    Args:
        task_id: Task identifier

    Returns:
        Task status dict or None if not found
    """
    return processing_tasks.get(task_id)


def get_all_tasks() -> list[dict[str, Any]]:
    """Get all processing tasks sorted by start time (newest first).

    Returns:
        List of task status dicts
    """
    return sorted(
        processing_tasks.values(),
        key=lambda t: t.get("started_at", ""),
        reverse=True,
    )


async def cleanup_completed_tasks():
    """Remove completed/failed tasks from memory — lock-protected.

    Once a task reaches a terminal state (completed/failed) its document
    status is persisted in kv_store_doc_status.json, so the in-memory
    processing_tasks entry is no longer needed.
    """
    async with _get_task_lock():
        to_remove = []
        for task_id, task in processing_tasks.items():
            if task.get("status") in ("completed", "failed"):
                try:
                    to_remove.append(task_id)
                except (ValueError, TypeError):
                    pass
        for task_id in to_remove:
            del processing_tasks[task_id]
        if to_remove:
            state_logger.info(f"Cleaned up {len(to_remove)} completed/failed task records")


# ── PG-backed Task State ────────────────────────────────────

def _task_pg_ready() -> bool:
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False


async def _pg_upsert_task(task_id: str, task_data: dict) -> None:
    """Write task state to PG (upsert)."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO processing_tasks
               (task_id, kb_name, file_name, file_hash, user_id,
                status, progress, phase, phase_status,
                chunking_strategy, error_message, message, started_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
               ON CONFLICT (task_id) DO UPDATE SET
                status=$6, progress=$7, phase=$8, phase_status=$9,
                chunking_strategy=$10, error_message=$11, message=$12,
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
        )


async def _pg_complete_task(task_id: str):
    """Mark task as completed in PG."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE processing_tasks SET status='completed', completed_at=NOW(), "
            "updated_at=NOW() WHERE task_id=$1",
            task_id,
        )


async def _pg_delete_task(task_id: str):
    """Delete task from PG."""
    from raganything.services.pg_state_repo import get_pg_pool
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM processing_tasks WHERE task_id=$1", task_id)


async def upsert_task_state(task_id: str, task_data: dict) -> None:
    """Update task state — memory dict + optional PG persistence."""
    async with _get_task_lock():
        task_data["id"] = task_id
        processing_tasks[task_id] = task_data
    if _task_pg_ready():
        try:
            await _pg_upsert_task(task_id, task_data)
        except Exception:
            pass  # PG write failure is non-fatal


async def complete_task(task_id: str) -> None:
    """Mark task completed — memory dict + optional PG."""
    async with _get_task_lock():
        if task_id in processing_tasks:
            processing_tasks[task_id]["status"] = "completed"
    if _task_pg_ready():
        try:
            await _pg_complete_task(task_id)
        except Exception:
            pass


async def delete_task(task_id: str) -> None:
    """Remove task — memory dict + optional PG."""
    async with _get_task_lock():
        processing_tasks.pop(task_id, None)
    if _task_pg_ready():
        try:
            await _pg_delete_task(task_id)
        except Exception:
            pass


async def load_tasks_from_pg() -> list[dict]:
    """Load active (non-terminal) tasks from PG for crash recovery."""
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
    return [dict(r) for r in rows]


__all__ = [
    "processing_tasks",
    "query_history",
    "conversation_manager",
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
    "delete_task",
    "load_tasks_from_pg",
]
