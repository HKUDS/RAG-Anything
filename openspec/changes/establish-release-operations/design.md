## Context

The composed production topology has a PostgreSQL 16 service (`pgdata` volume), Redis 7 (`redisdata` volume), and application bind mounts for `rag_storage`, `uploads`, and `output`. The application reads its server-owned model-profile catalog read-only. PostgreSQL is required at application startup and holds users/RBAC, token revocation, audit, task, knowledge-base, agent/conversation, and configured PostgreSQL-backed RAG state. Redis is configured as a service dependency, but its durable application responsibility must be verified per deployment rather than inferred from the Compose volume.

`GET /api/health` is a public compatibility endpoint that currently returns `ok` or `degraded` and component details. `/metrics` is exposed by the FastAPI instrumentator. Neither is yet a release-grade separation of process liveness, dependency readiness, and degraded-service signalling. This change is owner-scoped to operations assets and must not modify the current server or routing entry points.

Stakeholders are the platform administrator who owns secrets and deployment access, the on-call operator who performs a time-bounded recovery, and the shared-entrypoint coordinator who owns any later health-contract implementation.

## Goals / Non-Goals

**Goals:**

- Establish a formal production asset inventory and a first release target of RPO <= 24 hours and RTO <= 2 hours.
- Produce executable, secret-safe backup, verification, and isolated-restore scripts that can be invoked by a non-development operator with deployment-owned configuration.
- Make a successful backup self-describing through a manifest and SHA-256 checksums, and make restore validation observable through a drill evidence template.
- Provide Prometheus scrape/recording/alert configuration and a runbook that turns alerts into actionable on-call steps.
- Define a precise future health interface without modifying shared Python entry points.

**Non-Goals:**

- Implementing or changing `server.py`, health routes, auth/RBAC code, migrations, Docker/Compose, nginx, CI workflows, or business behaviour.
- Delivering database WAL archiving/PITR, automatic remote replication, a secrets manager, or an HA topology in this first release.
- Claiming that an external graph/vector database or a model cache is recoverable without the owner supplying its native backup/export contract.
- Restoring directly into a running production deployment.

## Decisions

### 1. Treat backup as an application-consistent release bundle

Each backup creates one timestamped directory outside the active runtime roots, containing: a PostgreSQL logical dump; selected file assets; a UTF-8 JSON manifest; and a checksum file. The manifest includes schema version, creation time in UTC, tool version, asset identifiers, relative artifact paths, byte counts, SHA-256 values, database dump format, and source revision label if provided. It MUST NOT contain a DSN, password, token, raw environment file, file content, or user data.

The bundle is complete only after checksum verification succeeds. Database export uses `pg_dump` with an explicit deployment-provided connection source and a custom/archive format suitable for `pg_restore --clean --if-exists` into an empty isolated database. File asset copying uses an archive format that preserves relative paths and supports an allowlisted extraction.

Alternatives considered:

- Copying PostgreSQL volume files: rejected because a filesystem copy is not a portable application-consistent backup while the database is running.
- Backing up only the database: rejected because original uploads and controlled parser/media artifacts are referenced by durable state.
- Backing up the entire repository or `.env`: rejected because source code and secrets are not production data assets and would widen secret exposure.

### 2. Define assets and responsibility explicitly

The backup inventory is configured using paths and identifiers, never credentials. Required first-party assets are PostgreSQL, `rag_storage`, `uploads`, `output` (including accepted `output_*` roots only when declared), and the server-owned model/config files explicitly selected by the deployment. Configuration backup is limited to sanitized/secret-excluded deployment configuration and a separately provisioned encrypted secret recovery process. Model directories are included only when the deployment declares that models are locally managed and licensing/storage policy permits them; otherwise the manifest records the model artifact as externally reproducible.

Redis is classified as a deployment-dependent cache/queue state: the runbook requires the operator to decide and record whether it is recoverable or rebuildable for that deployment. An external graph/vector store is not implicitly covered. Its owner must deliver a consistent snapshot/export, restore command, checksum/freshness signal, and dependency readiness signal; absent this, the application is degraded and the release is not fully recoverable.

### 3. Use encrypted off-site copies with separation of duties

The backup script produces a local verified bundle only. A deployment wrapper encrypts that bundle using an operator-supplied recipient or key reference and transfers it to an off-site object store or backup system with immutable/versioned retention. The repository stores configuration examples with placeholder environment-variable names only. Backup writers, encryption-key custodians, and restore approvers use separate least-privilege identities; successful jobs publish timestamps and checksums but never secrets.

