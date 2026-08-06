#!/usr/bin/env python3
"""Fail-closed PostgreSQL migration runner for the release chain.

The runner deliberately keeps migration identity and ordering in
``migrations/migration_manifest.json``. PostgreSQL connection values are read from the
environment (``DATABASE_URL`` or the standard ``PG*`` variables) and are
never included in command output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit


HISTORY_TABLE = "schema_migration_history"
_MIGRATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")
_SECRET_RE = re.compile(
    r"(?i)(postgres(?:ql)?://)[^\s'\"]+|"
    r"(password\s*[=:]\s*)[^\s,;]+|"
    r"(PGPASSWORD\s*[=:]\s*)[^\s,;]+"
)


class MigrationRunnerError(RuntimeError):
    """Base class for expected, user-actionable runner failures."""


class ManifestError(MigrationRunnerError):
    pass


class DatabaseStateError(MigrationRunnerError):
    pass


class ChecksumDriftError(MigrationRunnerError):
    pass


class BackupAcknowledgementError(MigrationRunnerError):
    pass


class MigrationApplyError(MigrationRunnerError):
    pass


@dataclass(frozen=True)
class Migration:
    sequence: int
    migration_id: str
    path: Path
    checksum: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class MigrationPlan:
    migrations: tuple[Migration, ...]
    applied: tuple[Migration, ...]
    pending: tuple[Migration, ...]


def _sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def sanitize_failure(message: str, *, limit: int = 500) -> str:
    """Return bounded diagnostics without DSNs, passwords, or multiline noise."""

    cleaned = _SECRET_RE.sub(
        lambda match: (
            match.group(1) or match.group(2) or match.group(3) or "<redacted>"
        ),
        message,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit] or "migration command failed without diagnostics"


def database_safe_failure(message: str, *, limit: int = 500) -> str:
    """Return a portable diagnostic literal for psql's Windows command line."""

    return sanitize_failure(message, limit=limit).encode(
        "ascii", "backslashreplace"
    ).decode("ascii")


def classify_failure(message: str, returncode: int) -> str:
    lowered = message.lower()
    if "password authentication failed" in lowered or "no password supplied" in lowered:
        return "connection-authentication"
    if "could not connect" in lowered or "connection refused" in lowered:
        return "connection-unavailable"
    if "permission denied" in lowered or "must be owner" in lowered:
        return "database-permission"
    if "syntax error" in lowered or "does not exist" in lowered:
        return "sql-schema"
    if "timeout" in lowered:
        return "timeout"
    return f"psql-exit-{returncode}"


