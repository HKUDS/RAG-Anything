import json
from contextlib import asynccontextmanager

import pytest

from raganything.base import DocStatus
from raganything.services import kb_service


class _FakeConnection:
    def __init__(
        self,
        recovered_rows=None,
        active_task_rows=None,
        fetchval_result=True,
        fetchval_error=None,
        active_task_error=None,
        execute_error=None,
    ):
        self.recovered_rows = recovered_rows or []
        self.active_task_rows = active_task_rows or []
        self.fetchval_result = fetchval_result
        self.fetchval_error = fetchval_error
        self.active_task_error = active_task_error
        self.execute_error = execute_error
        self.fetchval_calls = []
        self.fetch_calls = []
        self.execute_calls = []
        self.transaction_calls = 0

    async def fetchval(self, statement):
        self.fetchval_calls.append(statement)
        if self.fetchval_error is not None:
            raise self.fetchval_error
        return self.fetchval_result

    async def fetch(self, statement, *args):
        self.fetch_calls.append((statement, args))
        if "SELECT kb_name FROM processing_tasks" in statement:
            if self.active_task_error is not None:
                raise self.active_task_error
            return self.active_task_rows
        return self.recovered_rows

    async def execute(self, statement):
        self.execute_calls.append(statement)
        if self.execute_error is not None:
            raise self.execute_error

    def transaction(self):
        self.transaction_calls += 1
        return _FakeTransaction()


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _FakeAcquire(self.connection)


@pytest.mark.asyncio
async def test_recovery_lock_releases_advisory_lock_on_its_acquired_connection(monkeypatch):
    connection = _FakeConnection()
    pool = _FakePool(connection)

    import raganything.services.pg_state_repo as pg_state_repo

    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: pool)

    async with kb_service._recovery_lock() as held_connection:
        assert held_connection is connection

    assert connection.fetchval_calls == ["SELECT pg_try_advisory_lock(987654)"]
    assert connection.execute_calls == ["SELECT pg_advisory_unlock(987654)"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "connection",
    [
        _FakeConnection(fetchval_result=False),
        _FakeConnection(fetchval_error=RuntimeError("PG unavailable")),
    ],
)
async def test_recovery_lock_fails_closed_when_pg_lock_is_unavailable(
    monkeypatch, connection
):
    pool = _FakePool(connection)

    import raganything.services.pg_state_repo as pg_state_repo

    monkeypatch.setattr(kb_service, "_pg_storage_ready", lambda: True)
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: pool)

    async with kb_service._recovery_lock() as held_connection:
        assert held_connection is kb_service._RECOVERY_LOCK_NOT_ACQUIRED

    assert connection.execute_calls == []


@pytest.mark.asyncio
async def test_recovery_updates_pg_status_without_loading_knowledge_bases(monkeypatch):
    connection = _FakeConnection(recovered_rows=[{"workspace": "./rag_storage_demo", "id": "doc-1"}])

    @asynccontextmanager
    async def fake_recovery_lock():
        yield connection

    async def empty_metadata():
        return {}

    async def fail_get_kb(*args, **kwargs):
        raise AssertionError("recovery must not initialize a KB instance")

    monkeypatch.setattr(kb_service, "_recovery_lock", fake_recovery_lock)
    monkeypatch.setattr(kb_service, "load_kb_meta", empty_metadata)
    monkeypatch.setattr(kb_service, "get_kb", fail_get_kb)

    await kb_service._recover_stuck_documents()

    assert len(connection.fetch_calls) == 1
    statement, args = connection.fetch_calls[0]
    assert "FROM processing_tasks AS task" in statement
    assert "metadata -> 'multimodal_processed' = 'true'::jsonb" in statement
    assert "metadata ->> 'multimodal_processed'" not in statement
    assert "task.updated_at" not in statement
    assert args == (DocStatus.PROCESSED.value, DocStatus.HANDLING.value)


@pytest.mark.asyncio
async def test_recovery_keeps_json_backed_documents_compatible(tmp_path, monkeypatch):
    workspace = tmp_path / "demo"
    workspace.mkdir()
    status_path = workspace / "kv_store_doc_status.json"
    status_path.write_text(
        json.dumps(
            {
                "finished": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {"processing_end_time": 123, "multimodal_processed": True},
                },
                "unfinished": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {},
                },
                "text-only-finished": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {"processing_end_time": 123},
                },
                "legacy-top-level-marker": {
                    "status": DocStatus.HANDLING.value,
                    "multimodal_processed": True,
                    "metadata": {"processing_end_time": 123},
                },
                "string-marker": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {
                        "processing_end_time": 123,
                        "multimodal_processed": "true",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    @asynccontextmanager
    async def json_only_recovery_lock():
        yield None

    async def demo_metadata():
        return {"demo": {}}

    monkeypatch.setattr(kb_service, "_recovery_lock", json_only_recovery_lock)
    monkeypatch.setattr(kb_service, "load_kb_meta", demo_metadata)
    monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(workspace))

    await kb_service._recover_stuck_documents()

    recovered = json.loads(status_path.read_text(encoding="utf-8"))
    assert recovered["finished"]["status"] == DocStatus.PROCESSED.value
    assert recovered["unfinished"]["status"] == DocStatus.HANDLING.value
    assert recovered["text-only-finished"]["status"] == DocStatus.HANDLING.value
    assert recovered["legacy-top-level-marker"]["status"] == DocStatus.HANDLING.value
    assert recovered["string-marker"]["status"] == DocStatus.HANDLING.value