First-release policy is daily full backups, at least 35 daily recovery points, 12 monthly recovery points, quarterly restore drills, and a second-site copy completed within 24 hours. Retention changes require documented data-owner approval.

### 4. Restore only into an isolated target and validate semantic references

The restore script refuses a non-empty target root unless an explicit operator confirmation flag is supplied, refuses paths outside its target root, verifies checksums before extraction, creates/uses a named isolated database, and writes evidence only under the specified drill directory. It never contacts production destinations.

Validation is a separate command and checks: database reachability; expected RBAC roles and user/role relations without logging identities; audit and token-revocation table availability; KB metadata and per-KB workspace existence; uploaded-file metadata against restored `uploads`; and controlled media references resolving beneath declared restored output roots. Validation reports aggregate counts and failing identifiers hashed or redacted.

Alternatives considered:

- Restoring in place: rejected because it risks overwriting production and cannot distinguish recovery success from accidental data loss.
- File existence only: rejected because it misses broken durable references and authorization data.

### 5. Publish operations configuration independently from application code

Prometheus integration is supplied as deploy-owned examples: scrape jobs, recording rules, alert rules, and Alertmanager routing placeholders. Rules cover request availability/error rate and latency from the existing metrics endpoint, PostgreSQL and Redis exporters, host/filesystem metrics, upload queue metrics once exposed, SSE error-rate metrics once exposed, backup-freshness textfile/push metric, and TLS certificate-expiry metrics. Rules label severity and runbook URL, use `for` durations to reduce flapping, and identify unavailable metrics as integration prerequisites rather than pretending the metric exists.

The following shared-entrypoint interface is a proposal for separate approval:

| Endpoint | HTTP | Body contract | Meaning |
|---|---:|---|---|
| `GET /api/live` | 200 | `{status:"live", version}` | Process/event loop can answer; no dependency checks. |
| `GET /api/ready` | 200/503 | `{status:"ready"|"not_ready", checks:{name:{status,required}}}` | Required startup dependencies, migrations/schema compatibility, writable operational roots, and durable upload recovery are usable. |
| `GET /api/health` | 200/503 | `{status:"ok"|"degraded"|"failed", components, version}` | Compatibility aggregate; 200 for usable-but-degraded, 503 for failed required service. No secret or user data. |

The owner must confirm exact dependency checks, status-code compatibility, and metric names before implementation. Acceptance cases include a healthy process with a failed required PG check returning `ready=503`, a non-required external vector dependency returning `health=200/degraded`, and no component error revealing a DSN or exception details.

## Risks / Trade-offs

- [A daily schedule can miss nearly 24 hours of data] -> Schedule completion monitoring at < 26 hours, record completed timestamps, and require an incident when freshness exceeds the RPO.
- [Logical dumps can be slow for large databases] -> Measure dump/restore during drills; promote to physical backups/PITR only when the two-hour RTO is not met.
- [File and database snapshots are not perfectly simultaneous] -> Record start/end timestamps and assessed RPO; quiesce uploads during a future consistency-window enhancement if evidence exposes cross-asset gaps.
- [Encrypted off-site copies can be unrecoverable if key custody is weak] -> Test key-access procedure during each drill with separate approval and never embed keys in scripts or manifests.
- [Existing metrics lack upload queue, SSE-error, backup-freshness, or certificate signals] -> Mark each as an integration gap and alert only after its source/exporter is deployed and verified.
- [REST health changes can affect load balancers] -> Keep the current endpoint unchanged in this change and route implementation through a shared-entrypoint owner.

## Migration Plan

1. Deploy the scripts, configuration examples, and runbook without enabling destructive restore commands.
2. Create a protected backup service identity and separate encrypted off-site destination; configure only environment-variable references.
3. Execute an initial local backup, checksum verification, encryption/off-site transfer, and isolated restore drill. Record actual start/end times and calculated RPO/RTO in the evidence template.
4. Enable the daily scheduler outside this repository and wire backup freshness plus platform/exporter alerts.
5. Obtain owner approval and implement the proposed health contract in a separate change, then adjust probe configuration only after endpoint acceptance tests pass.

Rollback consists of disabling the external scheduler and alert routes, revoking the backup identity, and retaining completed encrypted bundles per the approved retention policy. Scripts do not alter production data.

## Open Questions

- Which off-site backup system, encryption mechanism, and key-custody owner are approved for production?
- Is Redis authoritative for any production queue at deployment time, and if so what persistence/RPO contract applies?
- Which external graph/vector stores are enabled in each production environment, and who owns their export/restore runbooks?
- Are local model weights licensed and sized for backup, or should models be restored through an immutable registry/cache?
- Who owns the shared health endpoints and which component checks are required versus degradable?
