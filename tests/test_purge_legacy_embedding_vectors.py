"""Self-checks for the one-time legacy embedding vector purge script."""

import json
import re

import pytest

from scripts.purge_legacy_embedding_vectors import (
    EXIT_EXPECTED,
    EXIT_OK,
    PurgeError,
    _sanitize,
    apply,
    dry_run,
    main,
)

HASH = "639985a6e4b87473e90542a7953028829f9c850e59496ef691694cefe6229505"

FIXED_IDENTITY = {
    "schema_version": "text-embedding-v1",
    "provider": "openai_compatible",
    "model": "text-embedding-v3",
    "dimension": 1024,
    "endpoint_semantics": "dashscope.aliyuncs.com/compatible-mode/v1",
    "endpoint_fingerprint": "e34d4d3c2d5aa0e09982bd67",
    "identity_hash": HASH,
    "table_suffix": "openai_compa_639985a6e4b87473",
    "model_name": "openai_compa_639985a6e4b87473",
}

LEGACY_TABLES = ["lightrag_vdb_chunks", "lightrag_vdb_entity", "lightrag_vdb_relation"]
SUFFIXED_TABLE = "lightrag_vdb_chunks_openai_compa_639985a6e4b87473_1024d"
VIDEO = "./rag_storage_视频"
NEW_ENERGY = "./rag_storage_新能源"


def default_dataset():
    return {
        "lightrag_vdb_chunks": {VIDEO: 115, NEW_ENERGY: 536},
        "lightrag_vdb_entity": {VIDEO: 640, NEW_ENERGY: 1200},
        "lightrag_vdb_relation": {VIDEO: 900, NEW_ENERGY: 1500},
    }


def default_registrations():
    return {"./rag_storage": (HASH, json.dumps(FIXED_IDENTITY, sort_keys=True))}


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.transactions.append(True)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.rolled_back = exc_type is not None
        return False


class FakeConn:
    def __init__(self, *, legacy=None, suffixed=None, rows=None, registrations=None, delete_effective=True):
        self.legacy = list(legacy or LEGACY_TABLES)
        self.suffixed = list(suffixed or [])
        self.rows = {table: dict(rows.get(table, {})) for table in (rows or {})}
        self.registrations = dict(registrations or {})
        self.delete_effective = delete_effective
        self.executed = []
        self.advisory_locks = []
        self.inserted = []
        self.rolled_back = None
        self.transactions = []

    async def fetch(self, query, *args):
        lowered = query.lower()
        if "pg_catalog.pg_class" in lowered:
            return [{"table_name": table} for table in self.legacy + self.suffixed]
        if "from information_schema.tables" in lowered:
            requested = (args[0] or "").lower() if args else ""
            return [{"table_name": table} for table in self.legacy if table.lower() == requested]
        if "from kb_text_embedding_identities" in lowered:
            return [
                {"workspace": workspace, "identity_hash": hash_, "identity": identity}
                for workspace, (hash_, identity) in sorted(self.registrations.items())
            ]
        if "group by workspace" in lowered:
            table = self._table(query)
            return [
                {"workspace": workspace, "n": count}
                for workspace, count in sorted(self.rows.get(table, {}).items())
            ]
        raise AssertionError(f"unhandled fetch: {query!r} {args!r}")

    async def fetchrow(self, query, *args):
        lowered = query.lower()
        if "from information_schema.tables" in lowered:
            requested = (args[0] or "").lower() if args else ""
            found = [table for table in self.legacy if table.lower() == requested]
            return {"table_name": found[0]} if found else None
        if "from kb_text_embedding_identities" in lowered and "for update" in lowered:
            workspace = args[0]
            if workspace in self.registrations:
                hash_, identity = self.registrations[workspace]
                return {"identity_hash": hash_, "identity": identity}
            return None
        raise AssertionError(f"unhandled fetchrow: {query!r} {args!r}")

    async def fetchval(self, query, *args):
        lowered = query.lower()
        if "from information_schema.columns" in lowered:
            table = args[0]
            return 1 if table in self.legacy + self.suffixed else None
        if "select count(*) from" in lowered:
            table = self._table(query)
            workspace = args[0]
            return self.rows.get(table, {}).get(workspace, 0)
        raise AssertionError(f"unhandled fetchval: {query!r} {args!r}")

    async def execute(self, query, *args):
        lowered = query.lower()
        self.executed.append((query, args))
        if lowered.startswith("insert into kb_text_embedding_identities"):
            workspace, hash_, identity = args
            self.registrations[workspace] = (hash_, identity)
            self.inserted.append(workspace)
            return "INSERT 0 1"
        if "pg_advisory_xact_lock" in lowered:
            self.advisory_locks.append(args[0])
            return "SELECT 1"
        if lowered.startswith("delete from"):
            table = self._table(query)
            workspace = args[0]
            if self.delete_effective:
                self.rows.setdefault(table, {}).pop(workspace, None)
            return "DELETE 1"
        raise AssertionError(f"unhandled execute: {query!r} {args!r}")

    def transaction(self):
        return FakeTransaction(self)

    @staticmethod
    def _table(query):
        match = re.search(r'"([^"]+)"', query)
        if not match:
            raise AssertionError(f"no quoted table in query: {query!r}")
        return match.group(1)


