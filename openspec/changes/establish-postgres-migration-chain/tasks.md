## 1. Migration Chain Definition

- [x] 1.0 Repair and test the explicitly authorized historical SQL incompatibilities required for a complete chain, preserving filenames, intent, and dependency order. (2026-08-04: repaired `010_manufacturing_to_autorepair_permissions.sql` from array operators/legacy `pg_kb_meta` to the current JSONB `roles.permissions` and `kb_metadata.extra` contracts; real PostgreSQL fresh/repeat/upgrade/failure integration scenarios passed.)
- [x] 1.1 Inventory every current `migrations/*.sql` release file, define its reviewed manifest order, and add an automated guard that rejects omissions, unknown entries, duplicates, and the duplicate-prefix ambiguity around `001`, `009`, and `010`.
- [x] 1.2 Add a migration metadata schema and runner module that uses complete filenames as IDs, computes raw-byte SHA-256 checksums, and exposes ordered local/history status without secret values.
- [x] 1.3 Implement checksum verification, supported baseline/upgrade handling, unresolved-failure blocking, and no-op repeated execution semantics.

## 2. Safe Execution and Setup Integration

- [x] 2.1 Implement manifest planning and application with per-file `psql` failure handling, sanitized diagnostics, non-zero exit behavior, and immediate stop before later migrations.
- [x] 2.2 Add backup-acknowledged apply gating and document the command contract for status, plan, verify, and apply without echoing passwords or DSNs.
- [x] 2.3 Refactor `scripts/pg_setup.py` to provision its fresh database/user responsibilities and delegate chain application to the runner, eliminating the handwritten migration list and continuation-after-failure behavior.

## 3. Validation

- [x] 3.1 Add deterministic unit tests for manifest completeness/order, history/checksum behavior, a supported upgrade checkpoint, repeat execution, checksum drift, and intentional stop-on-failure behavior.
- [x] 3.2 Add opt-in isolated PostgreSQL integration tests using `MIGRATION_TEST_DATABASE_URL` for fresh install, upgrade, repeated execution, and intentionally failing migration; ensure cleanup is namespace-scoped and output is secret-free.
- [x] 3.3 Run focused tests, OpenSpec strict validation, static compilation/lint checks applicable to changed Python files, and `git diff --check`; record exact environment limitations if a PostgreSQL target is unavailable. (2026-08-04: real PostgreSQL focused unit/integration suite 15 passed; strict validation, py_compile, and scoped diff check completed after the compatibility repair.)

## 4. Release Documentation and Handoff

- [x] 4.1 Add migration-focused operator documentation covering backup verification, preflight/status review, apply, failure stop/remediation, restore/forward rollback limits, and deployment handoff commands.
- [x] 4.2 Produce the implementation handoff with changed-file summary, test results, deployment migration commands, known runtime/CI gaps, and a proposed `PROJECT_SUMMARY.md` delta without modifying that file. (Handoff delivered in the implementation response; `PROJECT_SUMMARY.md` remains untouched.)
