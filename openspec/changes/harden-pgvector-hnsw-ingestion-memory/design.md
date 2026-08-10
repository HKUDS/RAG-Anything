## Context

An incremental relationship-vector upsert exhausted PostgreSQL memory in the
`Hnsw insert temporary context`. The current Worker reports it as a generic
parse failure, while the parent can turn a partially indexed document into a
degraded completed upload. A running retry job can also be reclaimed after its
lease expires. The deployed HNSW indexes are runtime-created by LightRAG, not
migration-owned.

## Goals / Non-Goals

**Goals:**

- Make HNSW memory exhaustion a fenced terminal graph-index failure with an
  explicit, guarded manual retry path.
- Add capacity evidence and a safe maintenance procedure for both Compose and
  externally managed PostgreSQL deployments.
- Reduce recovery-time write pressure without changing the HNSW retrieval
  strategy.

**Non-Goals:**

- Do not automatically retry, degrade, or repair affected documents.
- Do not alter historical completed documents, switch to IVFFlat, or add a
  schema migration for runtime-created indexes.
- Do not claim that index rebuilding alone fixes memory exhaustion.

## Decisions

### Terminal failure contract

The Worker walks the complete exception chain and recognizes SQLSTATE `53200`
or `Hnsw insert temporary context`. It emits
`graph_index_hnsw_memory_exhausted`, stage `graph_index`, and `retryable=false`
with exit code 1. The parent handles this before generic retry, cleanup, and
degraded-completion branches. It writes fenced `failed` / `terminal_failed`
state, broadcasts `upload_error`, records graph-index failure metadata, and
does not enqueue tagging or repair.

When the failed invocation owns a retry lease, the job is atomically changed to
`terminal_failed` only when both job ID and lease token still match. A terminal
HNSW retry job is never eligible for the retry loop. The existing retry-now
endpoint is the explicit recovery action: it may move only this terminal code
back to queued after the standard task-scoped residue cleanup runs in the
claimed retry attempt. It is not an automatic retry.

### Recovery-time load and deployment profile

The Compose-owned PostgreSQL service receives a 4 GiB cgroup limit,
`shm_size: 1gb`, `shared_buffers=1GB`, `work_mem=16MB`, and
`maintenance_work_mem=512MB`. It explicitly exports `POSTGRES_HNSW_M=16` and
`POSTGRES_HNSW_EF=64`; LightRAG maps the latter to `ef_construction`.
`MAX_ASYNC=1` is a temporary global LLM load limit, not a promise about graph
write concurrency. `ENTITY_EXTRACT_CONCURRENCY` remains explicitly configured
and is reported by the health tooling.

For external or managed PostgreSQL, Compose settings are not assumed effective.
The runbook requires DBA-equivalent settings and live verification before any
claim of deployment acceptance.

### Health and maintenance

A read-only script discovers HNSW indexes from `pg_catalog`, not fixed names.
It reports pgvector version, index validity/definition/size, VDB table counts
and dead tuples, PostgreSQL settings, active connections, database size, and
available capacity evidence without credentials. Where supported, it also
reports container cgroup memory values; unavailable host/container metrics are
reported as unavailable rather than fabricated.

The runbook first gates uploads and drains tasks, validates a logical backup,
captures the discovered DDL, verifies disk headroom, and then changes runtime
configuration. In a no-write window it rebuilds each discovered HNSW index in
one ordinary transaction so DDL failure rolls back to the prior index. It
validates the actual catalog state after restart and requires a real write and
retrieval acceptance test. A rollback restores the previous runtime settings
and relies on transactional DDL rollback; production restore is never run as
part of this procedure.

## Risks / Trade-offs

- **4 GiB is a hard limit, not a cure** -> require cgroup/PG evidence and a
  real post-change write test before declaring resolution.
- **`work_mem` multiplies with sessions and plan nodes** -> report connection
  limits and active sessions; do not raise it beyond the documented 16 MiB
  baseline without a separate capacity review.
- **Manual retry can encounter partial residue** -> preserve the existing
  task-hash-scoped cleanup and test that it cannot affect similarly named
  documents.
- **Global LLM throttling reduces throughput** -> keep the setting recovery-only
  and require measured stage concurrency before any increase.

## Migration Plan

1. Deploy the failure-contract and health-check changes before the maintenance
   window.
2. Identify topology. For Compose apply the documented limits; for external PG
   obtain the equivalent DBA configuration and live `SHOW` evidence.
3. During the approved write pause, capture health output and logical-backup
   evidence, rebuild discovered indexes transactionally, then verify catalog
   readiness and capacity.
4. Restore API/Worker admission and run the explicit MP4 write/retrieval
   acceptance. Roll back settings and restart PostgreSQL if validation fails.

## Open Questions

None. Production execution remains an operator action after the maintenance
window and backup are confirmed.
