"""Offline first-install reset for the RAG-Anything application.

The command is intentionally fail-closed. Running it without ``--execute``
only prints a preflight report. Destructive execution requires the exact
confirmation phrase and refuses to run while application services are active.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import psutil
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONFIRMATION_PHRASE = "ERASE-RAGANYTHING-DATA"
ADMIN_USERNAME = "admin"
CANONICAL_ROLES = {
    "super_admin",
    "dept_admin",
    "teacher",
    "assistant",
    "student",
}
PRESERVED_TABLES = {"roles", "settings", "users"}
PURGED_TABLES = {
    "agent_conversations",
    "agent_messages",
    "agents",
    "audit_logs",
    "chunk_tag_assignments",
    "conversations",
    "dashboard_query_log",
    "document_repair_jobs",
    "document_tag_jobs",
    "upload_retry_jobs",
    "embedding_cache",
    "fault_cases",
    "image_vision_vectors",
    "kb_metadata",
    "kb_tags",
    "lightrag_doc_chunks",
    "lightrag_doc_full",
    "lightrag_doc_status",
    "lightrag_entity_chunks",
    "lightrag_full_entities",
    "lightrag_full_relations",
    "lightrag_llm_cache",
    "lightrag_relation_chunks",
    "lightrag_vdb_chunks",
    "lightrag_vdb_entity",
    "lightrag_vdb_relation",
    "messages",
    "monitor_events",
    "process_documents",
    "processing_tasks",
    "query_history",
    "token_revocations",
    "uploaded_files",
    "user_entities",
    "user_relations",
    "workflow_definitions",
    "workflow_runs",
}
EXPECTED_TABLES = PRESERVED_TABLES | PURGED_TABLES
SERVICE_PORTS = (8001, 5173)
RESET_MARKER = ROOT / ".system-reset-in-progress"
LEGACY_STATE_FILES = {
    "agent_meta.json",
    "auth.db",
    "conversations.json",
    "query_history.json",
    "rag_storage_kb_meta.json",
}
EXCLUDED_CACHE_ROOTS = {
    ".agents",
    ".codex",
    ".git",
    ".venv",
    "node_modules",
    "venv",
}


class ResetRefused(RuntimeError):
    """Raised when a destructive reset precondition is not satisfied."""


class DatabaseCommitUncertain(ResetRefused):
    """Raised when PostgreSQL may already contain the reset baseline."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset all application data to a first-install baseline."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the reset; without this flag only preflight is run",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"required destructive confirmation: {CONFIRMATION_PHRASE}",
    )
    return parser.parse_args()


def _within_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _deduplicate_targets(paths: list[Path]) -> list[Path]:
    resolved = sorted(
        {path.resolve() for path in paths if path.exists()},
        key=lambda value: (len(value.parts), str(value).casefold()),
    )
    selected: list[Path] = []
    for path in resolved:
        if not _within_root(path) or path == ROOT.resolve():
            raise ResetRefused(f"unsafe reset target: {path}")
        if any(path == parent or path.is_relative_to(parent) for parent in selected):
            continue
        selected.append(path)
    return selected


def collect_reset_targets(root: Path = ROOT) -> list[Path]:
    """Return only generated application data paths beneath the workspace."""
    root = root.resolve()
    paths: list[Path] = []
    for child in root.iterdir():
        if child.is_dir() and (
            child.name == "uploads"
            or child.name == "output"
            or child.name.startswith("output_")
            or child.name == "rag_storage"
            or child.name.startswith("rag_storage_")
        ):
            paths.append(child)
        elif child.is_file() and (
            child.name in LEGACY_STATE_FILES
            or child.name.startswith("auth.db")
            or child.name == "server_output.log"
            or child.name.startswith(".tmp-")
        ):
            paths.append(child)

    for relative in (
        Path("frontend/dist"),
        Path("frontend/node_modules/.vite"),
        Path("workflows/runs"),
        Path(".pytest_cache"),
        Path(".ruff_cache"),
        Path(".mypy_cache"),
        Path("data/manufacturing_kb/dashboard/query_log.json"),
    ):
        candidate = root / relative
        if candidate.exists():
            paths.append(candidate)

    for cache_dir in root.rglob("__pycache__"):
        relative_parts = cache_dir.relative_to(root).parts
        if any(part in EXCLUDED_CACHE_ROOTS for part in relative_parts):
            continue
        paths.append(cache_dir)

    return _deduplicate_targets(paths)


def _path_size(path: Path) -> tuple[int, int]:
    if path.is_file():
        return 1, path.stat().st_size
    files = 0
    size = 0
    for child in path.rglob("*"):
        if child.is_file():
            files += 1
            try:
                size += child.stat().st_size
            except OSError:
                pass
    return files, size


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex(("127.0.0.1", port)) == 0


