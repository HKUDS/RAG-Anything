#!/usr/bin/env python3
"""Provision a PostgreSQL database/user, then delegate migrations to the runner.

This script intentionally does not write ``.env`` or apply a handwritten list
of SQL files. Set ``PGPASSWORD`` through an approved secret mechanism for
automation; credentials are never printed or accepted on the command line.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

from pg_migration_runner import MigrationRunner, PsqlExecutor, sanitize_failure


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def find_psql() -> str:
    candidates = [
        os.getenv("PSQL_BIN", "psql"),
        r"D:\PostgreSQL\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
        r"D:\Program Files\PostgreSQL\16\bin\psql.exe",
    ]
    for candidate in dict.fromkeys(candidates):
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate
    raise RuntimeError(
        "psql was not found; install PostgreSQL client tools or set PSQL_BIN"
    )


def sql_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"unsafe PostgreSQL identifier: {value!r}")
    return '"' + value + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_admin_psql(
    psql: str,
    args: list[str],
    *,
    env: dict[str, str],
    input_text: str | None = None,
) -> str:
    result = subprocess.run(
        [psql, "-X", "-w", "-v", "ON_ERROR_STOP=1", *args],
        input=input_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"administrative PostgreSQL command failed: {sanitize_failure(result.stderr or result.stdout)}"
        )
    return result.stdout.strip()


def provision_database(
    psql: str,
    *,
    admin_env: dict[str, str],
    db_name: str,
    db_user: str,
    db_password: str,
) -> None:
    db_ident = sql_identifier(db_name)
    user_ident = sql_identifier(db_user)
    user_literal = sql_literal(db_user)
    existing_user = run_admin_psql(
        psql,
        [
            "-At",
            "-d",
            "postgres",
            "-c",
            f"SELECT 1 FROM pg_roles WHERE rolname = {user_literal};",
        ],
        env=admin_env,
    )
    if existing_user != "1":
        run_admin_psql(
            psql,
            ["-f", "-"],
            env=admin_env,
            input_text=f"CREATE ROLE {user_ident} LOGIN PASSWORD {sql_literal(db_password)};\n",
        )

    existing_database = run_admin_psql(
        psql,
        [
            "-At",
            "-d",
            "postgres",
            "-c",
            f"SELECT 1 FROM pg_database WHERE datname = {sql_literal(db_name)};",
        ],
        env=admin_env,
    )
    if existing_database != "1":
        run_admin_psql(
            psql,
            ["-d", "postgres", "-c", f"CREATE DATABASE {db_ident} OWNER {user_ident};"],
            env=admin_env,
        )
    run_admin_psql(
        psql,
        ["-d", "postgres", "-c", f"GRANT ALL ON DATABASE {db_ident} TO {user_ident};"],
        env=admin_env,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision RAG-Anything PostgreSQL and run the official migration chain"
    )
    parser.add_argument("--db-name", default="raganything")
    parser.add_argument("--db-user", default="raganything")
    parser.add_argument(
        "--backup-acknowledged",
        action="store_true",
        help="acknowledge a verified backup before applying migrations",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="only provision the database/user; do not apply schema migrations",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        sql_identifier(args.db_name)
        sql_identifier(args.db_user)
        if not args.skip_migrations and not args.backup_acknowledged:
            raise RuntimeError(
                "migration apply requires --backup-acknowledged after a verified backup; "
                "use --skip-migrations for provisioning only"
            )
        admin_password = os.getenv("PGPASSWORD") or getpass.getpass(
            "PostgreSQL administrator password: "
        )
        db_password = admin_password
        psql = find_psql()
        admin_env = os.environ.copy()
        admin_env["PGPASSWORD"] = admin_password
        admin_env["PGUSER"] = "postgres"
        admin_env["PGDATABASE"] = "postgres"
        provision_database(
            psql,
            admin_env=admin_env,
            db_name=args.db_name,
            db_user=args.db_user,
            db_password=db_password,
        )
        if not args.skip_migrations:
            app_env = os.environ.copy()
            app_env.pop("DATABASE_URL", None)
            app_env["PGPASSWORD"] = db_password
            app_env["PGUSER"] = args.db_user
            app_env["PGDATABASE"] = args.db_name
            root = Path(__file__).resolve().parents[1]
            runner = MigrationRunner(
                root,
                executor=PsqlExecutor(psql_bin=psql, env=app_env, cwd=root),
            )
            plan = runner.apply(backup_acknowledged=True)
            print(
                f"PostgreSQL provisioned and migration chain applied: {len(plan.pending)} migration(s)"
            )
        else:
            print(
                "PostgreSQL database and user provisioned; migrations were not applied"
            )
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"PostgreSQL setup failed: {sanitize_failure(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
