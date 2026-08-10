## Context

`migrations/` contains 30 release SQL files. Their numeric prefixes are not unique: both `001_pg_schema.sql` and `001_shared_state_tables.sql`, both `009_*` files, and both `010_*` files are independently required. `scripts/pg_setup.py` manually selects 23 files, omitting `001_shared_state_tables.sql`, `002_pg_3to5_roles.sql`, `004_token_blacklist_pg.sql`, `006_workflow_manufacturing_pg.sql`, `008_manufacturing_config_pg.sql`, and `009_conversation_summary.sql`; it also retries failed files after changing schema ownership and continues to later files.

The PostgreSQL repositories assume schema objects exist but do not own migration state. Existing focused tests inspect selected SQL strings and may optionally use `MIGRATION_TEST_DATABASE_URL`; no release-level migration chain contract exists. This change is constrained to migration artifacts, setup/runner/test code, and directly related documentation. It must not change server startup, container configuration, RBAC, auth/business routes, CI workflows, active-change files, or `PROJECT_SUMMARY.md`.

The approved implementation scope includes minimal repairs to historical migration SQL when a complete fresh or supported upgrade chain cannot execute against the current schema. Such repairs must preserve the filename, migration identity, dependency order, and intended data transformation. They are limited to type/table-name compatibility and idempotency/order defects proven by the chain tests; they must not introduce unrelated schema or business changes.

## Goals / Non-Goals

**Goals:**

- Treat a versioned repository manifest, rather than a handwritten setup-script list or numeric prefix, as the canonical ordered migration chain.
- Preserve all historical filenames and apply every currently required migration in a deterministic order.
- Persist queryable application history, SHA-256 checksums, execution ordering, and safe failure diagnostics.
- Support fresh installations, upgrades from a recorded historical release point, idempotent repeated invocations, and immediate stop on a failed migration.
- Provide a production preflight that requires an explicit backup acknowledgement and never prints credentials, DSNs, or SQL parameter values.
- Make the integration contract executable when a dedicated PostgreSQL test database is supplied, while keeping pure runner tests runnable without it.

**Non-Goals:**

- Renaming or renumbering historical migration SQL files, or changing their business meaning. Historical SQL may be minimally corrected only under the approved compatibility-repair scope above.
- Automatically creating backups, automatically rolling back arbitrary migrations, or modifying data recovery policy.
- Adding runtime startup migrations, Docker/CI changes, an ORM, or a new external migration framework.
- Altering repository/business behavior that happens to depend on migrated tables.

## Decisions

### 1. Use a checked-in ordered manifest and immutable filename IDs

A new runner module will read a small checked-in manifest whose entries are the exact SQL filenames in release order. The migration ID is the full filename, not the numeric prefix. The manifest is the reviewed ordering authority; discovery verifies that every `migrations/*.sql` release file is included exactly once and that the referenced file exists.

This resolves historical duplicate prefixes without destructive renames, lets causal dependencies be explicit, and makes missing files a pre-execution error. Lexicographic filename ordering was rejected because it cannot express the established ordering around the duplicate `009` and `010` prefixes. Continuing with a Python list in `pg_setup.py` was rejected because it already drifted.

### 2. Store history in PostgreSQL and checksum the exact bytes

Before applying SQL, the runner creates an idempotent metadata table, `schema_migration_history`, outside the application domain. Its rows include `migration_id`, manifest sequence, SHA-256 hex checksum, state (`applied` or `failed`), started/completed timestamps, and a bounded sanitized error classification/message. The primary lookup key is `migration_id`; applied history is queryable by ID and sequence.

The checksum is computed from the raw file bytes. A recorded applied migration whose current file checksum differs causes a terminal verification error before any new SQL runs. A historical database with no rows is handled through explicit baseline/bootstrap verification, not by inferring applied status from arbitrary table existence. This protects both content drift and ambiguous duplicate numeric prefixes.

### 3. Run one migration per invocation and fail closed

The runner uses `psql` with `ON_ERROR_STOP=1` for one migration file at a time. It writes an in-progress/failure diagnostic only through controlled runner SQL, records `applied` only after the file invocation succeeds, and stops immediately on any non-zero result, checksum conflict, malformed manifest, or failed history entry. It never treats text such as `already exists` as success.

