"""Opt-in PostgreSQL integration coverage for the release migration runner.

Set MIGRATION_TEST_DATABASE_URL to a disposable PostgreSQL server endpoint.
Each test creates and drops only its own generated database because migration
023 contains public-schema checks that cannot be safely isolated by schema.
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from scripts.pg_migration_runner import (
    MigrationApplyError,
    MigrationRunner,
    PsqlExecutor,
    connection_environment,
    sanitize_failure,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("MIGRATION_TEST_DATABASE_URL"),
    reason="MIGRATION_TEST_DATABASE_URL is required for PostgreSQL migration integration tests",
)


def _identifier() -> str:
    return f"raganything_migration_{uuid.uuid4().hex[:20]}"


def _run(executor: PsqlExecutor, args):
    result = executor.run(args)
    assert result.returncode == 0, sanitize_failure(result.stderr or result.stdout)
    return result.stdout.strip()


@pytest.fixture
def isolated_database():
    base_env = connection_environment(
        {**os.environ, "DATABASE_URL": os.environ["MIGRATION_TEST_DATABASE_URL"]}
    )
    base_env.pop("DATABASE_URL", None)
    admin = PsqlExecutor(env=base_env)
    database_name = _identifier()
    _run(admin, ["-c", f'CREATE DATABASE "{database_name}";'])
    database_env = dict(base_env)
    database_env.pop("DATABASE_URL", None)
    database_env["PGDATABASE"] = database_name
    try:
        yield database_env
    finally:
        result = admin.run(
            ["-c", f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE);']
        )
        assert result.returncode == 0, sanitize_failure(result.stderr or result.stdout)


def _write_manifest(root: Path, migration_sql):
    migrations_dir = root / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for sequence, (migration_id, sql) in enumerate(migration_sql, start=1):
        (migrations_dir / migration_id).write_text(sql, encoding="utf-8")
        entries.append({"sequence": sequence, "id": migration_id})
    (migrations_dir / "migration_manifest.json").write_text(
        json.dumps({"version": 1, "migrations": entries}), encoding="utf-8"
    )


def test_complete_chain_fresh_install_and_repeat(isolated_database):
    root = Path(__file__).resolve().parents[1]
    runner = MigrationRunner(
        root, executor=PsqlExecutor(env=isolated_database, cwd=root)
    )
    manifest = json.loads((root / "migrations" / "migration_manifest.json").read_text(encoding="utf-8"))
    expected_count = len(manifest["migrations"])

    first_plan = runner.apply(backup_acknowledged=True)
    assert len(first_plan.pending) == expected_count
    assert all(row["state"] == "applied" for row in runner.status())

    repeat_plan = runner.apply(backup_acknowledged=True)
    assert repeat_plan.pending == ()


def test_recorded_checkpoint_upgrades_only_the_new_migration(
    isolated_database, tmp_path
):
    _write_manifest(
        tmp_path,
        [("001_base.sql", "CREATE TABLE upgrade_marker (id INTEGER PRIMARY KEY);\n")],
    )
    first_runner = MigrationRunner(
        tmp_path, executor=PsqlExecutor(env=isolated_database, cwd=tmp_path)
    )
    first_runner.apply(backup_acknowledged=True)

    _write_manifest(
        tmp_path,
        [
            ("001_base.sql", "CREATE TABLE upgrade_marker (id INTEGER PRIMARY KEY);\n"),
            (
                "002_upgrade.sql",
                "ALTER TABLE upgrade_marker ADD COLUMN upgraded BOOLEAN NOT NULL DEFAULT FALSE;\n",
            ),
        ],
    )
    upgraded_runner = MigrationRunner(
        tmp_path, executor=PsqlExecutor(env=isolated_database, cwd=tmp_path)
    )
    plan = upgraded_runner.apply(backup_acknowledged=True)
    assert [migration.migration_id for migration in plan.pending] == ["002_upgrade.sql"]
    assert (
        _run(
            PsqlExecutor(env=isolated_database),
            [
                "-At",
                "-c",
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'upgrade_marker' AND column_name = 'upgraded';",
            ],
        )
        == "1"
    )


def test_failing_migration_stops_before_later_file(isolated_database, tmp_path):
    _write_manifest(
        tmp_path,
        [
            ("001_base.sql", "CREATE TABLE failure_marker (id INTEGER PRIMARY KEY);\n"),
            ("002_intentional_failure.sql", "SELECT 1 / 0;\n"),
            (
                "003_never_run.sql",
                "CREATE TABLE must_not_exist (id INTEGER PRIMARY KEY);\n",
            ),
        ],
    )
    runner = MigrationRunner(
        tmp_path, executor=PsqlExecutor(env=isolated_database, cwd=tmp_path)
    )

    with pytest.raises(MigrationApplyError, match="002_intentional_failure.sql"):
        runner.apply(backup_acknowledged=True)
    assert (
        _run(
            PsqlExecutor(env=isolated_database),
            ["-At", "-c", "SELECT to_regclass('public.must_not_exist');"],
        )
        == ""
    )
    history = _run(
        PsqlExecutor(env=isolated_database),
        [
            "-At",
            "-c",
            "SELECT state FROM schema_migration_history WHERE migration_id = '002_intentional_failure.sql';",
        ],
    )
    assert history == "failed"