def _listening_ports() -> set[int]:
    ports: set[int] = set()
    try:
        for connection in psutil.net_connections(kind="inet"):
            if connection.status == psutil.CONN_LISTEN and connection.laddr:
                ports.add(int(connection.laddr.port))
    except (psutil.AccessDenied, OSError):
        pass
    return ports


def active_application_processes(root: Path = ROOT) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    root_text = str(root.resolve()).casefold()
    for process in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            command = " ".join(process.info.get("cmdline") or [])
            cwd = str(process.info.get("cwd") or "").casefold()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        lowered = command.casefold()
        application_command = "server.py" in lowered or "process_worker.py" in lowered
        frontend_command = "vite" in lowered or (
            "npm-cli.js" in lowered and "run dev" in lowered
        )
        in_workspace = (
            root_text in lowered
            or cwd == root_text
            or cwd.startswith(root_text + "\\")
        )
        if (application_command or frontend_command) and in_workspace:
            active.append({"pid": process.pid, "command": command})
    return active


def service_blockers() -> dict[str, Any]:
    listening = _listening_ports()
    return {
        "active_ports": {
            str(port): port in listening or _port_open(port) for port in SERVICE_PORTS
        },
        "active_processes": active_application_processes(),
    }


async def _connect() -> asyncpg.Connection:
    load_dotenv(ROOT / ".env", override=False)
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        raise ResetRefused("DATABASE_URL is not configured")
    return await asyncpg.connect(dsn)


async def database_preflight() -> dict[str, Any]:
    connection = await _connect()
    try:
        tables = {
            str(row["table_name"])
            for row in await connection.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
        }
        unknown = sorted(tables - EXPECTED_TABLES)
        missing = sorted(EXPECTED_TABLES - tables)
        if unknown or missing:
            raise ResetRefused(
                f"database table manifest mismatch; unknown={unknown}, missing={missing}"
            )

        admins = await connection.fetch(
            """
            SELECT u.id, u.username, u.email, u.password_hash, u.is_active,
                   u.must_change_password, r.name AS role_name
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            WHERE u.username = $1
            """,
            ADMIN_USERNAME,
        )
        if len(admins) != 1:
            raise ResetRefused(f"expected one admin user, found {len(admins)}")
        admin = dict(admins[0])
        if admin["role_name"] != "super_admin" or int(admin["is_active"] or 0) != 1:
            raise ResetRefused("admin must be active and assigned to super_admin")

        counts: dict[str, int] = {}
        for table in sorted(tables):
            counts[table] = int(
                await connection.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            )
        return {
            "tables": len(tables),
            "counts": counts,
            "admin": {
                "id": int(admin["id"]),
                "username": admin["username"],
                "email": admin["email"],
                "role": admin["role_name"],
                "must_change_password": int(admin["must_change_password"] or 0),
            },
            "password_hash": admin["password_hash"],
        }
    finally:
        await connection.close()


def build_preflight_report(
    database: dict[str, Any], targets: list[Path]
) -> dict[str, Any]:
    file_count = 0
    byte_count = 0
    for target in targets:
        files, size = _path_size(target)
        file_count += files
        byte_count += size
    blockers = service_blockers()
    stale_stages = sorted(path.name for path in ROOT.glob(".system-reset-staging-*"))
    return {
        "mode": "preflight",
        "database_tables": database["tables"],
        "database_nonempty": {
            key: value for key, value in database["counts"].items() if value
        },
        "preserved_admin": database["admin"],
        "disk_targets": len(targets),
        "disk_files": file_count,
        "disk_bytes": byte_count,
        **blockers,
        "stale_staging_directories": stale_stages,
        "execution_blocked": (
            any(blockers["active_ports"].values())
            or bool(blockers["active_processes"])
            or bool(stale_stages)
            or RESET_MARKER.exists()
        ),
    }


def _stage_targets(targets: list[Path]) -> tuple[Path, list[tuple[Path, Path]]]:
    stage = ROOT / f".system-reset-staging-{uuid.uuid4().hex}"
    stage.mkdir(parents=False, exist_ok=False)
    moved: list[tuple[Path, Path]] = []
    try:
        for source in targets:
            relative = source.relative_to(ROOT)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            moved.append((source, destination))
    except Exception:
        _restore_targets(moved, stage)
        raise
    return stage, moved


def _restore_targets(moved: list[tuple[Path, Path]], stage: Path) -> None:
    for original, staged in reversed(moved):
        if not staged.exists():
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(original)
    shutil.rmtree(stage, ignore_errors=True)


def _purge_stage(stage: Path) -> None:
    """Permanently remove transactional staging; never retain it as a backup."""
    last_error: OSError | None = None
    for _attempt in range(3):
        try:
            shutil.rmtree(stage)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
    raise ResetRefused(f"unable to purge reset staging directory: {last_error}")


