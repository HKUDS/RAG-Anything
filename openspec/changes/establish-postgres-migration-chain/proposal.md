## Why

The release PostgreSQL setup path keeps a handwritten subset of SQL files as its effective migration source, so existing deployments can silently miss changes and duplicate numeric prefixes (`001`, `009`, and `010`) cannot be tracked unambiguously. The project needs a release gate that can prove exactly which immutable migration files were applied, in which order, and against which checksums before a deployment proceeds.

## What Changes

- Introduce a PostgreSQL migration runner that discovers the repository migration chain from disk, uses each filename as its stable migration identity, and records an ordered history with SHA-256 checksums.
- Establish an explicit manifest/ordering policy that includes every current release migration and resolves duplicate numeric prefixes without renaming historical migration files.
- Repair only the historical SQL incompatibilities that prevent the complete reviewed chain from running on the current PostgreSQL schema, without changing migration identities or business intent.
- Replace `scripts/pg_setup.py`'s handwritten migration list with the runner for both fresh database initialization and existing-database upgrades.
- Make migration execution isolated per file, fail closed on checksum drift or execution error, and prevent later migrations from running after a failure.
- Add a non-secret release-preflight workflow: backup acknowledgement, status/checksum inspection, dry-run planning, failure remediation, and rollback guidance.
- Add automated validation for fresh install, upgrade from a historical checkpoint, repeated execution, checksum drift, and an intentionally failing migration; allow a real PostgreSQL integration suite in CI through an isolated test database URL.

## Capabilities

### New Capabilities

- `postgres-migration-release-safety`: Discovers, applies, records, verifies, and reports the complete PostgreSQL migration chain safely for release.

### Modified Capabilities

- `platform-deployment-and-ops`: Release database preparation gains an enforced migration preflight, status evidence, backup acknowledgement, and documented failure/rollback handling.

## Impact

- Affects `migrations/**`, `scripts/pg_setup.py`, a new migration runner and migration-focused tests, plus migration/release documentation only.
- Adds a `schema_migration_history`-style PostgreSQL metadata table managed by the runner; it records migration identifiers, execution order, checksums, timestamps, and failure details without recording DSNs or credentials.
- Does not alter Docker files, server startup, RBAC, authentication/business routes, CI workflows, or any file owned by an existing active change.
- Operators will use the new runner/preflight commands before deployment and must take a verified backup before applying a production upgrade.