def make_backup(tmp_path, tables=LEGACY_TABLES):
    for table in tables:
        (tmp_path / f"{table}.dump").write_text(
            f"COPY public.{table} (id, workspace) FROM stdin;\n\\N\n\\.\n",
            encoding="utf-8",
        )
    return tmp_path


def identity_loader():
    return dict(FIXED_IDENTITY)


# ── dry-run ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_reports_baseline_and_suffixed_inventory():
    rows = default_dataset()
    rows[SUFFIXED_TABLE] = {"./rag_storage_测试": 3}
    conn = FakeConn(suffixed=[SUFFIXED_TABLE], rows=rows, registrations=default_registrations())
    report = await dry_run(conn, identity_loader=identity_loader)
    assert report["mode"] == "dry-run"
    assert set(report["affected_workspaces"]) == {VIDEO, NEW_ENERGY}
    assert report["baseline"]["lightrag_vdb_chunks"][VIDEO] == 115
    assert report["baseline"]["lightrag_vdb_relation"][NEW_ENERGY] == 1500
    assert report["suffixed_rows"][SUFFIXED_TABLE] == {"./rag_storage_测试": 3}
    assert report["identity_hash"] == HASH
    assert conn.executed == []


@pytest.mark.asyncio
async def test_dry_run_zero_rows():
    conn = FakeConn(rows={}, registrations=default_registrations())
    report = await dry_run(conn, identity_loader=identity_loader)
    assert report["affected_workspaces"] == []
    assert report["baseline"] == {"lightrag_vdb_chunks": {}, "lightrag_vdb_entity": {}, "lightrag_vdb_relation": {}}


# ── apply success / idempotency ────────────────────────────────

@pytest.mark.asyncio
async def test_apply_success_inserts_identity_and_deletes(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    report = await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)
    assert report["mode"] == "apply"
    assert set(report["affected_workspaces"]) == {VIDEO, NEW_ENERGY}
    assert report["registrations"] == {VIDEO: "INSERTED", NEW_ENERGY: "INSERTED"}
    assert report["deletions"][VIDEO] == {
        "lightrag_vdb_chunks": 115, "lightrag_vdb_entity": 640, "lightrag_vdb_relation": 900,
    }
    assert report["remaining"] == {}
    assert set(conn.inserted) == {VIDEO, NEW_ENERGY}
    assert set(conn.advisory_locks) == {VIDEO, NEW_ENERGY}
    assert conn.registrations[VIDEO] == (HASH, json.dumps(FIXED_IDENTITY, sort_keys=True))
    assert conn.rows.get("lightrag_vdb_chunks", {}).get(VIDEO, 0) == 0
    assert conn.rolled_back is False


@pytest.mark.asyncio
async def test_apply_idempotent_second_run(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    backup = make_backup(tmp_path)
    first = await apply(conn, backup_dir=backup, identity_loader=identity_loader)
    assert sum(sum(v.values()) for v in first["deletions"].values()) > 0
    second = await apply(conn, backup_dir=backup, identity_loader=identity_loader)
    assert second["affected_workspaces"] == []
    assert second["deletions"] == {}
    assert second["registrations"] == {}
    assert second["remaining"] == {}


@pytest.mark.asyncio
async def test_apply_existing_matching_registration_is_existed(tmp_path):
    registrations = default_registrations()
    registrations[VIDEO] = (HASH, json.dumps(FIXED_IDENTITY, sort_keys=True))
    conn = FakeConn(rows=default_dataset(), registrations=registrations)
    report = await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)
    assert report["registrations"][VIDEO] == "EXISTED"
    assert VIDEO not in conn.inserted
    assert report["registrations"][NEW_ENERGY] == "INSERTED"


