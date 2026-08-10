## Why

PostgreSQL HNSW relation-vector writes have exhausted the server's memory and
caused multimodal documents to fail after partial graph work. Retrying the
same write does not restore capacity and must not result in a false completed
document.

## What Changes

- Set an explicit, bounded PostgreSQL memory profile and HNSW parameters for
  the Compose deployment, with a recovery-time global LLM concurrency of one.
- Classify PostgreSQL HNSW memory exhaustion as a stable non-retryable Worker
  failure at the graph-index stage and prevent the generic degraded-completion
  path from reclassifying it as successful.
- Add a credential-safe, read-only health check for pgvector/HNSW capacity and
  an operator runbook for a drained-write maintenance window and index rebuild.
- Add regression coverage for failure classification, fenced retry-job closure,
  and explicit recovery without duplicate graph/vector records.

## Capabilities

### New Capabilities

- `pgvector-hnsw-operations`: Read-only capacity inspection and a controlled
  PostgreSQL HNSW maintenance procedure.

### Modified Capabilities

- `upload-failure-detection`: Graph-index HNSW memory exhaustion has an
  explicit terminal, non-retryable upload failure contract.
- `perf-config-defaults`: The deployment defaults constrain graph write
  concurrency during HNSW recovery.

## Impact

Affected areas are the isolated Worker error envelope, upload retry lifecycle,
LightRAG concurrency configuration, Docker Compose PostgreSQL runtime settings,
operational documentation, and focused PostgreSQL regression tests. The
existing retry-now endpoint retains its route but gains guarded manual recovery
semantics for this terminal error. No database schema changes are introduced.
