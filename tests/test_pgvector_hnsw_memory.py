from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest


def _health_script():
    path = Path(__file__).parents[1] / "scripts" / "check_pgvector_hnsw.py"
    spec = importlib.util.spec_from_file_location("check_pgvector_hnsw", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_hnsw_worker_failure_bypasses_degraded_completion_and_auto_retry(monkeypatch, tmp_path):
    from raganything.services import kb_service, state_service, user_settings, ws_service

    uploaded = tmp_path / "graph.mp4"
    uploaded.write_bytes(b"video")
    calls = []

    class Stream:
        def __init__(self, lines):
            self._lines = iter(lines)

        async def readline(self):
            return next(self._lines, b"")

    class FailedWorker:
        returncode = 1
        stdout = Stream([
            b'WORKER_ERROR_JSON {"stage":"graph_index","root_type":"GraphIndexHnswMemoryExhausted","failure_code":"graph_index_hnsw_memory_exhausted","retryable":false,"message":"HNSW exhausted"}\n'
        ])
        stderr = Stream([])

        async def wait(self):
            return self.returncode

    async def no_op(*_args, **_kwargs):
        return None

    async def update_upload(*args, **kwargs):
        calls.append(("upload", args, kwargs))
        return {"task_id": args[0]}

    async def terminalize(**kwargs):
        calls.append(("terminalize", kwargs))
        return {"status": "terminal_failed"}

    async def persist(*args, **kwargs):
        calls.append(("doc_status", args, kwargs))

    async def event(*args, **kwargs):
        calls.append(("event", args, kwargs))

    async def fake_subprocess(*_args, **_kwargs):
        return FailedWorker()

    async def snapshot(_task_id):
        return {
            "revision": 1,
            "fingerprint": "hnsw-test-snapshot",
            "settings": {"ingestion": {"chunking_strategy": "recursive"}},
        }

    monkeypatch.setattr(user_settings, "get_task_settings_snapshot", snapshot)
    monkeypatch.setattr(kb_service.asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(kb_service, "pg_update_upload_status_by_task_id", update_upload)
    monkeypatch.setattr(kb_service, "_register_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_unregister_processing_file", lambda *_args: None)
    monkeypatch.setattr(kb_service, "_kb_worker_procs", {})
    monkeypatch.setattr(kb_service, "_finalize_failed_upload", pytest.fail)
    monkeypatch.setattr(kb_service, "_persist_hnsw_terminal_doc_status", persist)
    monkeypatch.setattr(
        "raganything.services.upload_retry.terminalize_hnsw_memory_failure", terminalize,
    )
    monkeypatch.setattr(state_service, "processing_tasks", {})
    monkeypatch.setattr(state_service, "upsert_task_state", no_op)
    monkeypatch.setattr(state_service, "update_task_progress", no_op)
    monkeypatch.setattr(state_service, "complete_task", no_op)
    monkeypatch.setattr(ws_service, "emit_progress", no_op)
    monkeypatch.setattr(ws_service, "add_event", event)
    monkeypatch.setattr(ws_service, "ws_broadcast", no_op)

    await kb_service._process_uploaded_file(
        "task-hnsw", str(uploaded), "graph.mp4", kb_name="demo", user_id=7,
    )

    terminal = next(call for call in calls if call[0] == "terminalize")
    assert terminal[1]["retry_job_id"] is None
    assert terminal[1]["chunking_strategy"] == "recursive"
    assert any(call[0] == "doc_status" for call in calls)
    failure_event = next(
        call for call in calls
        if call[0] == "event" and call[1] == ("upload_error",)
    )
    assert failure_event[1] == ("upload_error",)
    assert failure_event[2]["failure_stage"] == "graph_index"
    assert failure_event[2]["retryable"] is False


@pytest.mark.asyncio
async def test_retry_now_requeues_only_guarded_hnsw_terminal_job(monkeypatch):
    from raganything.services import upload_retry

    statements = []

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Connection:
        def transaction(self):
            return Transaction()

        async def fetchrow(self, sql, *_args):
            statements.append(sql)
            return {"upload_id": 3}

        async def execute(self, sql, *_args):
            statements.append(sql)

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr(upload_retry, "get_pg_pool", lambda: Pool())

    assert await upload_retry.retry_now("task-hnsw", reset_budget=True)
    update = statements[0]
    assert "status='terminal_failed' AND stage='graph_index'" in update
    assert "root_type='GraphIndexHnswMemoryExhausted'" in update


def test_hnsw_health_check_is_catalog_discovery_and_redacts_connection_failure(monkeypatch, capsys):
    script = _health_script()
    source = Path(script.__file__).read_text(encoding="utf-8")
    assert "pg_catalog" in source or "pg_index" in source
    assert "am.amname='hnsw'" in source
    assert "DATABASE_URL is required; it is never printed" in source

    async def failed(_url):
        raise ValueError("postgresql://user:secret@host/database")

    monkeypatch.setattr(script, "collect_hnsw_health", failed)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@host/database")
    monkeypatch.setattr("sys.argv", ["check_pgvector_hnsw.py"])
    assert script.main() == 2
    assert "secret" not in capsys.readouterr().out
