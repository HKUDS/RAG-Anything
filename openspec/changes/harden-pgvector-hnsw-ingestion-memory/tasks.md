## 1. Terminal Failure Contract

- [x] 1.1 Classify chained PostgreSQL HNSW memory errors in the Worker and emit the stable graph-index error envelope.
- [x] 1.2 Add a fenced HNSW terminal-finalization path that bypasses degraded completion, repair, tagging, and automatic retry.
- [x] 1.3 Terminalize a held retry lease and permit only explicit retry-now recovery with task-scoped residue cleanup.

## 2. Recovery Configuration and Operations

- [x] 2.1 Add the Compose-only PostgreSQL 4 GiB recovery profile, shared-memory settings, and explicit HNSW/LLM concurrency environment values.
- [x] 2.2 Add a credential-safe read-only HNSW health-check script that discovers runtime catalog objects and reports capacity evidence.
- [x] 2.3 Document topology-aware preflight, write pause, transactional index rebuild, verification, and rollback operations.

## 3. Verification and Records

- [x] 3.1 Add focused Worker, coordinator, retry-lifecycle, and health-check tests for HNSW terminal failure and guarded manual recovery.
- [x] 3.2 Run focused and full validation, OpenSpec strict validation, diff checks, and record the implemented facts in PROJECT_SUMMARY.md.