@pytest.mark.asyncio
async def test_json_recovery_does_not_complete_a_document_with_an_active_task(tmp_path, monkeypatch):
    workspace = tmp_path / "demo"
    workspace.mkdir()
    status_path = workspace / "kv_store_doc_status.json"
    status_path.write_text(
        json.dumps(
            {
                "active-document": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {"processing_end_time": 123, "multimodal_processed": True},
                }
            }
        ),
        encoding="utf-8",
    )

    @asynccontextmanager
    async def json_only_recovery_lock():
        yield None

    async def demo_metadata():
        return {"demo": {}}

    import raganything.services.state_service as state_service

    monkeypatch.setattr(kb_service, "_recovery_lock", json_only_recovery_lock)
    monkeypatch.setattr(kb_service, "load_kb_meta", demo_metadata)
    monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(workspace))
    monkeypatch.setattr(
        state_service,
        "processing_tasks",
        {"task-1": {"kb": "demo", "status": "processing"}},
    )

    await kb_service._recover_stuck_documents()

    recovered = json.loads(status_path.read_text(encoding="utf-8"))
    assert recovered["active-document"]["status"] == DocStatus.HANDLING.value


@pytest.mark.asyncio
async def test_json_recovery_uses_active_tasks_from_pg(tmp_path, monkeypatch):
    workspace = tmp_path / "demo"
    workspace.mkdir()
    status_path = workspace / "kv_store_doc_status.json"
    status_path.write_text(
        json.dumps(
            {
                "active-document": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {"processing_end_time": 123, "multimodal_processed": True},
                }
            }
        ),
        encoding="utf-8",
    )
    connection = _FakeConnection(active_task_rows=[{"kb_name": "demo"}])

    @asynccontextmanager
    async def pg_recovery_lock():
        yield connection

    async def demo_metadata():
        return {"demo": {}}

    monkeypatch.setattr(kb_service, "_recovery_lock", pg_recovery_lock)
    monkeypatch.setattr(kb_service, "load_kb_meta", demo_metadata)
    monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(workspace))

    await kb_service._recover_stuck_documents()

    recovered = json.loads(status_path.read_text(encoding="utf-8"))
    assert recovered["active-document"]["status"] == DocStatus.HANDLING.value
    assert any(
        "SELECT kb_name FROM processing_tasks" in statement
        for statement, _ in connection.fetch_calls
    )
    assert connection.execute_calls == ["LOCK TABLE processing_tasks IN SHARE MODE NOWAIT"]
    assert connection.transaction_calls == 1


@pytest.mark.asyncio
async def test_json_recovery_fails_closed_when_pg_active_task_lookup_fails(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "demo"
    workspace.mkdir()
    status_path = workspace / "kv_store_doc_status.json"
    status_path.write_text(
        json.dumps(
            {
                "active-document": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {
                        "processing_end_time": 123,
                        "multimodal_processed": True,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    connection = _FakeConnection(active_task_error=RuntimeError("PG unavailable"))

    @asynccontextmanager
    async def pg_recovery_lock():
        yield connection

    async def demo_metadata():
        return {"demo": {}}

    monkeypatch.setattr(kb_service, "_recovery_lock", pg_recovery_lock)
    monkeypatch.setattr(kb_service, "load_kb_meta", demo_metadata)
    monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(workspace))

    await kb_service._recover_stuck_documents()

    recovered = json.loads(status_path.read_text(encoding="utf-8"))
    assert recovered["active-document"]["status"] == DocStatus.HANDLING.value


@pytest.mark.asyncio
async def test_json_recovery_fails_closed_when_pg_task_coordination_lock_fails(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "demo"
    workspace.mkdir()
    status_path = workspace / "kv_store_doc_status.json"
    status_path.write_text(
        json.dumps(
            {
                "active-document": {
                    "status": DocStatus.HANDLING.value,
                    "metadata": {
                        "processing_end_time": 123,
                        "multimodal_processed": True,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    connection = _FakeConnection(execute_error=RuntimeError("lock unavailable"))

    @asynccontextmanager
    async def pg_recovery_lock():
        yield connection

    async def demo_metadata():
        return {"demo": {}}

    monkeypatch.setattr(kb_service, "_recovery_lock", pg_recovery_lock)
    monkeypatch.setattr(kb_service, "load_kb_meta", demo_metadata)
    monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(workspace))

    await kb_service._recover_stuck_documents()

    recovered = json.loads(status_path.read_text(encoding="utf-8"))
    assert recovered["active-document"]["status"] == DocStatus.HANDLING.value
    assert connection.execute_calls == ["LOCK TABLE processing_tasks IN SHARE MODE NOWAIT"]
