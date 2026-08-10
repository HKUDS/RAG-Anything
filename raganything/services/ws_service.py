# -*- coding: utf-8 -*-
"""
RAG-Anything WebSocket Service.

Layer: Service
Primary Responsibility: WebSocket connection tracking, broadcasting,
    progress emission, event logging.
Key Dependencies: fastapi (WebSocket), asyncio

Extracted from routers/shared.py. All WebSocket management is centralized here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket

ws_logger = logging.getLogger("rag_server.ws")

# ── WebSocket State ────────────────────────────────────────

ws_clients: list[WebSocket] = []
"""All connected WebSocket clients for general broadcast."""

active_ws_connections: dict[str, list] = {}
"""Per-run WebSocket connections: run_id → [ws1, ws2, ...]."""

_ws_sessions: dict[WebSocket, dict[str, Any]] = {}
"""Authenticated account session snapshot for each connected WebSocket."""

_event_lock = asyncio.Lock()
"""Lock for thread-safe event list mutation."""

processing_events: list[dict] = []
"""In-memory event log (max 200 entries)."""


# ── Broadcast ──────────────────────────────────────────────

def _event_pg_ready() -> bool:
    """Return whether the PG pool is ready for monitor-event persistence."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False

async def ws_broadcast(data: dict[str, Any]) -> None:
    """Broadcast a JSON message to all connected WebSocket clients.

    Dead connections are automatically removed.

    Args:
        data: JSON-serializable dict to broadcast
    """
    dead = []
    for ws in ws_clients:
        try:
            if not await _session_is_current(_ws_sessions.get(ws, {})):
                await ws.close(code=4001, reason="Account session is no longer valid")
                dead.append(ws)
                continue
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)
        _ws_sessions.pop(ws, None)


async def push_run_status(
    run_id: str, node_id: str | None, status: str, data: dict[str, Any] | None = None,
) -> None:
    """Push workflow execution status to all subscribers of a run.

    Args:
        run_id: Workflow run identifier
        node_id: Current node ID (None for run-level events)
        status: Status string
        data: Optional additional payload
    """
    msg = {
        "type": "node_status" if node_id else "run_complete",
        "run_id": run_id,
        "status": status,
    }
    if node_id:
        msg["node_id"] = node_id
    if data:
        msg["data"] = data
    for ws in active_ws_connections.get(run_id, []):
        try:
            if not await _session_is_current(_ws_sessions.get(ws, {})):
                await ws.close(code=4001, reason="Account session is no longer valid")
                continue
            await ws.send_json(msg)
        except Exception:
            pass


async def _session_is_current(session: dict[str, Any]) -> bool:
    """Fail closed before delivering a WS event to an existing connection."""
    user_id = session.get("id")
    if not user_id:
        return False
    try:
        from raganything.services.auth import get_user_by_id, is_token_revoked

        jti = session.get("token_jti")
        if jti and await is_token_revoked(jti):
            return False
        account = await get_user_by_id(user_id)
        return bool(
            account and account.get("is_active") and account.get("archived_at") is None
            and int(account.get("session_generation", 0)) == int(session.get("session_generation"))
        )
    except (TypeError, ValueError):
        return False
    except Exception:
        return False


# ── Progress ───────────────────────────────────────────────

async def emit_progress(task_id: str, progress: int, msg: str = "") -> None:
    """Emit a progress update for a processing task.

    Updates PG + local cache via ``update_task_progress()`` and broadcasts
    to all WS clients.

    Args:
        task_id: Processing task identifier
        progress: Progress percentage (0-100)
        msg: Human-readable progress message
    """
    from raganything.services.state_service import update_task_progress

    await update_task_progress(task_id, progress, message=msg)
    await ws_broadcast({
        "type": "progress",
        "task_id": task_id,
        "progress": progress,
        "message": msg,
    })


# ── Events ─────────────────────────────────────────────────

