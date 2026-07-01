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

_event_lock = asyncio.Lock()
"""Lock for thread-safe event list mutation."""

processing_events: list[dict] = []
"""In-memory event log (max 200 entries)."""


# ── Broadcast ──────────────────────────────────────────────

async def ws_broadcast(data: dict[str, Any]) -> None:
    """Broadcast a JSON message to all connected WebSocket clients.

    Dead connections are automatically removed.

    Args:
        data: JSON-serializable dict to broadcast
    """
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)


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
            await ws.send_json(msg)
        except Exception:
            pass


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

async def add_event(event: str, user_id: int = 0, **kw: Any) -> None:
    """Add a processing event to the in-memory log.

    Maintains a rolling window of 200 events.

    Args:
        event: Event name
        user_id: Associated user ID
        **kw: Additional event fields
    """
    global processing_events
    e = {"time": datetime.now().isoformat(), "event": event, "user_id": user_id, **kw}
    async with _event_lock:
        processing_events.append(e)
        if len(processing_events) > 200:
            processing_events[:] = processing_events[-200:]


# ── Connection Management ──────────────────────────────────

def register_ws(run_id: str, ws: WebSocket):
    """Register a WebSocket connection for a workflow run.

    Args:
        run_id: Workflow run identifier
        ws: WebSocket connection
    """
    if run_id not in active_ws_connections:
        active_ws_connections[run_id] = []
    active_ws_connections[run_id].append(ws)


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


__all__ = [
    "ws_clients",
    "active_ws_connections",
    "processing_events",
    "ws_broadcast",
    "push_run_status",
    "emit_progress",
    "add_event",
    "register_ws",
    "unregister_ws",
]
