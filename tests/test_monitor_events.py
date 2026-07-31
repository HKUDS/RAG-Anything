from unittest.mock import AsyncMock
from datetime import datetime, timezone
import json

import pytest


@pytest.mark.asyncio
async def test_add_event_persists_when_pg_ready(monkeypatch):
    from raganything.services import ws_service

    original_events = list(ws_service.processing_events)
    persist_mock = AsyncMock()
    monkeypatch.setattr(ws_service, "_event_pg_ready", lambda: True)
    monkeypatch.setattr("raganything.services.pg_state_repo.insert_monitor_event", persist_mock)

    try:
        ws_service.processing_events[:] = []
        await ws_service.add_event("upload_start", user_id=7, file="alpha.docx")

        assert ws_service.processing_events[-1]["event"] == "upload_start"
        assert ws_service.processing_events[-1]["file"] == "alpha.docx"
        assert ws_service.processing_events[-1]["user_id"] == 7
        persist_mock.assert_awaited_once()
    finally:
        ws_service.processing_events[:] = original_events


@pytest.mark.asyncio
async def test_get_monitor_events_falls_back_to_memory_filter(monkeypatch):
    from raganything.services import ws_service

    original_events = list(ws_service.processing_events)
    monkeypatch.setattr(ws_service, "_event_pg_ready", lambda: False)

    try:
        ws_service.processing_events[:] = [
            {"time": "2026-07-09T10:28:00+08:00", "event": "system_boot", "user_id": 0},
            {"time": "2026-07-09T10:29:00+08:00", "event": "upload_start", "user_id": 3},
            {"time": "2026-07-09T10:30:00+08:00", "event": "upload_complete", "user_id": 7},
        ]

        result = await ws_service.get_monitor_events(limit=5, user_id=7, is_admin=False)

        assert [event["event"] for event in result] == ["system_boot", "upload_complete"]
    finally:
        ws_service.processing_events[:] = original_events


@pytest.mark.asyncio
async def test_load_persisted_monitor_events_rehydrates_memory(monkeypatch):
    from raganything.services import ws_service

    original_events = list(ws_service.processing_events)
    persisted = [
        {"time": "2026-07-09T10:29:41+08:00", "event": "upload_start", "user_id": 7},
        {"time": "2026-07-09T10:31:46+08:00", "event": "upload_complete", "user_id": 7},
    ]
    load_mock = AsyncMock(return_value=persisted)
    monkeypatch.setattr(ws_service, "_event_pg_ready", lambda: True)
    monkeypatch.setattr("raganything.services.pg_state_repo.get_monitor_events", load_mock)

    try:
        ws_service.processing_events[:] = []
        count = await ws_service.load_persisted_monitor_events(limit=2)

        assert count == 2
        assert ws_service.processing_events == persisted
        load_mock.assert_awaited_once_with(limit=2)
    finally:
        ws_service.processing_events[:] = original_events


@pytest.mark.asyncio
async def test_pg_insert_monitor_event_serializes_payload_and_prunes(monkeypatch):
    from raganything.services import pg_state_repo

    class FakeTransaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def __init__(self):
            self.execute_calls = []

        def transaction(self):
            return FakeTransaction()

        async def execute(self, sql, *params):
            self.execute_calls.append((sql, params))

    class FakeAcquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return FakeAcquire(self.conn)

    conn = FakeConn()
    monkeypatch.setattr(pg_state_repo, "_get_pool", lambda: FakePool(conn))

    await pg_state_repo.insert_monitor_event(
        {
            "time": "2026-07-09T10:31:46+08:00",
            "event": "upload_complete",
            "user_id": 7,
            "file": "alpha.docx",
            "task_id": "task-1",
        },
        max_rows=5000,
    )

    assert len(conn.execute_calls) == 2
    insert_sql, insert_params = conn.execute_calls[0]
    assert "INSERT INTO monitor_events" in insert_sql
    assert insert_params[1] == "upload_complete"
    assert insert_params[2] == 7
    payload = json.loads(insert_params[3])
    assert payload == {"file": "alpha.docx", "task_id": "task-1"}

    prune_sql, prune_params = conn.execute_calls[1]
    assert "DELETE FROM monitor_events" in prune_sql
    assert prune_params == (5000,)


@pytest.mark.asyncio
async def test_pg_get_monitor_events_merges_payload_in_chronological_order(monkeypatch):
    from raganything.services import pg_state_repo

    class FakeConn:
        def __init__(self):
            self.fetch_calls = []

        async def fetch(self, sql, *params):
            self.fetch_calls.append((sql, params))
            return [
                {
                    "created_at": datetime(2026, 7, 9, 10, 31, 46, tzinfo=timezone.utc),
                    "event": "upload_complete",
                    "user_id": 7,
                    "payload": {"file": "beta.docx"},
                },
                {
                    "created_at": datetime(2026, 7, 9, 10, 29, 41, tzinfo=timezone.utc),
                    "event": "upload_start",
                    "user_id": 0,
                    "payload": {"file": "alpha.docx"},
                },
            ]

    class FakeAcquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            return FakeAcquire(self.conn)

    conn = FakeConn()
    monkeypatch.setattr(pg_state_repo, "_get_pool", lambda: FakePool(conn))

    events = await pg_state_repo.get_monitor_events(limit=2, user_id=7, include_global=True)

    assert [event["event"] for event in events] == ["upload_start", "upload_complete"]
    assert events[0]["file"] == "alpha.docx"
    assert events[1]["file"] == "beta.docx"
    assert "WHERE user_id IN (0, $1)" in conn.fetch_calls[0][0]
    assert conn.fetch_calls[0][1] == (7, 2)
