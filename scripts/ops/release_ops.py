"""Secret-safe release backup, restore, and validation helpers.

This module deliberately uses only the standard library. Deployment wrappers
provide PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSFILE; passwords and DSNs are not
accepted as arguments and are never serialized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

MANIFEST_VERSION = 1
ROLE_NAMES = {"super_admin", "dept_admin", "teacher", "assistant", "student"}
SECRET_WORDS = ("password", "secret", "token", "api_key", "dsn", "database_url")


class OpsError(RuntimeError):
    """An operation refused an unsafe configuration or incomplete bundle."""


def utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_link_or_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)


def _public_error(text: str) -> str:
    """Keep command results useful without publishing secret-bearing text."""
    lowered = text.lower()
    return "command failed (details redacted)" if any(word in lowered for word in SECRET_WORDS) else text[:240]


def load_config(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise OpsError("unsupported operations config schema")
    def reject_secrets(value: Any, key: str = "") -> None:
        if any(word in key.lower() for word in SECRET_WORDS):
            raise OpsError("operations config must contain references, not secrets")
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                reject_secrets(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                reject_secrets(child)
    reject_secrets(raw)
    if not isinstance(raw.get("assets"), list) or not raw["assets"]:
        raise OpsError("config requires declared assets")
    return raw


def validated_assets(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve only declared, non-overlapping directory assets."""
    assets: list[dict[str, Any]] = []
    seen: list[Path] = []
    for item in config["assets"]:
        required = {"id", "classification"}
        if not required.issubset(item):
            raise OpsError("asset is missing id or classification")
        classification = item["classification"]
        if classification not in {"include", "reproducible", "externally_owned", "rebuildable"}:
            raise OpsError("invalid asset classification")
        if classification != "include":
            if classification == "externally_owned" and not item.get("owner"):
                raise OpsError("externally owned asset requires owner")
            assets.append({"id": item["id"], "classification": classification, "owner": item.get("owner", "")})
            continue
        source = _resolved(item.get("path", ""))
        if not source.is_dir() or _is_link_or_reparse(source):
            raise OpsError("included asset must be a real directory")
        if any(_inside(source, other) or _inside(other, source) for other in seen):
            raise OpsError("asset paths must not overlap")
        seen.append(source)
        assets.append({"id": item["id"], "classification": classification, "source": source})
    return assets


def _safe_archive(source: Path, target: Path) -> tuple[int, int]:
    """Archive a root without following links and without recording filenames in metadata."""
    count = total = 0
    with tarfile.open(target, "w:gz", dereference=False) as archive:
        for entry in source.rglob("*"):
            if _is_link_or_reparse(entry):
                raise OpsError("asset contains link or reparse point")
            if entry.is_file():
                relative = entry.relative_to(source).as_posix()
                archive.add(entry, arcname=relative, recursive=False)
                count += 1
                total += entry.stat().st_size
    return count, total


def _pg_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSFILE")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise OpsError("missing PostgreSQL connection environment references")
    # Keep the process-launch variables required by Windows and POSIX clients;
    # PostgreSQL connection material remains limited to the explicit PG* refs.
    process_env = dict(os.environ)
    process_keys = ("PATH", "SystemRoot", "TEMP", "TMP", "HOME", "LANG", "LC_ALL")
    for key in process_keys:
        value = env.get(key)
        if value is None:
            value = next(
                (candidate for name, candidate in env.items() if name.lower() == key.lower()),
                None,
            )
        if value:
            process_env[key] = value
    process_env.update({key: env[key] for key in required})
    return process_env