Per-file transactions retain the existing migration files, some of which already declare `BEGIN`/`COMMIT`; the runner must avoid an incompatible outer wrapper for those files. Instead it invokes each migration as an isolated `psql -f` operation with `ON_ERROR_STOP`, records history only after success, and reports that a partial result requires operator restore/remediation if the SQL file itself is non-transactional. The implementation will detect and document this constraint. A single all-chain transaction was rejected because current SQL contains transaction control and release migrations may include operations that cannot run in a transaction.

### 4. Separate bootstrap, preflight, and state commands

The new CLI exposes `status`, `plan`/`verify`, and `apply` behavior. `apply` requires an explicit `--backup-acknowledged` flag in production-oriented use; without it it exits before executing any migration. `status` displays only migration identifiers, sequences, state, checksums, timestamps, and sanitized failures. `pg_setup.py` remains the interactive fresh-instance provisioner but delegates application/upgrades to the runner and avoids emitting credentials.

The runner accepts connection details through environment variables or an explicit secure input mechanism without echoing them. It does not write a DSN to terminal output. Deployment instructions require a verified `pg_dump` backup, `plan/status`, `apply`, a post-apply `status`, and an incident path: stop deployment, preserve the failure output, restore the verified backup if needed, remediate via a new forward migration or approved restoration, and never edit a recorded migration.

### 5. Use isolated PostgreSQL integration tests plus deterministic unit tests

Unit tests will create temporary migration directories/manifest data to assert ordering, checksum behavior, repeats, and stop-on-failure via a fake command runner. An integration suite, gated by `MIGRATION_TEST_DATABASE_URL`, creates a unique test schema/database namespace and runs the actual runner against the complete chain for fresh install, upgrade/baseline state, repeated application, and an injected failing migration. It cleans only its unique namespace after assertions.

The integration URL is an opt-in secret supplied by CI or an operator environment; test logs must redact connection strings and passwords. Docker-in-Docker or CI workflow edits are deliberately excluded.

## Risks / Trade-offs

- [Historical SQL may be only partially idempotent or may include transaction control] -> Apply state is recorded only after a successful `psql` invocation; test the complete current chain in real PostgreSQL and document restore-first failure handling.
- [A pre-run database has no history table but has unknown schema state] -> Refuse unsafe inference; require an explicit, reviewed baseline/import procedure that validates a known checkpoint before recording it.
- [Changing an already released SQL file] -> Raw-byte checksum validation blocks the release before new migrations execute; publish a new migration instead.
- [Credentials leak through subprocess errors] -> Construct commands without embedding DSNs, pass secrets through environment variables, and sanitize captured stderr before reporting.
- [Full-chain integration needs extensions/privileges unavailable in a CI database] -> Clearly distinguish an environment skip/block from a source failure; keep deterministic runner coverage mandatory and preserve the exact setup prerequisites.
- [Manifest becomes a second source of truth] -> It is intentionally the single ordered release authority; a test fails when the manifest and migration directory diverge, so a file cannot be silently excluded.

## Migration Plan

1. Inventory and codify every present release migration in the manifest, retaining existing filenames and order.
2. Add the runner, its metadata schema, checksum/history/status behavior, and safe command-line contract.
3. Replace `pg_setup.py`'s explicit migration list with runner delegation while retaining its database/user provision responsibilities.
4. Add unit and opt-in PostgreSQL integration coverage, then run the release preflight against an isolated database.
5. For deployment: take and verify a PostgreSQL backup; run `status` and `plan`; invoke `apply --backup-acknowledged`; re-run `status`; only then continue the service deployment.
6. On failure: do not retry by skipping history, changing a historical file, or launching the service. Preserve sanitized diagnostics, determine whether the failed SQL left partial state, restore the verified backup when required, and ship a new forward migration or approved recovery runbook.

Rollback is database restore from the verified backup or a separately reviewed forward corrective migration. This runner deliberately does not claim that arbitrary SQL migrations are automatically reversible.

## Open Questions

- Which existing deployed database checkpoints can be positively identified and safely baselined without running missing historical SQL? The implementation must start with the current release checkpoint only unless concrete deployment evidence defines earlier supported baselines.
- Does the CI PostgreSQL service grant the extensions/privileges required by the full historic chain? This must be tested in the CI-equivalent database and reported as a deployment prerequisite if unavailable.
