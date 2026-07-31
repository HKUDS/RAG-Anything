from pathlib import Path
from types import SimpleNamespace

import pytest


def test_reset_table_manifest_covers_current_application_schema():
    from scripts.reset_system import EXPECTED_TABLES, PRESERVED_TABLES, PURGED_TABLES

    assert len(EXPECTED_TABLES) == 40
    assert PRESERVED_TABLES == {"roles", "settings", "users"}
    assert PRESERVED_TABLES.isdisjoint(PURGED_TABLES)
    assert {
        "agents",
        "audit_logs",
        "kb_metadata",
        "lightrag_doc_chunks",
        "monitor_events",
        "token_revocations",
        "upload_retry_jobs",
    }.issubset(PURGED_TABLES)


def test_reset_targets_are_scoped_and_do_not_include_configuration(tmp_path: Path):
    from scripts import reset_system

    for relative in (
        "uploads/document.pdf",
        "rag_storage/logs/server.log",
        "rag_storage_demo/graph.graphml",
        "output_demo/page.png",
        "frontend/dist/index.html",
        "workflows/runs/run.json",
        "raganything/__pycache__/module.pyc",
        "auth.db-wal",
        "auth.db-shm",
        "auth.db.pre_reset_backup",
        ".mypy_cache/state.json",
        "data/manufacturing_kb/dashboard/query_log.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated", encoding="utf-8")
    for relative in (".env", "agent_templates.json", "config/manufacturing.yaml"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preserve", encoding="utf-8")

    original_root = reset_system.ROOT
    reset_system.ROOT = tmp_path.resolve()
    try:
        targets = reset_system.collect_reset_targets(tmp_path)
    finally:
        reset_system.ROOT = original_root

    relative_targets = {str(path.relative_to(tmp_path)).replace("\\", "/") for path in targets}
    assert "uploads" in relative_targets
    assert "rag_storage" in relative_targets
    assert "rag_storage_demo" in relative_targets
    assert "output_demo" in relative_targets
    assert "frontend/dist" in relative_targets
    assert "workflows/runs" in relative_targets
    assert "raganything/__pycache__" in relative_targets
    assert "auth.db-wal" in relative_targets
    assert "auth.db-shm" in relative_targets
    assert "auth.db.pre_reset_backup" in relative_targets
    assert ".mypy_cache" in relative_targets
    assert "data/manufacturing_kb/dashboard/query_log.json" in relative_targets
    assert ".env" not in relative_targets
    assert "agent_templates.json" not in relative_targets
    assert "config/manufacturing.yaml" not in relative_targets


def test_deduplicate_targets_rejects_workspace_root(tmp_path: Path):
    from scripts import reset_system

    original_root = reset_system.ROOT
    reset_system.ROOT = tmp_path.resolve()
    try:
        with pytest.raises(reset_system.ResetRefused, match="unsafe reset target"):
            reset_system._deduplicate_targets([tmp_path])
    finally:
        reset_system.ROOT = original_root


def test_reset_staging_restore_and_purge_lifecycle(monkeypatch, tmp_path: Path):
    from scripts import reset_system

    monkeypatch.setattr(reset_system, "ROOT", tmp_path)
    upload = tmp_path / "uploads" / "document.pdf"
    upload.parent.mkdir()
    upload.write_text("content", encoding="utf-8")

    stage, moved = reset_system._stage_targets([upload.parent])
    assert not upload.parent.exists()
    assert (stage / "uploads" / "document.pdf").read_text(encoding="utf-8") == "content"

    reset_system._restore_targets(moved, stage)
    assert upload.read_text(encoding="utf-8") == "content"
    assert not stage.exists()

    stage, _moved = reset_system._stage_targets([upload.parent])
    reset_system._purge_stage(stage)
    assert not upload.parent.exists()
    assert not stage.exists()


def test_reset_marker_is_exclusive(monkeypatch, tmp_path: Path):
    from scripts import reset_system

    marker = tmp_path / ".system-reset-in-progress"
    monkeypatch.setattr(reset_system, "RESET_MARKER", marker)

    reset_system._acquire_reset_marker()

    assert marker.exists()
    with pytest.raises(reset_system.ResetRefused, match="reset marker already exists"):
        reset_system._acquire_reset_marker()


def test_worker_started_from_workspace_cwd_is_detected(monkeypatch, tmp_path: Path):
    from scripts import reset_system

    class Process:
        pid = 42
        info = {
            "cmdline": ["python", "process_worker.py", "--file", "input.pdf"],
            "cwd": str(tmp_path),
        }

    monkeypatch.setattr(reset_system.psutil, "process_iter", lambda _attrs: [Process()])

    active = reset_system.active_application_processes(tmp_path)

    assert active == [{
        "pid": 42,
        "command": "python process_worker.py --file input.pdf",
    }]


def test_auth_runtime_constants_refresh_from_postgres_module(monkeypatch):
    from raganything.services import auth, pg_auth_repo

    monkeypatch.setattr(auth, "SECRET_KEY", auth.SECRET_KEY)
    monkeypatch.setattr(auth, "REFRESH_SECRET_KEY", auth.REFRESH_SECRET_KEY)
    monkeypatch.setattr(auth, "SERVER_START_ID", auth.SERVER_START_ID)
    monkeypatch.setattr(pg_auth_repo, "SECRET_KEY", "new-access-secret")
    monkeypatch.setattr(pg_auth_repo, "REFRESH_SECRET_KEY", "new-refresh-secret")
    monkeypatch.setattr(pg_auth_repo, "SERVER_START_ID", "new-server-id")

    auth.refresh_runtime_constants()

    assert auth.SECRET_KEY == "new-access-secret"
    assert auth.REFRESH_SECRET_KEY == "new-refresh-secret"
    assert auth.SERVER_START_ID == "new-server-id"


@pytest.mark.asyncio
async def test_reset_database_preserves_admin_and_seeds_owned_baseline(monkeypatch):
    from scripts import reset_system

    class Transaction:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            if self.connection.fail_commit:
                raise RuntimeError("commit acknowledgement failed")
            return False

    class Connection:
        def __init__(self):
            self.executed = []
            self.isolation = None
            self.fail_close = False
            self.fail_commit = False

        def transaction(self, *, isolation):
            self.isolation = isolation
            return Transaction(self)

        async def execute(self, sql, *args):
            self.executed.append((sql, args))
            return "OK"

        async def fetch(self, sql, *_args):
            assert "information_schema.tables" in sql
            return [{"table_name": name} for name in reset_system.EXPECTED_TABLES]

        async def fetchval(self, sql, *args):
            if "password_hash" in sql:
                assert args == (7, "admin")
                return "preserved-hash"
            if "name = 'super_admin'" in sql:
                return 76
            if "MAX(id) FROM roles" in sql:
                return 80
            raise AssertionError(sql)

        async def fetchrow(self, sql, *args):
            assert "SELECT COUNT(*) FROM users" in sql
            assert args == (7,)
            return {
                "users": 1,
                "roles": 5,
                "knowledge_bases": 1,
                "agents": 1,
                "password_hash": "preserved-hash",
            }

        async def close(self):
            if self.fail_close:
                raise RuntimeError("connection close failed")
            return None

    connection = Connection()

    async def connect():
        return connection

    monkeypatch.setattr(reset_system, "_connect", connect)
    result = await reset_system.reset_database({
        "admin": {"id": 7},
        "password_hash": "preserved-hash",
    })

    statements = "\n".join(sql for sql, _args in connection.executed)
    assert connection.isolation == "serializable"
    assert "TRUNCATE TABLE" in statements
    assert "DELETE FROM users WHERE id <> $1" in statements
    assert "DELETE FROM roles" in statements
    assert "INSERT INTO kb_metadata" in statements
    assert "INSERT INTO agents" in statements
    assert statements.count("SELECT setval") == 2
    assert result["admin_id"] == 7
    agent_call = next(call for call in connection.executed if "INSERT INTO agents" in call[0])
    assert agent_call[1][2:4] == (7, "admin")

    connection.fail_close = True
    with pytest.raises(
        reset_system.DatabaseCommitUncertain,
        match="database committed but connection cleanup failed",
    ):
        await reset_system.reset_database({
            "admin": {"id": 7},
            "password_hash": "preserved-hash",
        })

    connection.fail_close = False
    connection.fail_commit = True
    with pytest.raises(
        reset_system.DatabaseCommitUncertain,
        match="database commit outcome is uncertain",
    ):
        await reset_system.reset_database({
            "admin": {"id": 7},
            "password_hash": "preserved-hash",
        })


@pytest.mark.asyncio
async def test_reset_database_rechecks_manifest_inside_transaction(monkeypatch):
    from scripts import reset_system

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class Connection:
        def __init__(self):
            self.executed = []

        def transaction(self, **_kwargs):
            return Transaction()

        async def execute(self, sql, *args):
            self.executed.append((sql, args))

        async def fetch(self, _sql, *_args):
            return [{"table_name": "unexpected_runtime_table"}]

        async def close(self):
            return None

    connection = Connection()

    async def connect():
        return connection

    monkeypatch.setattr(reset_system, "_connect", connect)
    with pytest.raises(reset_system.ResetRefused, match="manifest changed"):
        await reset_system.reset_database({
            "admin": {"id": 7},
            "password_hash": "preserved-hash",
        })

    assert not any("TRUNCATE TABLE" in sql for sql, _args in connection.executed)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["mirror", "database_close"])
