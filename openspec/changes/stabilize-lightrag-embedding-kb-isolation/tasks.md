## 1. Identity and snapshots

- [x] 1.1 Add versioned text embedding identity canonicalization, collision-safe LightRAG suffix, and unit tests.
- [x] 1.2 Persist the identity in upload settings snapshots and expose a strict loader for Worker/retry/query paths.
- [x] 1.3 Pass the frozen model identity to the LightRAG `EmbeddingFunc`, semantic chunking, and cache; remove module-level drift.

## 2. KB registration and workspace safety

- [x] 2.1 Add an additive PostgreSQL KB embedding identity registry migration and immutable manifest entry.
- [x] 2.2 Implement locked first-use registration and incompatible/legacy preflight failures before LightRAG initialization.
- [x] 2.3 Reject unsafe `PG_WORKSPACE` overrides and assert the effective canonical KB workspace.
- [x] 2.4 Fix `_legacy_rows` transaction-abort and legacy detection case: use a case-insensitive `information_schema` existence + `workspace` column check (`lower(table_name)=lower($1)`, `LIMIT 1`, require a `workspace` column); return 0 when the table is absent or lacks `workspace` (no error, no aborted transaction); COUNT with the real table name returned by `information_schema` (quoted as stored); rows > 0 raise `embedding_legacy_storage_incompatible`. `to_regclass` is not used because it folds case and cannot cover quoted-uppercase legacy names. Also make `read_embedding_identity_diagnostics` discovery case-insensitive (`ILIKE`) and compare legacy names case-insensitively.
  - Adapt `_IdentityConnection` in `tests/test_text_embedding_identity.py` to the new query shape (existence `fetchrow` + COUNT `fetchval`) and add a missing-table regression case: no abort, registration proceeds.
- [x] 2.5 Fix content-readiness and cleanup vector queries to resolve the physical vector chunk table instead of the hard-coded unsuffixed `LIGHTRAG_VDB_CHUNKS`: add `resolve_vector_chunk_table` (identity-suffixed preferred via the registered identity's `model_name`/`dimension`, legacy fallback, case-insensitive `pg_class` lookup returning the real lowercase relname, `relkind='r'`, safe-name guard, `None` when no table exists); `evaluate_content_readiness` and `cleanup_failed_invalid_residue` use the resolved quoted physical name and skip vector DELETE when no table exists; unit tests cover suffix preference, lowercase physical names, legacy fallback (missing suffix / no registration / invalid identity JSON / string dimension), no-table `None`, and cleanup COUNT/DELETE against the suffixed table.

## 3. Diagnostics and integration verification

- [x] 3.1 Add admin-only read-only HNSW/vector identity diagnostics that discover actual tables and workspace counts without credentials.
- [x] 3.2 Add focused unit tests for identity drift, registry conflicts, legacy blocking, workspace isolation, and cache/chunk consistency.
- [x] 3.3 Add PostgreSQL integration coverage for two-KB chunk/entity/relation isolation and explicit legacy/migration behavior (live acceptance passed 2026-08-06):
  - Apply migration `032_kb_text_embedding_identity.sql` (manifest sequence 35) via `scripts/pg_migration_runner.py apply --backup-acknowledged` (after a verified backup, per the runner's fail-closed contract) and confirm `schema_migration_history` plus `kb_text_embedding_identities`.
  - Fresh DB startup: `python server.py` completes startup and registers the current identity for workspace `kb_dir('default')` (assert the row's `identity_hash` equals the environment identity).
  - Legacy block: create lowercase `lightrag_vdb_chunks` with one workspace row, assert `embedding_legacy_storage_incompatible` and that the row count is unchanged, then drop the table.
  - Live Worker upload acceptance: real API upload to a fresh scratch KB runs the worker to `completed` (entity-extraction -> graph-building), registers the workspace identity with the environment hash, writes chunks/entities/relations into the identity-suffixed vector tables only, and the automatic tagging content-readiness gate resolves the suffixed table (no `vector_count=0` failure); scratch data is cleaned up afterwards.

## 4. Validation and project records

- [x] 4.1 Run focused tests, `py_compile`, OpenSpec strict validation, and `git diff --check`.
- [x] 4.2 Update `PROJECT_SUMMARY.md` with current facts, validation boundaries, and remaining live PostgreSQL/Worker acceptance.
- [x] 4.3 Re-run focused tests, `py_compile`, `git diff --check`, and OpenSpec strict validation (change + repository) after 2.4/3.3; update `PROJECT_SUMMARY.md`.
- [x] 4.4 Update `tests/test_pg_migration_runner.py` manifest count assertions (34 -> 35 and last id `031_kb_card_update_time.sql` -> `032_kb_text_embedding_identity.sql`).
