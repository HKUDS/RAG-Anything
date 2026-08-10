## Why

The production deployment has PostgreSQL, Redis, persistent RAG and media workspaces, and a basic health/metrics surface, but it has no documented, executable recovery standard. A release cannot be accepted without a defined data boundary, a verified backup and isolated-restore path, and an operator-facing alert and escalation procedure.

## What Changes

- Define the production data-asset boundary for PostgreSQL, `rag_storage`, `uploads`, `output`, deployment configuration, and model catalog/directory; explicitly document Redis and externally hosted graph/vector stores as separately owned dependencies.
- Add operator-owned backup, manifest verification, and isolated-restore tooling for the defined asset boundary. The tooling will avoid secret output, emit checksums and evidence metadata, and provide a restore validation workflow for RBAC, audit, knowledge-base, upload, and controlled-media references.
- Establish the first release objective: RPO <= 24 hours and RTO <= 2 hours, including frequency, retention, encryption, off-site copy, access control, and drill-evidence requirements.
- Add deployable Prometheus recording/alert rules and alert-integration guidance for application, PostgreSQL, Redis, disk, upload queue, SSE error rate, backup freshness, and certificate expiry.
- Publish an administrator runbook for probe meanings, incident severity, backup and restore, on-call acknowledgement, escalation, and post-incident evidence.
- Define, but do not implement in this change, the shared application interface required to split liveness, readiness, and degraded health semantics. Any `server.py` or health-router implementation must be separately owned and approved.

## Capabilities

### New Capabilities

- `release-backup-recovery`: Creates verifiable backup and isolated recovery procedures for the formal production asset boundary.
- `release-observability-operations`: Defines release probes, Prometheus/alert integration, incident operation, and on-call runbook requirements.

### Modified Capabilities

- None.

## Impact

- New owner-scoped files only: `scripts/ops/**`, `tests/ops/**`, `deploy/**`, `docs/ops/**`, and operations alert/backup configuration.
- PostgreSQL dump/restore tooling and a compatible archiver/checksum implementation are deployment prerequisites; encryption keys, database passwords, and remote-storage credentials remain deployment secrets and are never written to manifests, logs, or repository configuration.
- Existing `GET /api/health` remains untouched. The proposal requests a later shared-entrypoint decision for `live`, `ready`, and `degraded` endpoints and their HTTP status contract.
- No migrations, Dockerfiles, Compose, nginx, authentication core, business code, CI workflow, or project summary will be changed by this change.