async def test_post_commit_failure_purges_stage_and_keeps_reset_marker(
    monkeypatch, tmp_path: Path, failure_point: str
):
    from scripts import reset_system

    marker = tmp_path / ".system-reset-in-progress"
    stage = tmp_path / ".system-reset-staging-test"
    stage.mkdir()
    (stage / "old-data").write_text("staged", encoding="utf-8")

    async def database_preflight():
        return {"admin": {"id": 7}, "password_hash": "preserved-hash"}

    async def reset_database(_database):
        if failure_point == "database_close":
            raise reset_system.DatabaseCommitUncertain("connection cleanup failed")
        return {"admin_id": 7, "system_data_epoch": "new-epoch"}

    def write_mirror(_admin_id):
        if failure_point == "mirror":
            raise RuntimeError("mirror write failed")

    monkeypatch.setattr(reset_system, "ROOT", tmp_path)
    monkeypatch.setattr(reset_system, "RESET_MARKER", marker)
    monkeypatch.setattr(
        reset_system,
        "_parse_args",
        lambda: SimpleNamespace(
            execute=True,
            confirm=reset_system.CONFIRMATION_PHRASE,
        ),
    )
    monkeypatch.setattr(reset_system, "database_preflight", database_preflight)
    monkeypatch.setattr(reset_system, "collect_reset_targets", lambda: [])
    monkeypatch.setattr(
        reset_system,
        "build_preflight_report",
        lambda _database, _targets: {"execution_blocked": False},
    )
    monkeypatch.setattr(
        reset_system,
        "service_blockers",
        lambda: {"active_ports": {}, "active_processes": []},
    )
    monkeypatch.setattr(reset_system, "_stage_targets", lambda _targets: (stage, []))
    monkeypatch.setattr(reset_system, "reset_database", reset_database)
    monkeypatch.setattr(reset_system, "_write_kb_mirror", write_mirror)
    monkeypatch.setattr(
        reset_system,
        "_restore_targets",
        lambda *_args: pytest.fail("post-commit data must never be restored"),
    )

    expected_error = (
        reset_system.DatabaseCommitUncertain
        if failure_point == "database_close"
        else RuntimeError
    )
    expected_message = (
        "connection cleanup failed"
        if failure_point == "database_close"
        else "mirror write failed"
    )
    with pytest.raises(expected_error, match=expected_message):
        await reset_system.main()

    assert marker.exists()
    assert not stage.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "precommit_failure"])
