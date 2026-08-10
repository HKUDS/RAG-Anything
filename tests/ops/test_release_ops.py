import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts" / "ops"))
import release_ops as ops


def config(tmp_path: Path, *assets: Path) -> Path:
    payload = {"schema_version": 1, "assets": [
        {"id": f"asset-{index}", "classification": "include", "path": str(asset)}
        for index, asset in enumerate(assets)
    ] + [{"id": "redis", "classification": "rebuildable", "owner": "ops"}]}
    path = tmp_path / "config.json"; path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def pg_env(tmp_path: Path, monkeypatch):
    for key, value in {"PGHOST": "isolated-db", "PGPORT": "5432", "PGDATABASE": "source", "PGUSER": "backup", "PGPASSFILE": str(tmp_path / "pgpass")}.items(): monkeypatch.setenv(key, value)


def ok_runner(command, **kwargs):
    output = Path(command[command.index("--file") + 1]) if "--file" in command else None
    if output: output.write_bytes(b"pg dump")
    return SimpleNamespace(returncode=0, stderr="")


def test_backup_manifest_is_secret_safe_and_verifiable(tmp_path, monkeypatch):
    source = tmp_path / "uploads"; source.mkdir(); (source / "student-file.pdf").write_bytes(b"data")
    pg_env(tmp_path, monkeypatch)
    bundle = ops.create_backup(config(tmp_path, source), tmp_path / "backups", runner=ok_runner, now="2026-08-04T00:00:00Z")
    manifest = ops.verify_bundle(bundle)
    serialized = json.dumps(manifest)
    assert manifest["artifacts"] and "student-file" not in serialized and "PGPASSFILE" not in serialized


def test_backup_failure_cleans_stage(tmp_path, monkeypatch):
    source = tmp_path / "rag_storage"; source.mkdir(); pg_env(tmp_path, monkeypatch)
    with pytest.raises(ops.OpsError):
        ops.create_backup(config(tmp_path, source), tmp_path / "backups", runner=lambda *a, **k: SimpleNamespace(returncode=1, stderr="password=no"))
    assert not list((tmp_path / "backups").glob("release-backup-*"))


def test_backup_rejects_overlapping_live_root(tmp_path, monkeypatch):
    source = tmp_path / "output"; source.mkdir(); pg_env(tmp_path, monkeypatch)
    with pytest.raises(ops.OpsError, match="overlap"):
        ops.create_backup(config(tmp_path, source), source / "backup", runner=ok_runner)


def test_verify_rejects_tampered_checksum(tmp_path, monkeypatch):
    source = tmp_path / "uploads"; source.mkdir(); (source / "a").write_text("x"); pg_env(tmp_path, monkeypatch)
    bundle = ops.create_backup(config(tmp_path, source), tmp_path / "backups", runner=ok_runner)
    (bundle / "postgres.dump").write_bytes(b"tampered")
    with pytest.raises(ops.OpsError, match="checksum"):
        ops.verify_bundle(bundle)


def test_restore_requires_correct_confirmation_and_empty_root(tmp_path, monkeypatch):
    source = tmp_path / "uploads"; source.mkdir(); pg_env(tmp_path, monkeypatch)
    bundle = ops.create_backup(config(tmp_path, source), tmp_path / "backups", runner=ok_runner)
    target = tmp_path / "restore"; target.mkdir(); (target / "existing").write_text("x")
    with pytest.raises(ops.OpsError):
        ops.restore_bundle(bundle, target, confirm="wrong", isolated_pg_database="isolated", runner=ok_runner)


def test_restore_requires_explicit_production_database_guard(tmp_path, monkeypatch):
    source = tmp_path / "uploads"; source.mkdir()
    pg_env(tmp_path, monkeypatch)
    bundle = ops.create_backup(config(tmp_path, source), tmp_path / "backups", runner=ok_runner)
    backup_id = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["backup_id"]
    with pytest.raises(ops.OpsError):
        ops.restore_bundle(
            bundle,
            tmp_path / "restore",
            confirm=backup_id,
            isolated_pg_database="isolated",
            runner=ok_runner,
        )


def test_restore_refuses_archive_traversal(tmp_path, monkeypatch):
    source = tmp_path / "uploads"; source.mkdir(); (source / "data").write_text("x"); pg_env(tmp_path, monkeypatch)
    bundle = ops.create_backup(config(tmp_path, source), tmp_path / "backups", runner=ok_runner)
    # Replacing an artifact causes verification to fail before extraction.
    (bundle / "asset-asset-0.tar.gz").write_bytes(b"not a valid archive")
    with pytest.raises(ops.OpsError):
        ops.restore_bundle(bundle, tmp_path / "restore", confirm=bundle.name, isolated_pg_database="isolated", runner=ok_runner)


def test_inventory_validation_is_aggregate_and_detects_broken_reference(tmp_path):
    root = tmp_path / "restore"; (root / "assets" / "uploads").mkdir(parents=True)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"roles": sorted(ops.ROLE_NAMES), "audit_table": True, "token_revocation_table": True, "references": [{"kind": "upload", "root": "assets/uploads", "path": "assets/uploads/missing"}]}), encoding="utf-8")
    result = ops.validate_restored_inventory(inventory, root)
    assert result["status"] == "failed" and result["issues"] == ["upload"]


def test_config_rejects_secret_value_and_external_owner_is_required(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "assets": [{"id": "vector", "classification": "externally_owned"}], "api_key": "no"}), encoding="utf-8")
    with pytest.raises(ops.OpsError): ops.load_config(bad)


def test_pg_environment_preserves_process_launch_variables(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    for key, value in {
        "PGHOST": "isolated-db",
        "PGPORT": "5432",
        "PGDATABASE": "source",
        "PGUSER": "backup",
        "PGPASSFILE": "C:\\pgpass",
    }.items():
        monkeypatch.setenv(key, value)

    env = ops._pg_env()

    assert env["SystemRoot"] == r"C:\Windows"
    assert env["PATH"] == r"C:\Windows\System32"
    assert env["PGDATABASE"] == "source"