def _acquire_reset_marker() -> None:
    try:
        with RESET_MARKER.open("x", encoding="utf-8") as marker:
            marker.write(f"pid={os.getpid()}\n")
    except FileExistsError as exc:
        raise ResetRefused(f"reset marker already exists: {RESET_MARKER}") from exc


async def reset_database(preflight: dict[str, Any]) -> dict[str, Any]:
    from raganything.permissions import DEFAULT_ROLES

    connection = await _connect()
    new_server_start_id = uuid.uuid4().hex
    new_data_epoch = uuid.uuid4().hex
    admin_id = int(preflight["admin"]["id"])
    original_hash = str(preflight["password_hash"])
    default_agent_id = "default"
    body_finished = False
    transaction_error: Exception | None = None
    try:
        async with connection.transaction(isolation="serializable"):
            await connection.execute("SELECT pg_advisory_xact_lock($1)", 714_620_260)
            current_tables = {
                str(row["table_name"])
                for row in await connection.fetch(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    """
                )
            }
            if current_tables != EXPECTED_TABLES:
                raise ResetRefused(
                    "database table manifest changed after preflight; reset aborted"
                )
            current_hash = await connection.fetchval(
                "SELECT password_hash FROM users WHERE id = $1 AND username = $2",
                admin_id,
                ADMIN_USERNAME,
            )
            if current_hash != original_hash:
                raise ResetRefused("admin changed after preflight; reset aborted")

            table_sql = ", ".join(f'"{name}"' for name in sorted(PURGED_TABLES))
            await connection.execute(
                f"TRUNCATE TABLE {table_sql} RESTART IDENTITY CASCADE"
            )
            await connection.execute("DELETE FROM users WHERE id <> $1", admin_id)

            for role_name, role in DEFAULT_ROLES.items():
                await connection.execute(
                    """
                    INSERT INTO roles (name, description, permissions)
                    VALUES ($1, $2, $3::jsonb)
                    ON CONFLICT (name) DO UPDATE SET
                        description = EXCLUDED.description,
                        permissions = EXCLUDED.permissions
                    """,
                    role_name,
                    role["description"],
                    json.dumps(role["permissions"], ensure_ascii=False),
                )
            await connection.execute(
                "DELETE FROM roles WHERE NOT (name = ANY($1::text[]))",
                sorted(CANONICAL_ROLES),
            )
            super_admin_id = await connection.fetchval(
                "SELECT id FROM roles WHERE name = 'super_admin'"
            )
            await connection.execute(
                """
                UPDATE users
                SET role_id = $2, is_active = 1, failed_login_attempts = 0,
                    locked_until = NULL, last_login_at = NULL, updated_at = NOW()
                WHERE id = $1
                """,
                admin_id,
                super_admin_id,
            )

            await connection.execute(
                """
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                "server_start_id",
                new_server_start_id,
            )
            await connection.execute(
                """
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                "system_data_epoch",
                new_data_epoch,
            )

            now = datetime.now(timezone.utc)
            await connection.execute(
                """
                INSERT INTO kb_metadata (
                    name, display_name, domain, description, owner_id,
                    owner_username, status, document_count, extra,
                    created_at, updated_at
                ) VALUES (
                    'default', '默认知识库', 'general', '', $1,
                    $2, 'ready', 0, '{}'::jsonb, $3, $3
                )
                """,
                admin_id,
                ADMIN_USERNAME,
                now,
            )
            await connection.execute(
                """
                INSERT INTO agents (
                    id, name, icon, description, welcome_message,
                    kb_name, llm_model, system_prompt, use_default_prompt,
                    owner_id, owner_username, created_at, updated_at
                ) VALUES (
                    $1, '通用助手', '🤖', '默认智能体，关联默认知识库',
                    '你好！我是通用助手，可以回答知识库中的任何问题。',
                    'default', $2, '', TRUE, $3, $4, $5, $5
                )
                """,
                default_agent_id,
                os.getenv("LLM_MODEL", "qwen-plus"),
                admin_id,
                ADMIN_USERNAME,
                now,
            )

            await connection.execute(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), $1, true)",
                admin_id,
            )
            max_role_id = int(await connection.fetchval("SELECT MAX(id) FROM roles"))
            await connection.execute(
                "SELECT setval(pg_get_serial_sequence('roles', 'id'), $1, true)",
                max_role_id,
            )

            validation = await connection.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS users,
                    (SELECT COUNT(*) FROM roles) AS roles,
                    (SELECT COUNT(*) FROM kb_metadata) AS knowledge_bases,
                    (SELECT COUNT(*) FROM agents) AS agents,
                    (SELECT password_hash FROM users WHERE id = $1) AS password_hash
                """,
                admin_id,
            )
            if (
                int(validation["users"]) != 1
                or int(validation["roles"]) != len(CANONICAL_ROLES)
                or int(validation["knowledge_bases"]) != 1
                or int(validation["agents"]) != 1
                or validation["password_hash"] != original_hash
            ):
                raise ResetRefused(f"baseline validation failed: {dict(validation)}")
            body_finished = True
    except Exception as exc:
        transaction_error = exc

    close_error: Exception | None = None
    try:
        await connection.close()
    except Exception as exc:
        close_error = exc

    if transaction_error is not None:
        if body_finished:
            raise DatabaseCommitUncertain(
                "database commit outcome is uncertain; reset marker retained"
            ) from transaction_error
        raise transaction_error
    if close_error is not None:
        raise DatabaseCommitUncertain(
            "database committed but connection cleanup failed; reset marker retained"
        ) from close_error

    return {
        "admin_id": admin_id,
        "server_start_id": new_server_start_id,
        "system_data_epoch": new_data_epoch,
        "default_agent_id": default_agent_id,
    }


def _write_kb_mirror(admin_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "default": {
            "name": "默认知识库",
            "created": now,
            "domain": "general",
            "description": "",
            "owner_id": admin_id,
            "owner_username": ADMIN_USERNAME,
            "status": "ready",
            "document_count": 0,
            "updated_at": now,
            "extra": {},
        }
    }
    destination = ROOT / "rag_storage_kb_meta.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


async def _post_reset_audit(admin_id: int, password_hash: str) -> dict[str, Any]:
    connection = await _connect()
    try:
        counts = {
            table: int(await connection.fetchval(f'SELECT COUNT(*) FROM "{table}"'))
            for table in sorted(EXPECTED_TABLES)
        }
        preserved_hash = await connection.fetchval(
            "SELECT password_hash FROM users WHERE id = $1", admin_id
        )
        expected = {table: 0 for table in PURGED_TABLES}
        expected["kb_metadata"] = 1
        expected["agents"] = 1
        violations = {
            table: counts[table]
            for table, expected_count in expected.items()
            if counts[table] != expected_count
        }
        if counts["users"] != 1 or counts["roles"] != len(CANONICAL_ROLES):
            violations.update(users=counts["users"], roles=counts["roles"])
        if preserved_hash != password_hash:
            violations["admin_password_hash"] = "changed"
        if violations:
            raise ResetRefused(f"post-reset audit failed: {violations}")
        return counts
    finally:
        await connection.close()


async def main() -> int:
    args = _parse_args()
    database = await database_preflight()
    targets = collect_reset_targets()
    report = build_preflight_report(database, targets)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0
    if args.confirm != CONFIRMATION_PHRASE:
        raise ResetRefused(
            f"destructive execution requires --confirm {CONFIRMATION_PHRASE}"
        )
    if report["execution_blocked"]:
        raise ResetRefused(
            "execution is blocked by active services, a reset marker, or stale staging"
        )

    # Close the preflight-to-mutation race. The server also refuses startup
    # while this marker exists.
    blockers = service_blockers()
    if any(blockers["active_ports"].values()) or blockers["active_processes"]:
        raise ResetRefused(f"application services restarted after preflight: {blockers}")
    _acquire_reset_marker()
    stage: Path | None = None
    moved: list[tuple[Path, Path]] = []
    database_committed = False
    marker_can_clear = False
    try:
        stage, moved = _stage_targets(targets)
        try:
            reset_result = await reset_database(database)
        except DatabaseCommitUncertain:
            database_committed = True
            # PostgreSQL may already contain the new baseline. Never retain or
            # restore the staged old data in this state.
            _purge_stage(stage)
            raise
        database_committed = True
        try:
            _write_kb_mirror(int(reset_result["admin_id"]))
            counts = await _post_reset_audit(
                int(reset_result["admin_id"]), str(database["password_hash"])
            )
        finally:
            # Once PG commits, old files must never be restored or retained.
            _purge_stage(stage)
        marker_can_clear = True
    except Exception:
        if not database_committed and stage is not None:
            _restore_targets(moved, stage)
        if not database_committed:
            # Staging failures restore internally. Keep the marker if any
            # rollback directory remains, because recovery is incomplete.
            marker_can_clear = not any(ROOT.glob(".system-reset-staging-*"))
        raise
    finally:
        if marker_can_clear:
            RESET_MARKER.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "status": "reset_complete",
                "admin_id": reset_result["admin_id"],
                "system_data_epoch": reset_result["system_data_epoch"],
                "knowledge_bases": counts["kb_metadata"],
                "agents": counts["agents"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except ResetRefused as exc:
        print(f"RESET REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
