## Context

LightRAG currently receives an embedding callable with a dimension but no stable model identifier. PostgreSQL vector tables are therefore vulnerable to model/dimension mixing, while KB isolation relies on a caller-supplied `workspace` predicate. Queued task snapshots freeze LLM/VLM settings but not text embedding settings, so a runtime environment change can make enqueue, worker, retry, semantic chunking, cache, and query use different embedding contracts.

The change must preserve completed data, avoid secret exposure, and make incompatible or ambiguous existing storage fail explicitly before LightRAG initializes or writes.

## Goals / Non-Goals

**Goals:**

- Freeze a canonical text embedding identity (schema version, provider/model, dimension, endpoint semantics fingerprint, and LightRAG-safe table suffix) at enqueue time.
- Pass the same identity to LightRAG, semantic chunking, cache keys, worker retries, and query construction.
- Register one identity per KB atomically and enforce workspace equality; reject non-empty `PG_WORKSPACE` overrides.
- Keep KB isolation testable through `workspace` predicates and diagnostics across all three vector tables.
- Detect legacy unsuffixed or mixed-identity storage and block automatic cutover without copying or re-embedding data.

**Non-Goals:**

- Deleting, rewriting, or automatically migrating completed vectors.
- Physically separating KBs into one PostgreSQL table per KB.
- Changing the unrelated vision embedding profile or public API shape.

## Decisions

1. **Canonical identity and table suffix.** Build a deterministic identity from a versioned provider/model/endpoint-semantic token and dimension. Normalize only for display, then append a collision-resistant lowercase hash; cap the PostgreSQL identifier suffix to the supported length. Persist the full non-secret identity JSON and hash, never credentials.
2. **Snapshot authority.** Extend the existing task snapshot JSON with `text_embedding_identity`; enqueue resolves it once, and worker/retry/query paths reject snapshots missing or incompatible with it. Module-level environment values are not used for snapshot-bound work.
3. **Atomic KB registry.** Add a PostgreSQL registry keyed by KB workspace. A transaction takes a row lock/advisory lock, creates the identity on first use, and rejects a different identity or dimension before constructing LightRAG. The failure is terminal and not retried automatically.
4. **Workspace guard.** Always pass the canonical `kb_dir(kb)` workspace and fail initialization if `PG_WORKSPACE` is non-empty or differs. Diagnostics report the effective workspace and unexpected workspace rows.
5. **Legacy policy.** If any populated unsuffixed vector table or unknown/mixed identity is found for a KB, mark the KB incompatible and fail upload/query preflight. No normal read path copies legacy rows into suffixed tables; a future explicit migration remains an operational task.
   - Implementation note: legacy detection must be case-insensitive (LightRAG creates tables with unquoted identifiers, stored lowercase) and must return 0 instead of raising when a table or column is absent, because an error inside the registration transaction marks the whole transaction aborted and the next statement fails with `InFailedSQLTransactionError`, breaking startup.
   - Legacy rows block KB initialization, including the startup warm-up path (`get_kb`), surfacing `embedding_legacy_storage_incompatible`; this fail-closed behavior matches the spec, and inventory plus explicit cutover is the operator path (Migration Plan step 3).
   - Out of scope for this change: mixed-identity detection for suffixed tables with no registration is deferred to an explicit audited migration; a registered identity conflict is already covered by `embedding_identity_conflict`.
   - The diagnostic endpoint `read_embedding_identity_diagnostics` must discover tables case-insensitively (`ILIKE`) and compare legacy names case-insensitively.
6. **Read-only diagnostics.** Provide an admin-only, read-only health check that discovers actual LightRAG vector tables from `pg_catalog`, reports model suffix/identity, dimensions, index definitions and sizes, per-workspace counts, and anomalies without DSNs, paths, or stack traces.

## Risks / Trade-offs

- [Existing KBs use unsuffixed tables] → block automatic cutover and expose an actionable incompatibility status; preserve data for a separately audited migration.
- [Hash or canonicalization bugs cause collisions] → version the identity schema, include provider/model/dimension/semantic fingerprint, and test collision, length, and invalid-input cases.
- [Concurrent workers race on first registration] → use a transaction plus row/advisory lock and verify identity before any LightRAG initialization.
- [A process changes environment after enqueue] → snapshot-bound construction uses only persisted identity; startup diagnostics warn on environment drift.
- [Shared tables can still leak if a query omits workspace] → add focused SQL assertions and two-KB integration tests for chunk/entity/relation insert, search, and delete.

## Migration Plan

1. Apply the additive KB embedding identity migration and update the immutable migration manifest.
2. Deploy code with registration/preflight and diagnostics disabled only behind a safe read-only verification mode if needed.
3. Inventory unsuffixed and suffixed tables; register only compatible, explicitly verified KBs. Do not mutate vectors.
4. Enable strict preflight, restart API/Worker, and run two-KB integration plus retrieval checks.
5. Roll back by disabling new uploads/query initialization and reverting code; keep the additive registry and existing vectors intact.

## Open Questions

- Which provider endpoint semantics are available in the current model catalog for the identity fingerprint? Until catalog support is added, use the configured non-secret provider/base URL host and explicit model profile fingerprint.
- Should an explicit audited legacy migration be implemented in a later change? This change intentionally leaves it out.