async def test_main_clears_marker_only_after_success_or_complete_rollback(
    monkeypatch, tmp_path: Path, outcome: str
):
    from scripts import reset_system

    marker = tmp_path / ".system-reset-in-progress"
    upload = tmp_path / "uploads" / "document.pdf"
    upload.parent.mkdir()
    upload.write_text("old-data", encoding="utf-8")

    async def database_preflight():
        return {"admin": {"id": 7}, "password_hash": "preserved-hash"}

    async def reset_database(_database):
        if outcome == "precommit_failure":
            raise RuntimeError("transaction rolled back")
        return {"admin_id": 7, "system_data_epoch": "new-epoch"}

    async def post_reset_audit(_admin_id, _password_hash):
        return {"kb_metadata": 1, "agents": 1}

    monkeypatch.setattr(reset_system, "ROOT", tmp_path)
    monkeypatch.setattr(reset_system, "RESET_MARKER", marker)
    monkeypatch.setattr(
        reset_system,
        "_parse_args",
        lambda: SimpleNamespace(
            execute=True,
            confirm=reset_system.CONFIRMATION_PHRASE,
        ),
    )
    monkeypatch.setattr(reset_system, "database_preflight", database_preflight)
    monkeypatch.setattr(reset_system, "collect_reset_targets", lambda: [upload.parent])
    monkeypatch.setattr(
        reset_system,
        "build_preflight_report",
        lambda _database, _targets: {"execution_blocked": False},
    )
    monkeypatch.setattr(
        reset_system,
        "service_blockers",
        lambda: {"active_ports": {}, "active_processes": []},
    )
    monkeypatch.setattr(reset_system, "reset_database", reset_database)
    monkeypatch.setattr(reset_system, "_write_kb_mirror", lambda _admin_id: None)
    monkeypatch.setattr(reset_system, "_post_reset_audit", post_reset_audit)

    if outcome == "precommit_failure":
        with pytest.raises(RuntimeError, match="transaction rolled back"):
            await reset_system.main()
        assert upload.read_text(encoding="utf-8") == "old-data"
    else:
        assert await reset_system.main() == 0
        assert not upload.parent.exists()

    assert not marker.exists()
    assert not list(tmp_path.glob(".system-reset-staging-*"))