async def load_persisted_monitor_events(limit: int = 200) -> int:
    """Warm the in-memory event window from persistent storage."""
    global processing_events
    if not _event_pg_ready():
        return len(processing_events)

    try:
        from raganything.services.pg_state_repo import get_monitor_events as _pg_get_monitor_events
        events = await _pg_get_monitor_events(limit=limit)
    except Exception as exc:
        ws_logger.warning("Failed to load persisted monitor events: %s", exc)
        return len(processing_events)

    async with _event_lock:
        processing_events[:] = events[-limit:]
        return len(processing_events)


async def get_monitor_events(
    limit: int = 50,
    *,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """Get recent monitor events from PG, falling back to memory if needed."""
    if limit <= 0:
        return []

    if _event_pg_ready():
        try:
            from raganything.services.pg_state_repo import get_monitor_events as _pg_get_monitor_events
            if is_admin:
                return await _pg_get_monitor_events(limit=limit)
            return await _pg_get_monitor_events(limit=limit, user_id=user_id, include_global=True)
        except Exception as exc:
            ws_logger.warning("Failed to query persisted monitor events: %s", exc)

    async with _event_lock:
        if is_admin or user_id is None:
            return processing_events[-limit:]
        visible = [
            current_event for current_event in processing_events
            if current_event.get("user_id", 0) in (0, user_id)
        ]
        return visible[-limit:]

async def add_event(event: str, user_id: int = 0, **kw: Any) -> None:
    """Add a processing event to the in-memory log.

    Maintains a rolling window of 200 events.

    Args:
        event: Event name
        user_id: Associated user ID
        **kw: Additional event fields
    """
    global processing_events
    e = {
        "time": datetime.now().astimezone().isoformat(),
        "event": event,
        "user_id": user_id,
        **kw,
    }
    async with _event_lock:
        processing_events.append(e)
        if len(processing_events) > 200:
            processing_events[:] = processing_events[-200:]
    if _event_pg_ready():
        try:
            from raganything.services.pg_state_repo import insert_monitor_event
            await insert_monitor_event(e)
        except Exception as exc:
            ws_logger.warning("Failed to persist monitor event %s: %s", event, exc)


# ── Connection Management ──────────────────────────────────

def register_ws(run_id: str, ws: WebSocket, session: dict[str, Any] | None = None):
    """Register a WebSocket connection for a workflow run.

    Args:
        run_id: Workflow run identifier
        ws: WebSocket connection
    """
    if run_id not in active_ws_connections:
        active_ws_connections[run_id] = []
    active_ws_connections[run_id].append(ws)
    if session is not None:
        _ws_sessions[ws] = dict(session)


def register_general_ws(ws: WebSocket, session: dict[str, Any]) -> None:
    """Register a general WebSocket together with its validated session."""
    ws_clients.append(ws)
    _ws_sessions[ws] = dict(session)


def unregister_ws(run_id: str, ws: WebSocket):
    """Unregister a WebSocket connection from a workflow run.

    Args:
        run_id: Workflow run identifier
        ws: WebSocket connection to remove
    """
    if run_id in active_ws_connections:
        try:
            active_ws_connections[run_id].remove(ws)
        except ValueError:
            pass
        if not active_ws_connections[run_id]:
            del active_ws_connections[run_id]
    _ws_sessions.pop(ws, None)


def unregister_general_ws(ws: WebSocket) -> None:
    """Remove a general WebSocket and its authentication snapshot."""
    if ws in ws_clients:
        ws_clients.remove(ws)
    _ws_sessions.pop(ws, None)


__all__ = [
    "ws_clients",
    "active_ws_connections",
    "processing_events",
    "ws_broadcast",
    "push_run_status",
    "emit_progress",
    "load_persisted_monitor_events",
    "get_monitor_events",
    "add_event",
    "register_ws",
    "unregister_ws",
    "register_general_ws",
    "unregister_general_ws",
]
