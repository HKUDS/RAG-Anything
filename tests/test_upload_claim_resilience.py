"""Resilience contracts for upload claims, leases, and background loops
during a temporarily unreachable PostgreSQL (no live database)."""

from __future__ import annotations

import asyncio
import inspect
import logging

import pytest

from raganything.services import (
    document_tagging,
    kb_mutation,
    kb_service,
    pg_state_repo,
    upload_retry,
)


async def _async_value(value):
    return value


def _make_immediate_sleep(started: asyncio.Event):
    """Replace asyncio.sleep with an immediate gate that still yields.

    Awaiting an already-set asyncio.Event does not suspend the coroutine, so
    a bare gate would starve the event loop (timeouts and wakeups could never
    run).  Yielding through the original asyncio.sleep(0) keeps the heartbeat
    loop alive while letting waiters progress.
    """
    original_sleep = asyncio.sleep

    async def immediate_sleep(_seconds):
        await started.wait()
        await original_sleep(0)

    return immediate_sleep


@pytest.mark.asyncio
async def test_kb_mutation_heartbeat_survives_transient_db_failures(monkeypatch):
    started = asyncio.Event()
    heartbeat_runs = 0
    heartbeat_ran = asyncio.Event()

    async def operation():
        started.set()
        try:
            await asyncio.wait_for(heartbeat_ran.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
        return "done"

    async def flaky_heartbeat(*_args, **_kwargs):
        nonlocal heartbeat_runs
        heartbeat_runs += 1
        if heartbeat_runs <= 2:
            raise ConnectionResetError("WinError 64")
        heartbeat_ran.set()
        return True

    monkeypatch.setattr(
        kb_mutation, "acquire_kb_mutation_lease",
        lambda *_a, **_k: _async_value("lease-1"),
    )
    monkeypatch.setattr(
        kb_mutation.asyncio, "sleep", _make_immediate_sleep(started)
    )
    monkeypatch.setattr(kb_mutation, "heartbeat_kb_mutation_lease", flaky_heartbeat)
    monkeypatch.setattr(
        kb_mutation, "release_kb_mutation_lease",
        lambda *_a, **_k: _async_value(None),
    )

    result = await kb_mutation.run_kb_mutation_with_lease(
        "demo", "task-1", operation, mutation_kind="content"
    )
    assert result == "done"
    assert heartbeat_runs >= 3


@pytest.mark.asyncio
async def test_kb_mutation_heartbeat_cancels_after_grace_period_exhausted(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def failing_heartbeat(*_args, **_kwargs):
        raise ConnectionResetError("WinError 64")

    monkeypatch.setattr(
        kb_mutation, "acquire_kb_mutation_lease",
        lambda *_a, **_k: _async_value("lease-1"),
    )
    monkeypatch.setattr(
        kb_mutation.asyncio, "sleep", _make_immediate_sleep(started)
    )
    monkeypatch.setattr(kb_mutation, "heartbeat_kb_mutation_lease", failing_heartbeat)
    monkeypatch.setattr(
        kb_mutation, "release_kb_mutation_lease",
        lambda *_a, **_k: _async_value(None),
    )

    with pytest.raises(RuntimeError, match="kb_mutation_lease_lost"):
        await kb_mutation.run_kb_mutation_with_lease(
            "demo", "task-1", operation, mutation_kind="content"
        )
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_kb_mutation_heartbeat_lost_lease_cancels_immediately(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    heartbeat_calls = 0

    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def lost_heartbeat(*_args, **_kwargs):
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        return False

    monkeypatch.setattr(
        kb_mutation, "acquire_kb_mutation_lease",
        lambda *_a, **_k: _async_value("lease-1"),
    )
    monkeypatch.setattr(
        kb_mutation.asyncio, "sleep", _make_immediate_sleep(started)
    )
    monkeypatch.setattr(kb_mutation, "heartbeat_kb_mutation_lease", lost_heartbeat)
    monkeypatch.setattr(
        kb_mutation, "release_kb_mutation_lease",
        lambda *_a, **_k: _async_value(None),
    )

    with pytest.raises(RuntimeError, match="kb_mutation_lease_lost"):
        await kb_mutation.run_kb_mutation_with_lease(
            "demo", "task-1", operation, mutation_kind="content"
        )
    assert cancelled.is_set()
    assert heartbeat_calls == 1


def test_is_transient_upload_failure_classifies_errors():
    assert kb_service._is_transient_upload_failure(RuntimeError("upload_claim_lost"))
    assert kb_service._is_transient_upload_failure(RuntimeError("kb_mutation_lease_lost"))
    assert kb_service._is_transient_upload_failure(ConnectionResetError("WinError 64"))
    assert kb_service._is_transient_upload_failure(OSError(64, "network name"))

    for error_type in (
        pg_state_repo.asyncpg.exceptions.ConnectionDoesNotExistError,
        pg_state_repo.asyncpg.exceptions.CannotConnectNowError,
        pg_state_repo.asyncpg.exceptions.ConnectionFailureError,
    ):
        assert kb_service._is_transient_upload_failure(error_type("closed"))

    assert not kb_service._is_transient_upload_failure(ValueError("boom"))
    assert not kb_service._is_transient_upload_failure(RuntimeError("settings_snapshot_invalid"))


@pytest.mark.asyncio
async def test_recover_transient_upload_failure_schedules_retry(monkeypatch):
    calls = []

    async def fake_schedule(**kwargs):
        calls.append(kwargs)
        return {"status": "retry_wait", "next_attempt_at": None}

    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(
        "raganything.services.upload_retry.schedule_upload_retry", fake_schedule
    )

    await kb_service._recover_transient_upload_failure(
        {
            "task_id": "task-9", "kb_name": "demo", "file_path": "C:/tmp/a.mp4",
            "filename": "a.mp4", "user_id": 7, "chunking_strategy": "fixed_size",
        },
        {"file_hash": "hash-1"},
        "owner-a",
        4,
        RuntimeError("upload_claim_lost"),
    )

    assert len(calls) == 1
    assert calls[0]["task_id"] == "task-9"
    assert calls[0]["kb_name"] == "demo"
    assert calls[0]["stage"] == "claim_lost"
    assert calls[0]["root_type"] == "ClaimLost"
    assert calls[0]["file_hash"] == "hash-1"
    assert calls[0]["claim_owner"] == "owner-a"
    assert calls[0]["claim_generation"] == 4


@pytest.mark.asyncio
async def test_recover_transient_upload_failure_stops_zombie_worker(monkeypatch):
    stopped = []

    class FakeProc:
        returncode = None

    proc = FakeProc()

    async def fake_stop(target, task_id):
        stopped.append((target, task_id))
        target.returncode = 0

    async def fake_schedule(**kwargs):
        return None

    monkeypatch.setattr(kb_service, "_stop_cancelled_upload_worker", fake_stop)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {"demo": [(proc, "task-9")]})
    monkeypatch.setattr(
        "raganything.services.upload_retry.schedule_upload_retry", fake_schedule
    )

    await kb_service._recover_transient_upload_failure(
        {
            "task_id": "task-9", "kb_name": "demo", "file_path": "C:/tmp/a.mp4",
            "filename": "a.mp4", "user_id": 7, "chunking_strategy": "",
        },
        None,
        "owner-a",
        4,
        RuntimeError("upload_claim_lost"),
    )

    assert stopped == [(proc, "task-9")]
    assert kb_service._kb_worker_procs["demo"] == []


@pytest.mark.asyncio
async def test_recover_transient_upload_failure_swallows_scheduling_errors(monkeypatch):
    async def fake_schedule(**kwargs):
        raise ConnectionResetError("WinError 64")

    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(
        "raganything.services.upload_retry.schedule_upload_retry", fake_schedule
    )

    await kb_service._recover_transient_upload_failure(
        {
            "task_id": "task-1", "kb_name": "demo", "file_path": "x",
            "filename": "x.mp4", "user_id": 1, "chunking_strategy": "",
        },
        None,
        "owner-a",
        3,
        RuntimeError("upload_claim_lost"),
    )


@pytest.mark.asyncio
async def test_stop_cancelled_upload_worker_terminates_then_waits(monkeypatch):
    calls = []

    class FakeProc:
        returncode = None

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

        async def wait(self):
            calls.append("wait")
            self.returncode = 0

    proc = FakeProc()
    assert await kb_service._stop_cancelled_upload_worker(proc, "task-1") is True
    assert calls == ["terminate", "wait"]


@pytest.mark.asyncio
async def test_upload_cancellation_kills_worker_subprocess(monkeypatch):
    stopped = []
    created = []

    class FakeProc:
        def __init__(self):
            self.returncode = None
            self.stdout = None
            self.stderr = None

    async def fake_stop(target, task_id):
        stopped.append((target, task_id))
        target.returncode = 0

    async def fake_create_subprocess(*_args, **_kwargs):
        proc = FakeProc()
        created.append(proc)
        return proc

    async def fake_watchdog(*_args, **_kwargs):
        raise asyncio.CancelledError()

    async def fake_settings_snapshot(_task_id):
        return {
            "settings": {"ingestion": {"chunking_strategy": "fixed_size"}},
            "revision": 1,
            "fingerprint": "fp",
        }

    async def fake_pg_status(*_args, **_kwargs):
        return {"id": 1}

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kb_service, "_upload_is_cancelling", _noop)
    monkeypatch.setattr(
        "raganything.services.user_settings.get_task_settings_snapshot",
        fake_settings_snapshot,
    )
    monkeypatch.setattr("raganything.services.state_service.upsert_task_state", _noop)
    monkeypatch.setattr("raganything.services.ws_service.add_event", _noop)
    monkeypatch.setattr(kb_service, "_compute_file_hash", lambda _p: "hash-1")
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_a, **_k: None)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", fake_pg_status)
    monkeypatch.setattr(kb_service, "_cleanup_retry_document_residue", _noop)
    monkeypatch.setattr(kb_service, "_get_ocr_worker_slot", lambda: asyncio.Semaphore(1))
    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", fake_create_subprocess)
    monkeypatch.setattr(kb_service, "_worker_subprocess_env", lambda: {})
    monkeypatch.setattr(kb_service, "_worker_watchdog_config", lambda: (60.0, 3600.0))
    monkeypatch.setattr(kb_service, "_wait_for_worker_with_watchdog", fake_watchdog)
    monkeypatch.setattr(kb_service, "_stop_cancelled_upload_worker", fake_stop)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {"demo": []})

    with pytest.raises(asyncio.CancelledError):
        await kb_service._process_uploaded_file(
            task_id="task-cancel",
            file_path="C:/tmp/a.mp4",
            filename="a.mp4",
            kb_name="demo",
            chunking_strategy="fixed_size",
            user_id=1,
        )

    assert len(created) == 1
    assert stopped == [(created[0], "task-cancel")]
    assert kb_service._kb_worker_procs["demo"] == []