@pytest.mark.asyncio
async def test_agent_listing_fails_closed_when_postgres_is_unavailable(monkeypatch):
    from raganything.services import pg_agent_repo

    class Pool:
        async def fetch(self, *_args):
            raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: Pool())

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        await pg_agent_repo.pg_list_agents(is_admin=True)


@pytest.mark.asyncio
async def test_default_agent_uses_deterministic_id_and_real_admin(monkeypatch):
    from raganything.services import pg_agent_repo

    class Pool:
        async def fetchval(self, *_args):
            return 0

        async def fetchrow(self, *_args):
            return {"id": 7, "username": "admin"}

    created = []

    async def create(config, owner_id=0, owner_username=""):
        created.append((config, owner_id, owner_username))
        return {"id": config["id"]}

    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: Pool())
    monkeypatch.setattr(pg_agent_repo, "pg_create_agent", create)

    agent, thread = await pg_agent_repo.pg_ensure_default_agent()

    assert agent == {"id": "default"}
    assert thread is None
    assert created[0][0]["id"] == "default"
    assert created[0][1:] == (7, "admin")


@pytest.mark.asyncio
async def test_kb_metadata_write_does_not_fall_back_after_pg_failure(
    monkeypatch, tmp_path: Path
):
    from raganything.services import kb_service, pg_kb_meta_repo

    async def fail(_meta):
        raise RuntimeError("postgres unavailable")

    mirror = tmp_path / "rag_storage_kb_meta.json"
    monkeypatch.setattr(pg_kb_meta_repo, "pg_save_all_kb_meta", fail)
    monkeypatch.setattr(kb_service, "KB_META_JSON", mirror)

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        await kb_service.save_kb_meta({"default": {"name": "Default"}})

    assert not mirror.exists()