# ── backup gate ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_requires_backup_dir():
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    with pytest.raises(PurgeError, match="backup"):
        await apply(conn, backup_dir=None, identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_apply_backup_gate_missing_file(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    make_backup(tmp_path, tables=LEGACY_TABLES[:2])
    with pytest.raises(PurgeError, match="backup gate"):
        await apply(conn, backup_dir=tmp_path, identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_apply_backup_gate_empty_file(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    (tmp_path / f"{LEGACY_TABLES[0]}.dump").write_text("", encoding="utf-8")
    make_backup(tmp_path, tables=LEGACY_TABLES[1:])
    with pytest.raises(PurgeError, match="backup gate"):
        await apply(conn, backup_dir=tmp_path, identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_apply_backup_gate_without_copy(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    for table in LEGACY_TABLES:
        (tmp_path / f"{table}.dump").write_text("not a pg dump", encoding="utf-8")
    with pytest.raises(PurgeError, match="backup gate"):
        await apply(conn, backup_dir=tmp_path, identity_loader=identity_loader)


# ── force guard ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_force_gate_refuses_without_force(tmp_path):
    rows = default_dataset()
    rows[SUFFIXED_TABLE] = {VIDEO: 1}
    conn = FakeConn(suffixed=[SUFFIXED_TABLE], rows=rows, registrations=default_registrations())
    with pytest.raises(PurgeError, match="suffixed"):
        await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)
    assert conn.rows["lightrag_vdb_chunks"][VIDEO] == 115
    assert conn.rolled_back is True


@pytest.mark.asyncio
async def test_apply_force_gate_allows_with_force(tmp_path):
    rows = default_dataset()
    rows[SUFFIXED_TABLE] = {VIDEO: 1}
    conn = FakeConn(suffixed=[SUFFIXED_TABLE], rows=rows, registrations=default_registrations())
    report = await apply(conn, backup_dir=make_backup(tmp_path), force=True, identity_loader=identity_loader)
    assert report["force_used"] == [VIDEO]
    assert conn.rows.get("lightrag_vdb_chunks", {}).get(VIDEO, 0) == 0
    assert conn.rolled_back is False


# ── identity guards ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_identity_source_missing_fails_closed():
    conn = FakeConn(rows=default_dataset(), registrations={})
    with pytest.raises(PurgeError, match="identity source missing"):
        await dry_run(conn, identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_identity_env_mismatch_aborts(tmp_path):
    other = dict(FIXED_IDENTITY)
    other["model"] = "other-model"
    other["identity_hash"] = "different"
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    with pytest.raises(PurgeError, match="env mismatch"):
        await dry_run(conn, identity_loader=lambda: other)
    with pytest.raises(PurgeError, match="env mismatch"):
        await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=lambda: other)


@pytest.mark.asyncio
async def test_embedding_registry_inconsistent_aborts(tmp_path):
    other = dict(FIXED_IDENTITY)
    other["identity_hash"] = "different-hash"
    registrations = default_registrations()
    registrations["./rag_storage_autorepair"] = ("different-hash", json.dumps(other, sort_keys=True))
    conn = FakeConn(rows=default_dataset(), registrations=registrations)
    with pytest.raises(PurgeError, match="inconsistent"):
        await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_target_workspace_conflict_registration_aborts(tmp_path):
    other = dict(FIXED_IDENTITY)
    other["identity_hash"] = "conflicting-hash"
    registrations = default_registrations()
    registrations[VIDEO] = ("conflicting-hash", json.dumps(other, sort_keys=True))
    conn = FakeConn(rows=default_dataset(), registrations=registrations)
    with pytest.raises(PurgeError, match="identity"):
        await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)
    assert conn.rows["lightrag_vdb_chunks"][VIDEO] == 115
    assert not [q for q, _ in conn.executed if q.lower().startswith("delete from")]


@pytest.mark.asyncio
async def test_pg_workspace_override_rejected(monkeypatch):
    monkeypatch.setenv("PG_WORKSPACE", "./rag_storage_other")
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    with pytest.raises(PurgeError, match="PG_WORKSPACE"):
        await dry_run(conn, identity_loader=identity_loader)


# ── edge cases and rollback ────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_legacy_table_skipped(tmp_path):
    rows = {
        "lightrag_vdb_chunks": {VIDEO: 115},
        "lightrag_vdb_entity": {VIDEO: 640},
    }
    conn = FakeConn(legacy=LEGACY_TABLES[:2], rows=rows, registrations=default_registrations())
    report = await apply(conn, backup_dir=make_backup(tmp_path, tables=LEGACY_TABLES[:2]), identity_loader=identity_loader)
    assert report["legacy_tables"] == LEGACY_TABLES[:2]
    assert report["deletions"][VIDEO] == {"lightrag_vdb_chunks": 115, "lightrag_vdb_entity": 640}
    assert report["remaining"] == {}


@pytest.mark.asyncio
async def test_verification_failure_rolls_back(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations(), delete_effective=False)
    with pytest.raises(PurgeError, match="verification failed"):
        await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)
    assert conn.rolled_back is True


# ── CLI exit codes ─────────────────────────────────────────────

def test_main_apply_and_dry_run_mutually_exclusive(capsys):
    assert main(["--apply", "--dry-run"]) == EXIT_EXPECTED
    assert "mutually exclusive" in capsys.readouterr().err


def test_main_force_without_apply_exits_2(capsys):
    assert main(["--force"]) == EXIT_EXPECTED
    assert "--force requires --apply" in capsys.readouterr().err


def test_main_apply_without_backup_dir_exits_2(capsys):
    assert main(["--apply"]) == EXIT_EXPECTED
    assert "--backup-dir" in capsys.readouterr().err


def test_main_connection_failure_is_sanitized(capsys):
    code = main([
        "--apply",
        "--backup-dir", "C:\\nonexistent\\backup",
        "--dsn", "postgresql://user:secretpw@127.0.0.1:59999/raganything",
    ])
    captured = capsys.readouterr()
    assert code == EXIT_EXPECTED
    assert "secretpw" not in captured.out + captured.err

# ?? backup gate hardening ?????????????????????????????????????

@pytest.mark.asyncio
async def test_backup_gate_rejects_suffixed_copy_in_legacy_named_file(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    for table in LEGACY_TABLES:
        (tmp_path / f"{table}.dump").write_text(
            f"COPY public.{table}_openai_compa_639985a6e4b87473_1024d (id, workspace) FROM stdin;\n\\.\n",
            encoding="utf-8",
        )
    with pytest.raises(PurgeError, match="backup gate"):
        await apply(conn, backup_dir=tmp_path, identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_backup_gate_accepts_quoted_mixed_case_table(tmp_path):
    legacy = ["Lightrag_Vdb_Chunks", "Lightrag_Vdb_Entity", "Lightrag_Vdb_Relation"]
    rows = {
        "Lightrag_Vdb_Chunks": {VIDEO: 115},
        "Lightrag_Vdb_Entity": {VIDEO: 640},
        "Lightrag_Vdb_Relation": {VIDEO: 900},
    }
    conn = FakeConn(legacy=legacy, rows=rows, registrations=default_registrations())
    for table in legacy:
        (tmp_path / f"{table}.dump").write_text(
            f'COPY public."{table}" (id, workspace) FROM stdin;\n\\N\n\\.\n',
            encoding="utf-8",
        )
    report = await apply(conn, backup_dir=tmp_path, identity_loader=identity_loader)
    assert report["deletions"][VIDEO] == {
        "Lightrag_Vdb_Chunks": 115, "Lightrag_Vdb_Entity": 640, "Lightrag_Vdb_Relation": 900,
    }


@pytest.mark.asyncio
async def test_apply_backup_dir_is_file_rejected(tmp_path):
    conn = FakeConn(rows=default_dataset(), registrations=default_registrations())
    target = tmp_path / "not-a-dir"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(PurgeError, match="backup gate"):
        await apply(conn, backup_dir=target, identity_loader=identity_loader)


# ?? identity registry hardening ???????????????????????????????

@pytest.mark.asyncio
async def test_other_registration_malformed_json_aborts(tmp_path):
    registrations = default_registrations()
    registrations["./rag_storage_autorepair"] = (HASH, "not-json")
    conn = FakeConn(rows=default_dataset(), registrations=registrations)
    with pytest.raises(PurgeError, match="inconsistent"):
        await apply(conn, backup_dir=make_backup(tmp_path), identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_authoritative_malformed_aborts():
    registrations = {"./rag_storage": (HASH, "not-json")}
    conn = FakeConn(rows=default_dataset(), registrations=registrations)
    with pytest.raises(PurgeError, match="malformed"):
        await dry_run(conn, identity_loader=identity_loader)


@pytest.mark.asyncio
async def test_authoritative_empty_hash_aborts():
    registrations = {"./rag_storage": ("", json.dumps(FIXED_IDENTITY, sort_keys=True))}
    conn = FakeConn(rows=default_dataset(), registrations=registrations)
    with pytest.raises(PurgeError, match="malformed"):
        await dry_run(conn, identity_loader=identity_loader)


# ?? sanitization ??????????????????????????????????????????????

def test_sanitize_redacts_at_password_and_malformed_dsn():
    assert "secretpw" not in _sanitize("connect failed postgresql://user:secretpw@127.0.0.1/x")
    assert "secretpw" not in _sanitize("bad dsn postgresql://user:secretpw")
    assert "p@ssword" not in _sanitize("connect failed postgresql://user:p@ssword@127.0.0.1/x")
    assert "pw" not in _sanitize("password=pw")