@pytest.mark.asyncio
async def test_init_pg_pool_passes_asyncpg_compatible_kwargs(monkeypatch):
    captured = {}

    class FakeConn:
        async def fetchval(self, _query, *_args):
            return 3

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *_args):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return FakePool()

    monkeypatch.setattr(pg_state_repo, "_pool", None)
    monkeypatch.setattr(pg_state_repo.asyncpg, "create_pool", fake_create_pool)

    pool = await pg_state_repo.init_pg_pool(dsn="postgresql://u:p@localhost:5432/db")

    assert isinstance(pool, FakePool)
    assert captured["timeout"] == 10
    assert captured["command_timeout"] == 30
    assert captured["max_inactive_connection_lifetime"] == 300
    assert "connection_timeout" not in captured
    assert "tcp_keepalive" not in captured

    pool_only_kwargs = {
        "min_size",
        "max_size",
        "max_inactive_connection_lifetime",
    }
    connect_kwargs = {
        key: value
        for key, value in captured.items()
        if key not in pool_only_kwargs
    }
    inspect.signature(pg_state_repo.asyncpg.connect).bind(**connect_kwargs)


@pytest.mark.asyncio
async def test_init_pg_pool_retries_when_pg_unavailable(monkeypatch):
    attempts = []
    sleeps = []

    class FakeConn:
        async def fetchval(self, _query, *_args):
            return 3

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *_args):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def flaky_create_pool(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionRefusedError("pg not up yet")
        return FakePool()

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(pg_state_repo, "_pool", None)
    monkeypatch.setattr(pg_state_repo.asyncpg, "create_pool", flaky_create_pool)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    pool = await pg_state_repo.init_pg_pool(dsn="postgresql://u:p@localhost:5432/db")

    assert isinstance(pool, FakePool)
    assert len(attempts) == 3
    assert sleeps == [5, 5]


@pytest.mark.asyncio
async def test_init_pg_pool_raises_after_retries_exhausted(monkeypatch):
    async def always_fail_create_pool(**kwargs):
        raise ConnectionRefusedError("pg down")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(pg_state_repo, "_pool", None)
    monkeypatch.setattr(pg_state_repo.asyncpg, "create_pool", always_fail_create_pool)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(ConnectionRefusedError):
        await pg_state_repo.init_pg_pool(dsn="postgresql://u:p@localhost:5432/db")


@pytest.mark.asyncio
async def test_durable_upload_queue_loop_backs_off_on_failure(monkeypatch):
    sleeps = []

    async def failing_resume():
        raise ConnectionResetError("WinError 64")

    async def recording_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(kb_service, "resume_queued_upload_tasks", failing_resume)
    monkeypatch.setattr(kb_service.asyncio, "sleep", recording_sleep)

    with pytest.raises(asyncio.CancelledError):
        await kb_service.durable_upload_queue_loop(interval_seconds=5.0)
    assert sleeps == [5.0, 10.0]


@pytest.mark.asyncio
async def test_retry_loop_backs_off_on_failure(monkeypatch):
    waits = []

    async def failing_claim():
        raise ConnectionResetError("WinError 64")

    async def recording_wait_for(_awaitable, *, timeout):
        if inspect.iscoroutine(_awaitable):
            _awaitable.close()
        waits.append(timeout)
        if len(waits) >= 3:
            raise asyncio.CancelledError()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(upload_retry, "_stop_event", asyncio.Event())
    monkeypatch.setattr(upload_retry, "claim_due_retry", failing_claim)
    monkeypatch.setattr(upload_retry.asyncio, "wait_for", recording_wait_for)
    monkeypatch.setattr(
        logging.Logger, "exception",
        lambda self, *_args, **_kwargs: None,
    )

    with pytest.raises(asyncio.CancelledError):
        await upload_retry._retry_loop()
    assert waits == [2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_tagging_loop_backs_off_on_claim_failure(monkeypatch):
    sleeps = []

    async def recording_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError()

    async def failing_claim():
        raise ConnectionResetError("WinError 64")

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(document_tagging, "ensure_document_tag_jobs_table", _noop)
    monkeypatch.setattr(document_tagging, "reconcile_terminal_tag_uploads", _noop)
    monkeypatch.setattr(
        "raganything.services.auto_tagging.automatic_tagging_enabled", lambda: True
    )
    monkeypatch.setattr(
        document_tagging, "cleanup_deleted_document_tag_assignments", _noop
    )
    monkeypatch.setattr(document_tagging, "reconcile_missing_document_tags", _noop)
    monkeypatch.setattr(document_tagging, "claim_due_tag_job", failing_claim)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", recording_sleep)

    with pytest.raises(asyncio.CancelledError):
        await document_tagging.document_tagging_loop(interval_seconds=3)
    assert sleeps == [3.0, 6.0, 12.0]


@pytest.mark.asyncio
async def test_tagging_loop_backs_off_on_terminal_reconciliation_failure(monkeypatch):
    sleeps = []
    reconcile_calls = 0

    async def recording_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError()

    async def flaky_reconcile(*_args, **_kwargs):
        nonlocal reconcile_calls
        reconcile_calls += 1
        if reconcile_calls <= 2:
            raise ConnectionResetError("WinError 64")
        return 0

    async def _noop(*_args, **_kwargs):
        return None

    async def no_job():
        return None

    monkeypatch.setattr(document_tagging, "ensure_document_tag_jobs_table", _noop)
    monkeypatch.setattr(document_tagging, "reconcile_terminal_tag_uploads", flaky_reconcile)
    monkeypatch.setattr(
        "raganything.services.auto_tagging.automatic_tagging_enabled", lambda: True
    )
    monkeypatch.setattr(
        document_tagging, "cleanup_deleted_document_tag_assignments", _noop
    )
    monkeypatch.setattr(document_tagging, "reconcile_missing_document_tags", _noop)
    monkeypatch.setattr(document_tagging, "claim_due_tag_job", no_job)
    monkeypatch.setattr(document_tagging.asyncio, "sleep", recording_sleep)

    with pytest.raises(asyncio.CancelledError):
        await document_tagging.document_tagging_loop(interval_seconds=3)

    assert reconcile_calls == 3
    assert sleeps == [3.0, 6.0, 3]


def test_kb_mutation_lease_exceeds_grace_and_heartbeat_window():
    heartbeat_interval = 15
    grace_seconds = 12 * heartbeat_interval
    acquire_default = inspect.signature(
        kb_mutation.acquire_kb_mutation_lease
    ).parameters["ttl_seconds"].default
    heartbeat_default = inspect.signature(
        kb_mutation.heartbeat_kb_mutation_lease
    ).parameters["ttl_seconds"].default

    assert acquire_default == heartbeat_default
    assert grace_seconds + heartbeat_interval < acquire_default
