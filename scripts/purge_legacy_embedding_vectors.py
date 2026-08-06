"""One-time ops script: purge legacy unsuffixed LightRAG vector rows.

Discovers the legacy vector tables (``LIGHTRAG_VDB_CHUNKS/ENTITY/RELATION``)
case-insensitively, reports a row-count baseline per table x workspace
(``--dry-run``, the default), and in ``--apply`` mode registers the canonical
text-embedding identity for each affected workspace and deletes its legacy
vector rows inside a single transaction.

Safety gates:
- ``--apply`` requires ``--backup-dir`` with a non-empty, COPY-bearing dump
  file per existing legacy table.
- A workspace with rows in suffixed vector tables is skipped unless ``--force``.
- The authoritative identity is the ``./rag_storage`` registration and must
  match the runtime embedding env exactly.
- ``PG_WORKSPACE`` must not be set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import asyncpg

LEGACY_VECTOR_TABLES = (
    "LIGHTRAG_VDB_CHUNKS",
    "LIGHTRAG_VDB_ENTITY",
    "LIGHTRAG_VDB_RELATION",
)
IDENTITY_SOURCE_WORKSPACE = "./rag_storage"
_IDENTITY_KEYS = (
    "schema_version", "provider", "model", "dimension",
    "endpoint_semantics", "endpoint_fingerprint", "identity_hash",
    "table_suffix", "model_name",
)
_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+$")

EXIT_OK = 0
EXIT_EXPECTED = 2
EXIT_UNEXPECTED = 1

IdentityLoader = Callable[[], dict[str, Any]]


class PurgeError(Exception):
    """Expected failure; the message is safe to print."""


def _sanitize(message: str) -> str:
    message = re.sub(r"(postgres(?:ql)?://)[^\s]+", r"\1***", message)
    message = re.sub(r"(password[=:]\s*)[^\s,;]+", r"\1***", message, flags=re.IGNORECASE)
    return message


def _assert_pg_workspace_clean() -> None:
    override = str(os.getenv("PG_WORKSPACE") or "").strip()
    if override:
        raise PurgeError("PG_WORKSPACE is set; refusing to run to avoid workspace override ambiguity")


def resolve_dsn(override: str | None = None) -> str:
    if override:
        return override
    dsn = os.getenv("DATABASE_URL", "").strip()
    if dsn:
        return dsn
    user = os.getenv("POSTGRES_USER", "raganything")
    password = os.getenv("POSTGRES_PASSWORD", "raganything")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DATABASE", os.getenv("POSTGRES_DB", "raganything"))
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _normalize_identity(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _env_identity() -> dict[str, Any]:
    import warnings
    from raganything.embedding.identity import text_embedding_identity_from_environment
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="pkg_resources is deprecated.*")
        return text_embedding_identity_from_environment()


# ── discovery ──────────────────────────────────────────────────

async def _resolve_legacy_table(conn, requested: str) -> str | None:
    row = await conn.fetchrow(
        "SELECT t.table_name FROM information_schema.tables t "
        "WHERE t.table_schema='public' AND lower(t.table_name)=lower($1) "
        "AND EXISTS (SELECT 1 FROM information_schema.columns c "
        "WHERE c.table_schema='public' AND c.table_name=t.table_name "
        "AND c.column_name='workspace') "
        "LIMIT 1",
        requested,
    )
    if row is None:
        return None
    actual = str(row["table_name"])
    return actual if _SAFE_TABLE_NAME.fullmatch(actual) else None


async def _resolve_legacy_tables(conn) -> list[str]:
    tables = []
    for requested in LEGACY_VECTOR_TABLES:
        actual = await _resolve_legacy_table(conn, requested)
        if actual is not None:
            tables.append(actual)
    return tables


async def _discover_vector_tables(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT c.relname AS table_name FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname ILIKE 'LIGHTRAG_VDB_%' AND c.relkind='r' "
        "ORDER BY c.relname"
    )
    tables = []
    for row in rows:
        name = str(row["table_name"])
        if not _SAFE_TABLE_NAME.fullmatch(name):
            continue
        has_workspace = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns c "
            "WHERE c.table_schema='public' AND c.table_name=$1 AND c.column_name='workspace' LIMIT 1",
            name,
        )
        if has_workspace:
            tables.append(name)
    return tables


async def _resolve_suffixed_tables(conn, legacy_tables: list[str]) -> list[str]:
    legacy_set = {table.lower() for table in legacy_tables}
    return [table for table in await _discover_vector_tables(conn) if table.lower() not in legacy_set]


# ── row counts and identity ────────────────────────────────────

async def _legacy_rows(conn, table: str, workspace: str) -> int:
    return int(await conn.fetchval(f'SELECT COUNT(*) FROM "{table}" WHERE workspace=$1', workspace) or 0)


async def _table_rows(conn, table: str) -> dict[str, int]:
    rows = await conn.fetch(f'SELECT workspace, COUNT(*) AS n FROM "{table}" GROUP BY workspace ORDER BY workspace')
    return {str(row["workspace"]): int(row["n"]) for row in rows}


async def _collect_baseline(conn, legacy_tables: list[str], suffixed_tables: list[str]) -> dict[str, Any]:
    legacy_rows = {table: await _table_rows(conn, table) for table in legacy_tables}
    suffixed_rows = {table: await _table_rows(conn, table) for table in suffixed_tables}
    affected = sorted({workspace for rows in legacy_rows.values() for workspace in rows})
    return {
        "legacy_rows": legacy_rows,
        "suffixed_rows": suffixed_rows,
        "affected_workspaces": affected,
    }


async def _load_authoritative_identity(conn) -> dict[str, Any]:
    rows = await conn.fetch(
        "SELECT workspace, identity_hash, identity FROM kb_text_embedding_identities ORDER BY workspace"
    )
    source = next((row for row in rows if str(row["workspace"]) == IDENTITY_SOURCE_WORKSPACE), None)
    if source is None:
        raise PurgeError(
            f"identity source missing: {IDENTITY_SOURCE_WORKSPACE!r} is not registered "
            "in kb_text_embedding_identities; aborting"
        )
    authoritative = _normalize_identity(source["identity"])
    authoritative_hash = str(authoritative.get("identity_hash") or "") if authoritative else ""
    if authoritative is None or not authoritative_hash or str(source["identity_hash"]) != authoritative_hash:
        raise PurgeError(f"identity source registration for {IDENTITY_SOURCE_WORKSPACE!r} is malformed")
    for row in rows:
        if str(row["workspace"]) == IDENTITY_SOURCE_WORKSPACE:
            continue
        other = _normalize_identity(row["identity"])
        other_hash = str(other.get("identity_hash") or "") if other else ""
        if (
            other is None
            or other_hash != authoritative_hash
            or str(row["identity_hash"]) != authoritative_hash
        ):
            raise PurgeError(
                f"embedding registry inconsistent: workspace {row['workspace']!r} is registered "
                "with a different or malformed identity; aborting"
            )
    return authoritative


def _assert_identity_matches(identity: Mapping[str, Any], authoritative: Mapping[str, Any]) -> None:
    missing = [key for key in _IDENTITY_KEYS if key not in identity]
    if missing:
        raise PurgeError(f"identity invalid: missing keys {missing}")
    if any(str(identity.get(key)) != str(authoritative.get(key)) for key in _IDENTITY_KEYS):
        raise PurgeError(
            "identity env mismatch: computed identity differs from the registered "
            f"authoritative identity ({IDENTITY_SOURCE_WORKSPACE!r}); run with the same "
            "EMBEDDING_PROVIDER/EMBEDDING_MODEL/EMBEDDING_DIM and "
            "EMBEDDING_ENDPOINT_SEMANTICS or LLM_BINDING_HOST as production"
        )


# ── backup gate ────────────────────────────────────────────────

_TABLE_REF = re.compile(r'^copy public\.(?:\"([^\"]+)\"|([a-z0-9_]+))(?=\s|\()', re.IGNORECASE)


def _dump_covers_table(file_text: str, table: str) -> bool:
    target = table.lower()
    for line in file_text.splitlines():
        match = _TABLE_REF.match(line.strip())
        if not match:
            continue
        physical = match.group(1) or match.group(2)
        if physical.lower() == target:
            return True
    return False


def _verify_backup_gate(backup_dir: str | Path, legacy_tables: list[str]) -> None:
    directory = Path(backup_dir)
    problems = []
    for table in legacy_tables:
        dump = directory / f"{table}.dump"
        if not dump.is_file() or dump.stat().st_size == 0:
            problems.append(f"{dump} (missing or empty)")
            continue
        text = dump.read_text(encoding="utf-8", errors="replace")
        if not _dump_covers_table(text, table):
            problems.append(f"{dump} (no COPY data for {table})")
    if problems:
        raise PurgeError("backup gate failed: " + "; ".join(problems))


# ── modes ──────────────────────────────────────────────────────

async def dry_run(conn, *, identity_loader: IdentityLoader | None = None) -> dict[str, Any]:
    _assert_pg_workspace_clean()
    legacy_tables = await _resolve_legacy_tables(conn)
    suffixed_tables = await _resolve_suffixed_tables(conn, legacy_tables)
    baseline = await _collect_baseline(conn, legacy_tables, suffixed_tables)
    authoritative = await _load_authoritative_identity(conn)
    identity = (identity_loader or _env_identity)()
    _assert_identity_matches(identity, authoritative)
    return {
        "mode": "dry-run",
        "legacy_tables": legacy_tables,
        "suffixed_tables": suffixed_tables,
        "baseline": baseline["legacy_rows"],
        "suffixed_rows": baseline["suffixed_rows"],
        "affected_workspaces": baseline["affected_workspaces"],
        "identity_hash": str(identity.get("identity_hash") or ""),
    }


async def apply(
    conn,
    *,
    backup_dir: str | Path,
    force: bool = False,
    identity_loader: IdentityLoader | None = None,
) -> dict[str, Any]:
    _assert_pg_workspace_clean()
    if not backup_dir:
        raise PurgeError("--apply requires --backup-dir with verified pg_dump files")
    legacy_tables = await _resolve_legacy_tables(conn)
    suffixed_tables = await _resolve_suffixed_tables(conn, legacy_tables)
    _verify_backup_gate(backup_dir, legacy_tables)

    deletions: dict[str, dict[str, int]] = {}
    registrations: dict[str, str] = {}
    remaining: dict[str, dict[str, int]] = {}

    async with conn.transaction():
        authoritative = await _load_authoritative_identity(conn)
        identity = (identity_loader or _env_identity)()
        _assert_identity_matches(identity, authoritative)
        baseline = await _collect_baseline(conn, legacy_tables, suffixed_tables)
        affected = baseline["affected_workspaces"]
        workspaces_with_suffixed = sorted(
            {workspace for rows in baseline["suffixed_rows"].values() for workspace in rows}
        )
        needs_force = sorted(set(affected) & set(workspaces_with_suffixed))
        if needs_force and not force:
            raise PurgeError(
                "workspaces have rows in suffixed vector tables; pass --force to allow "
                "purging their legacy rows: " + ", ".join(needs_force)
            )

        for workspace in affected:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", workspace)
            row = await conn.fetchrow(
                "SELECT identity_hash, identity FROM kb_text_embedding_identities "
                "WHERE workspace=$1 FOR UPDATE",
                workspace,
            )
            if row is None:
                await conn.execute(
                    "INSERT INTO kb_text_embedding_identities(workspace,identity_hash,identity) "
                    "VALUES($1,$2,$3::jsonb)",
                    workspace,
                    str(identity.get("identity_hash") or ""),
                    json.dumps(dict(identity), sort_keys=True),
                )
                registrations[workspace] = "INSERTED"
            else:
                stored = _normalize_identity(row["identity"])
                if (
                    str(row["identity_hash"]) != str(identity.get("identity_hash") or "")
                    or stored != dict(identity)
                ):
                    raise PurgeError(
                        f"embedding_identity_conflict for workspace {workspace!r}: existing "
                        "registration differs from the authoritative identity; aborting"
                    )
                registrations[workspace] = "EXISTED"

            workspace_deletions: dict[str, int] = {}
            for table in legacy_tables:
                count = await _legacy_rows(conn, table, workspace)
                if count:
                    await conn.execute(f'DELETE FROM "{table}" WHERE workspace=$1', workspace)
                workspace_deletions[table] = count
            deletions[workspace] = workspace_deletions

        for table in legacy_tables:
            table_remaining = {}
            for workspace in affected:
                left = await _legacy_rows(conn, table, workspace)
                if left:
                    table_remaining[workspace] = left
            if table_remaining:
                remaining[table] = table_remaining
        if remaining:
            raise PurgeError("verification failed: legacy rows remain after delete; rolling back")

    return {
        "mode": "apply",
        "legacy_tables": legacy_tables,
        "suffixed_tables": suffixed_tables,
        "affected_workspaces": list(affected),
        "deletions": deletions,
        "registrations": registrations,
        "force_used": needs_force if force else [],
        "remaining": remaining,
        "identity_hash": str(identity.get("identity_hash") or ""),
    }


# ── CLI ────────────────────────────────────────────────────────

def _print_report(report: dict[str, Any]) -> None:
    print(f"mode: {report['mode']}")
    print("legacy tables: " + (", ".join(report["legacy_tables"]) or "(none)"))
    print("suffixed tables: " + (", ".join(report["suffixed_tables"]) or "(none)"))
    affected = report["affected_workspaces"]
    print(f"affected workspaces ({len(affected)}): " + (", ".join(affected) or "(none)"))
    print(f"identity hash: {report['identity_hash']}")
    if report["mode"] == "dry-run":
        print("legacy baseline:")
        for table, rows in sorted(report["baseline"].items()):
            for workspace, count in sorted(rows.items()):
                print(f"  {table}  {workspace}: {count}")
        print("suffixed rows:")
        for table, rows in sorted(report["suffixed_rows"].items()):
            for workspace, count in sorted(rows.items()):
                print(f"  {table}  {workspace}: {count}")
    else:
        total = 0
        for workspace in affected:
            per_table = report["deletions"].get(workspace, {})
            deleted = sum(per_table.values())
            total += deleted
            status = report["registrations"].get(workspace, "UNCHANGED")
            print(f"  {workspace}: registration={status} deleted={deleted}")
        print(f"total deleted: {total}")
        print("force used for: " + (", ".join(report["force_used"]) or "(none)"))
        print(f"verification remaining: {report['remaining']}")


async def _run(args: argparse.Namespace) -> int:
    dsn = resolve_dsn(args.dsn)
    conn = await asyncpg.connect(dsn=dsn, timeout=10)
    try:
        if args.apply:
            report = await apply(conn, backup_dir=args.backup_dir, force=args.force)
        else:
            report = await dry_run(conn)
    finally:
        await conn.close()
    _print_report(report)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-time purge of legacy LightRAG vector rows with identity registration."
    )
    parser.add_argument("--apply", action="store_true", help="perform the destructive purge (requires --backup-dir)")
    parser.add_argument("--dry-run", action="store_true", help="report the baseline only (default mode)")
    parser.add_argument("--force", action="store_true", help="allow purging workspaces that also have suffixed-table rows (only with --apply)")
    parser.add_argument("--backup-dir", metavar="DIR", help="directory with a non-empty pg_dump file per legacy table (required with --apply)")
    parser.add_argument("--dsn", metavar="DSN", help="override database DSN (default: DATABASE_URL or POSTGRES_*)")
    args = parser.parse_args(argv)

    try:
        if args.apply and args.dry_run:
            raise PurgeError("--apply and --dry-run are mutually exclusive")
        if not args.apply and args.force:
            raise PurgeError("--force requires --apply")
        if args.apply and not args.backup_dir:
            raise PurgeError("--apply requires --backup-dir with verified pg_dump files")
        return asyncio.run(_run(args))
    except PurgeError as exc:
        print(f"[purge] error: {exc}", file=sys.stderr)
        return EXIT_EXPECTED
    except (asyncpg.PostgresError, OSError, ValueError) as exc:
        print(f"[purge] error: {_sanitize(str(exc))}", file=sys.stderr)
        return EXIT_EXPECTED
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"[purge] unexpected error: {_sanitize(str(exc))}", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())