def connection_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolve DATABASE_URL into PG* variables without exposing it to output."""

    env = dict(base or os.environ)
    # Keep psql diagnostics safe to store in the UTF-8 migration history on Windows.
    # An explicit caller choice remains authoritative.
    env.setdefault("PGCLIENTENCODING", "UTF8")
    database_url = env.get("DATABASE_URL")
    if not database_url:
        return env

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise MigrationRunnerError("DATABASE_URL must be a PostgreSQL connection URL")
    env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    if parsed.path and parsed.path != "/":
        env["PGDATABASE"] = unquote(parsed.path.lstrip("/"))
    query_values = dict(
        part.split("=", 1) for part in parsed.query.split("&") if "=" in part
    )
    if "sslmode" in query_values:
        env["PGSSLMODE"] = unquote(query_values["sslmode"])
    if "target_session_attrs" in query_values:
        env["PGTARGETSESSIONATTRS"] = unquote(query_values["target_session_attrs"])
    return env


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(
    root: Path, manifest_path: Path | None = None
) -> tuple[Migration, ...]:
    migrations_dir = root / "migrations"
    manifest_file = manifest_path or migrations_dir / "migration_manifest.json"
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read migration manifest: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ManifestError("migration manifest version must be 1")
    entries = payload.get("migrations")
    if not isinstance(entries, list) or not entries:
        raise ManifestError(
            "migration manifest must contain a non-empty migrations list"
        )

    sql_files = {path.name for path in migrations_dir.glob("*.sql")}
    seen: set[str] = set()
    migrations: list[Migration] = []
    for expected_sequence, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ManifestError(
                f"manifest entry {expected_sequence} must contain a filename id"
            )
        migration_id = entry["id"]
        sequence = entry.get("sequence")
        if sequence != expected_sequence:
            raise ManifestError(
                f"manifest sequence must be contiguous at {migration_id!r}"
            )
        if not _MIGRATION_ID_RE.fullmatch(migration_id):
            raise ManifestError(
                f"manifest id is not a safe complete SQL filename: {migration_id!r}"
            )
        if migration_id in seen:
            raise ManifestError(f"duplicate migration id in manifest: {migration_id}")
        seen.add(migration_id)
        path = migrations_dir / migration_id
        if not path.is_file():
            raise ManifestError(f"manifest migration does not exist: {migration_id}")
        migrations.append(Migration(sequence, migration_id, path, sha256_file(path)))

    missing = sorted(sql_files - seen)
    unknown = sorted(seen - sql_files)
    if missing:
        raise ManifestError(
            "migration files missing from manifest: " + ", ".join(missing)
        )
    if unknown:
        raise ManifestError(
            "manifest references unknown migration files: " + ", ".join(unknown)
        )

    # A numeric prefix is useful for humans only.  The full filename must be
    # present so duplicate 001/009/010 prefixes remain independently tracked.
    prefix_groups: dict[str, list[str]] = {}
    for migration in migrations:
        prefix = migration.migration_id.split("_", 1)[0]
        prefix_groups.setdefault(prefix, []).append(migration.migration_id)
    for prefix, ids in prefix_groups.items():
        if len(ids) > 1 and any(id_value == f"{prefix}.sql" for id_value in ids):
            raise ManifestError(
                f"numeric prefix {prefix} cannot be used as a migration id"
            )
    return tuple(migrations)


class PsqlExecutor:
    """Small subprocess boundary that keeps connection secrets in the env."""

    def __init__(
        self,
        *,
        psql_bin: str = "psql",
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int = 300,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.psql_bin = psql_bin
        self.env = connection_environment(env)
        self.cwd = str(cwd) if cwd else None
        self.timeout = timeout
        self.command_runner = command_runner or subprocess.run

    def run(
        self, args: Sequence[str], *, input_text: str | None = None
    ) -> CommandResult:
        command = [self.psql_bin, "-X", "-w", "-v", "ON_ERROR_STOP=1", *args]
        try:
            completed = self.command_runner(
                command,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.env,
                cwd=self.cwd,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            return CommandResult(127, "", str(exc))
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, "", str(exc))
        return CommandResult(
            completed.returncode, completed.stdout or "", completed.stderr or ""
        )


class MigrationRunner:
    def __init__(
        self,
        root: Path | str | None = None,
        *,
        manifest_path: Path | str | None = None,
        executor: PsqlExecutor | None = None,
    ) -> None:
        self.root = Path(root or Path(__file__).resolve().parents[1]).resolve()
        self.manifest_path = Path(manifest_path).resolve() if manifest_path else None
        self.migrations = load_manifest(self.root, self.manifest_path)
        self.executor = executor or PsqlExecutor(cwd=self.root)

    def _execute(
        self, args: Sequence[str], *, input_text: str | None = None
    ) -> CommandResult:
        result = self.executor.run(args, input_text=input_text)
        if result.returncode:
            detail = sanitize_failure(result.stderr or result.stdout)
            raise DatabaseStateError(
                f"psql command failed ({classify_failure(detail, result.returncode)}): {detail}"
            )
        return result

    def _query(self, sql: str) -> str:
        return self._execute(["-At", "-c", sql]).stdout.strip()

    def ensure_history_table(self) -> None:
        self._execute(
            [
                "-c",
                f"""
                CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (
                    migration_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL,
                    checksum CHAR(64) NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('applied', 'failed')),
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    failure_class TEXT,
                    failure_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_{HISTORY_TABLE}_sequence
                    ON {HISTORY_TABLE}(sequence);
                """,
            ]
        )

    def _read_history(self) -> dict[str, dict[str, object]]:
        output = self._query(
            f"""
            SELECT COALESCE(json_agg(row_to_json(history) ORDER BY sequence)::text, '[]')
            FROM (
                SELECT migration_id, sequence, checksum, state,
                       started_at::text, completed_at::text,
                       failure_class, failure_message
                FROM {HISTORY_TABLE}
            ) AS history;
            """
        )
        try:
            rows = json.loads(output or "[]")
        except json.JSONDecodeError as exc:
            raise DatabaseStateError("migration history returned invalid JSON") from exc
        if not isinstance(rows, list):
            raise DatabaseStateError("migration history returned an invalid shape")
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(
                row.get("migration_id"), str
            ):
                raise DatabaseStateError("migration history contains an invalid row")
            migration_id = row["migration_id"]
            if migration_id in result:
                raise DatabaseStateError(f"duplicate history row: {migration_id}")
            result[migration_id] = row
        return result

    def _database_has_user_objects(self) -> bool:
        value = self._query(
            f"""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_name <> '{HISTORY_TABLE}';
            """
        )
        try:
            return int(value or "0") > 0
        except ValueError as exc:
            raise DatabaseStateError(
                "database object probe returned a non-numeric result"
            ) from exc

    def _validate_history(
        self, history: Mapping[str, Mapping[str, object]], *, allow_failed: bool = False
    ) -> None:
        known = {migration.migration_id: migration for migration in self.migrations}
        for migration_id, row in history.items():
            migration = known.get(migration_id)
            if migration is None:
                raise DatabaseStateError(
                    f"database history contains unknown migration: {migration_id}"
                )
            if row.get("sequence") != migration.sequence:
                raise DatabaseStateError(
                    f"migration history sequence mismatch: {migration_id}"
                )
            state = row.get("state")
            if state not in {"applied", "failed"}:
                raise DatabaseStateError(
                    f"migration history has invalid state: {migration_id}"
                )
            if state == "failed" and not allow_failed:
                failure = sanitize_failure(
                    str(row.get("failure_message") or "unresolved migration failure")
                )
                raise DatabaseStateError(
                    f"unresolved failed migration {migration_id}; remediate or restore before retry ({failure})"
                )
            recorded_checksum = str(row.get("checksum") or "")
            if recorded_checksum != migration.checksum:
                raise ChecksumDriftError(f"checksum drift detected for {migration_id}")

        applied_sequences = sorted(
            migration.sequence
            for migration in self.migrations
            if history.get(migration.migration_id, {}).get("state") == "applied"
        )
        if applied_sequences and applied_sequences != list(
            range(1, max(applied_sequences) + 1)
        ):
            raise DatabaseStateError(
                "migration history has a gap before an applied migration"
            )

    def plan(self) -> MigrationPlan:
        self.ensure_history_table()
        history = self._read_history()
        if not history and self._database_has_user_objects():
            raise DatabaseStateError(
                "database has schema objects but no migration history; refusing unsafe baseline inference"
            )
        self._validate_history(history)
        applied = tuple(
            migration
            for migration in self.migrations
            if migration.migration_id in history
        )
        pending = tuple(
            migration
            for migration in self.migrations
            if migration.migration_id not in history
        )
        return MigrationPlan(self.migrations, applied, pending)

    def status(self) -> list[dict[str, object]]:
        self.ensure_history_table()
        history = self._read_history()
        if not history and self._database_has_user_objects():
            raise DatabaseStateError(
                "database has schema objects but no migration history; refusing unsafe baseline inference"
            )
        self._validate_history(history, allow_failed=True)
        result: list[dict[str, object]] = []
        for migration in self.migrations:
            row = history.get(migration.migration_id)
            result.append(
                {
                    "sequence": migration.sequence,
                    "migration_id": migration.migration_id,
                    "checksum": migration.checksum,
                    "state": row.get("state") if row else "pending",
                    "started_at": row.get("started_at") if row else None,
                    "completed_at": row.get("completed_at") if row else None,
                    "failure_class": row.get("failure_class") if row else None,
                    "failure_message": (
                        sanitize_failure(str(row["failure_message"]))
                        if row and row.get("failure_message")
                        else None
                    ),
                }
            )
        return result

    def _record(
        self,
        migration: Migration,
        *,
        state: str,
        failure_class: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        if state not in {"applied", "failed"}:
            raise ValueError(f"unsupported migration history state: {state}")
        sql = f"""
        INSERT INTO {HISTORY_TABLE}
            (migration_id, sequence, checksum, state, started_at, completed_at,
             failure_class, failure_message)
        VALUES ({_sql_literal(migration.migration_id)}, {migration.sequence},
                {_sql_literal(migration.checksum)}, {_sql_literal(state)}, NOW(), NOW(),
                {_sql_literal(failure_class)}, {_sql_literal(database_safe_failure(failure_message or "") if failure_message else None)})
        ON CONFLICT (migration_id) DO UPDATE SET
            sequence = EXCLUDED.sequence,
            checksum = EXCLUDED.checksum,
            state = EXCLUDED.state,
            started_at = EXCLUDED.started_at,
            completed_at = EXCLUDED.completed_at,
            failure_class = EXCLUDED.failure_class,
            failure_message = EXCLUDED.failure_message;
        """
        self._execute(["-c", sql])

    def apply(self, *, backup_acknowledged: bool) -> MigrationPlan:
        if not backup_acknowledged:
            raise BackupAcknowledgementError(
                "apply requires --backup-acknowledged after a verified PostgreSQL backup and preflight"
            )
        plan = self.plan()
        for migration in plan.pending:
            result = self.executor.run(["-f", str(migration.path)])
            if result.returncode:
                detail = sanitize_failure(result.stderr or result.stdout)
                failure_class = classify_failure(detail, result.returncode)
                try:
                    self._record(
                        migration,
                        state="failed",
                        failure_class=failure_class,
                        failure_message=detail,
                    )
                except MigrationRunnerError as record_error:
                    raise MigrationApplyError(
                        f"migration {migration.migration_id} failed ({failure_class}); failure record unavailable"
                    ) from record_error
                raise MigrationApplyError(
                    f"migration {migration.migration_id} failed ({failure_class}): {detail}"
                )
            self._record(migration, state="applied")
        return plan

    def baseline(self, *, through: str, backup_acknowledged: bool) -> int:
        """Record an externally verified historical manifest prefix.

        This never infers state from table names or executes historical SQL. It
        exists solely for a deployment operator that has verified a supported
        release checkpoint from independent evidence.
        """

        if not backup_acknowledged:
            raise BackupAcknowledgementError(
                "baseline requires --backup-acknowledged after a verified PostgreSQL backup and checkpoint review"
            )
        self.ensure_history_table()
        history = self._read_history()
        if history:
            raise DatabaseStateError(
                "baseline is only allowed when migration history is empty"
            )
        try:
            last_sequence = next(
                migration.sequence
                for migration in self.migrations
                if migration.migration_id == through
            )
        except StopIteration as exc:
            raise DatabaseStateError(
                f"baseline checkpoint is not in the manifest: {through}"
            ) from exc
        if not self._database_has_user_objects():
            raise DatabaseStateError(
                "baseline requires an existing verified database; the target has no user schema objects"
            )
        for migration in self.migrations:
            if migration.sequence > last_sequence:
                break
            self._record(migration, state="applied")
        return last_sequence


def _format_status(rows: Iterable[Mapping[str, object]]) -> str:
    lines = [
        "sequence\tmigration_id\tstate\tchecksum\tstarted_at\tcompleted_at\tfailure_class\tfailure"
    ]
    for row in rows:
        failure = row.get("failure_message") or ""
        lines.append(
            "\t".join(
                str(row.get(key) or "")
                for key in (
                    "sequence",
                    "migration_id",
                    "state",
                    "checksum",
                    "started_at",
                    "completed_at",
                    "failure_class",
                )
            )
            + "\t"
            + str(failure)
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RAG-Anything PostgreSQL migration release runner"
    )
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--psql", default=os.getenv("PSQL_BIN", "psql"), help=argparse.SUPPRESS
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "plan", "verify"):
        subparsers.add_parser(command, help=f"show migration {command}")
    apply_parser = subparsers.add_parser("apply", help="apply pending migrations")
    apply_parser.add_argument(
        "--backup-acknowledged",
        action="store_true",
        help="acknowledge a verified backup and completed preflight",
    )
    baseline_parser = subparsers.add_parser(
        "baseline", help="record an externally verified historical checkpoint"
    )
    baseline_parser.add_argument(
        "--through",
        required=True,
        help="exact manifest filename of the verified checkpoint",
    )
    baseline_parser.add_argument(
        "--backup-acknowledged",
        action="store_true",
        help="acknowledge a verified backup and reviewed historical checkpoint",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        executor = PsqlExecutor(psql_bin=args.psql, cwd=args.root)
        runner = MigrationRunner(
            args.root, manifest_path=args.manifest, executor=executor
        )
        if args.command == "status":
            print(_format_status(runner.status()))
        elif args.command in {"plan", "verify"}:
            plan = runner.plan()
            if args.command == "verify":
                print(f"migration verification passed; pending={len(plan.pending)}")
            elif plan.pending:
                print("pending migrations:")
                for migration in plan.pending:
                    print(f"{migration.sequence}\t{migration.migration_id}")
            else:
                print("migration chain is current")
        else:
            if args.command == "baseline":
                count = runner.baseline(
                    through=args.through, backup_acknowledged=args.backup_acknowledged
                )
                print(f"migration baseline completed; recorded={count}")
            else:
                plan = runner.apply(backup_acknowledged=args.backup_acknowledged)
                applied_count = len(plan.pending)
                print(f"migration apply completed; applied={applied_count}")
        return 0
    except MigrationRunnerError as exc:
        print(f"migration runner failed: {sanitize_failure(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