def _run(command: list[str], env: dict[str, str], runner: Callable[..., Any] = subprocess.run) -> None:
    try:
        result = runner(command, env=env, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise OpsError("database command could not start") from exc
    if result.returncode:
        raise OpsError(_public_error(str(getattr(result, "stderr", ""))))


def create_backup(config_path: str | Path, backup_root: str | Path, *, runner: Callable[..., Any] = subprocess.run, now: str | None = None) -> Path:
    config = load_config(config_path)
    assets = validated_assets(config)
    root = _resolved(backup_root)
    live_paths = [asset["source"] for asset in assets if "source" in asset]
    if any(_inside(root, live) or _inside(live, root) for live in live_paths):
        raise OpsError("backup root must not overlap live assets")
    root.mkdir(parents=True, exist_ok=True)
    stamp = (now or utcnow()).replace(":", "").replace("+", "_").replace("Z", "Z")
    final = root / f"release-backup-{stamp}"
    if final.exists():
        raise OpsError("backup identifier already exists")
    stage = Path(tempfile.mkdtemp(prefix=".release-backup-", dir=root))
    os.chmod(stage, 0o700)
    try:
        dump = stage / "postgres.dump"
        _run([config.get("pg_dump_command", "pg_dump"), "--format=custom", "--file", str(dump)], _pg_env(), runner)
        artifacts = [{"kind": "postgresql", "path": dump.name, "bytes": dump.stat().st_size, "sha256": sha256(dump)}]
        for asset in assets:
            if asset.get("classification") != "include":
                continue
            archive = stage / f"asset-{asset['id']}.tar.gz"
            count, total = _safe_archive(asset["source"], archive)
            artifacts.append({"kind": "asset", "id": asset["id"], "path": archive.name, "bytes": archive.stat().st_size, "sha256": sha256(archive), "file_count": count, "source_bytes": total})
        manifest = {"schema_version": MANIFEST_VERSION, "created_at": utcnow(), "backup_id": final.name, "artifacts": artifacts, "asset_policy": [{k: str(v) for k, v in asset.items() if k in {"id", "classification", "owner"}} for asset in assets]}
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify_bundle(stage)
        stage.rename(final)
        return final
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_bundle(bundle: str | Path) -> dict[str, Any]:
    root = _resolved(bundle)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise OpsError("bundle manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_VERSION or not isinstance(manifest.get("artifacts"), list):
        raise OpsError("invalid bundle manifest")
    for artifact in manifest["artifacts"]:
        name = artifact.get("path", "")
        target = root / name
        if Path(name).name != name or not target.is_file():
            raise OpsError("bundle artifact is missing or unsafe")
        if target.stat().st_size != artifact.get("bytes") or sha256(target) != artifact.get("sha256"):
            raise OpsError("bundle checksum verification failed")
    return manifest


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if member.islnk() or member.issym() or pure.is_absolute() or ".." in pure.parts or not member.isfile():
                raise OpsError("unsafe archive member")
            target = (destination / Path(*pure.parts)).resolve(strict=False)
            if not _inside(target, destination):
                raise OpsError("archive member escapes isolated root")
        # Members were fully validated above. Extract one at a time for Python
        # 3.10 compatibility, where tarfile's extraction filters are absent.
        for member in archive.getmembers():
            archive.extract(member, destination)


def restore_bundle(bundle: str | Path, isolated_root: str | Path, *, confirm: str, isolated_pg_database: str, production_pg_database: str = "", runner: Callable[..., Any] = subprocess.run) -> Path:
    manifest = verify_bundle(bundle)
    source = _resolved(bundle)
    target = _resolved(isolated_root)
    if (
        not confirm
        or confirm != manifest["backup_id"]
        or target == source
        or not production_pg_database
        or isolated_pg_database == production_pg_database
    ):
        raise OpsError("isolated restore confirmation or database target rejected")
    if target.exists() and any(target.iterdir()):
        raise OpsError("isolated root must be empty")
    target.mkdir(parents=True, exist_ok=True)
    marker = target / ".release-restore-isolated"
    marker.write_text(manifest["backup_id"] + "\n", encoding="utf-8")
    try:
        for artifact in manifest["artifacts"]:
            artifact_path = source / artifact["path"]
            if artifact["kind"] == "asset":
                dest = target / "assets" / artifact["id"]
                dest.mkdir(parents=True)
                _safe_extract(artifact_path, dest)
            elif artifact["kind"] == "postgresql":
                env = _pg_env()
                env["PGDATABASE"] = isolated_pg_database
                _run(["pg_restore", "--clean", "--if-exists", "--dbname", isolated_pg_database, str(artifact_path)], env, runner)
        return target
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def validate_restored_inventory(inventory_path: str | Path, restored_root: str | Path) -> dict[str, Any]:
    """Validate a sanitized aggregate inventory produced by the isolated checker."""
    root = _resolved(restored_root)
    data = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    if not ROLE_NAMES.issubset(set(data.get("roles", []))): issues.append("rbac_roles")
    if not data.get("audit_table") or not data.get("token_revocation_table"): issues.append("audit_or_revocation")
    for ref in data.get("references", []):
        path = _resolved(root / ref["path"])
        allowed = _resolved(root / ref["root"])
        if not _inside(path, allowed) or not path.exists(): issues.append(ref.get("kind", "reference"))
    return {"status": "ok" if not issues else "failed", "issues": sorted(set(issues)), "checked_at": utcnow()}


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG-Anything release operations")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup"); backup.add_argument("--config", required=True); backup.add_argument("--backup-root", required=True)
    verify = sub.add_parser("verify"); verify.add_argument("--bundle", required=True)
    restore = sub.add_parser("restore"); restore.add_argument("--bundle", required=True); restore.add_argument("--isolated-root", required=True); restore.add_argument("--confirm-backup-id", required=True); restore.add_argument("--isolated-pg-database", required=True); restore.add_argument("--production-pg-database", required=True)
    validate = sub.add_parser("validate"); validate.add_argument("--inventory", required=True); validate.add_argument("--restored-root", required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup": result = {"bundle": str(create_backup(args.config, args.backup_root))}
        elif args.command == "verify": result = {"status": "ok", "backup_id": verify_bundle(args.bundle)["backup_id"]}
        elif args.command == "restore": result = {"isolated_root": str(restore_bundle(args.bundle, args.isolated_root, confirm=args.confirm_backup_id, isolated_pg_database=args.isolated_pg_database, production_pg_database=args.production_pg_database))}
        else: result = validate_restored_inventory(args.inventory, args.restored_root)
        print(json.dumps(result, sort_keys=True))
    except (OpsError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "reason": _public_error(str(exc))}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
