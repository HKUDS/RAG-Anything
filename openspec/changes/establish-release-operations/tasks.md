## 1. Asset Boundary and Backup Tooling

- [x] 1.1 Create `scripts/ops/` backup configuration contract with non-secret environment-variable references, allowlisted asset roots, model/external-store classification, and safe output locations.
- [x] 1.2 Implement the PostgreSQL logical-dump and file-asset backup command, including manifest generation, SHA-256 checksums, secret redaction, failure cleanup, and explicit no-live-runtime-output guardrails.
- [x] 1.3 Implement an offline bundle verification command that validates manifest schema, paths, sizes, and checksums without loading user content or secrets.
- [x] 1.4 Add unit tests under `tests/ops/` for asset allowlisting, secret redaction, manifest/checksum correctness, incomplete backups, and verification failures.

## 2. Isolated Restore and Recovery Validation

- [x] 2.1 Implement a restore command that requires an explicit isolated root and isolated PostgreSQL target, verifies a bundle first, rejects unsafe/non-empty targets by default, and never targets production paths.
- [x] 2.2 Implement a post-restore validation command for aggregate PostgreSQL/RBAC, audit, KB workspace, upload reference, and controlled-media reference checks with redacted diagnostics.
- [x] 2.3 Add hermetic restore tests using temporary paths and a stubbed PostgreSQL command interface, including unsafe-target refusal and missing/broken reference detection.
- [x] 2.4 Create a drill evidence template and record-location convention for backup identifier, timing, calculated RPO/RTO, validation result, exception, approval, and follow-up owner.

## 3. Deployment Policy and Alert Configuration

- [x] 3.1 Add deploy-owned examples for daily backup scheduling, encrypted off-site copy invocation, retention, least-privilege identities, and backup freshness metric publication; keep credentials and recipients outside the repository.
- [x] 3.2 Add Prometheus scrape, recording, and alert-rule examples for application availability/error/latency, PostgreSQL, Redis, filesystem capacity, upload queue, SSE error rate, backup freshness, and certificate expiry.
- [x] 3.3 Mark unavailable metric sources with their integration owner, expected metric name/query, and acceptance check instead of enabling unsupported alerts.
- [x] 3.4 Add configuration/source-contract tests for alert severity, `for` duration, runbook link, and required alert categories.

## 4. Operator Runbook and Shared-Endpoint Handoff

- [x] 4.1 Write the Chinese administrator runbook covering asset boundary, RPO/RTO policy, routine backup verification, alert triage, severity levels, on-call acknowledgement, escalation, isolated restore, acceptance, and post-incident evidence.
- [x] 4.2 Publish the precise `GET /api/live`, `GET /api/ready`, and compatibility `GET /api/health` interface proposal, status codes, dependency classifications, security constraints, and acceptance cases for the shared-entrypoint coordinator.
- [x] 4.3 Obtain shared-entrypoint owner approval before changing `server.py` or any health route; if not approved, retain the documented integration gap and do not implement it in this change. (2026-08-04: coordinator-owned integration authorized and implemented `/api/live`, `/api/ready`, and sanitized compatibility `/api/health` in the shared admin router.)
- [x] 4.4 Execute the focused operations test suite and one isolated restore drill where approved tooling and an isolated PostgreSQL target are available; record exact passed checks and environment-blocked evidence. (2026-08-04: real PostgreSQL 16.3 drill created temporary source/destination databases, completed `backup` -> `verify` -> `restore` -> `validate`, verified a database marker and archived asset, then removed both databases and the temporary root. Docker/TLS/staging evidence remains environment-blocked.)

## 5. Closeout and Handoff

- [x] 5.1 Produce deployment/CI/health integration handoff: required environment-variable names, scheduler/exporter/secret-manager responsibilities, external-store owners, and rollback steps.
- [x] 5.2 Submit the project-summary delta to the sole coordinator, including the release status, verified RPO/RTO evidence or remaining gaps, and no-secret operational facts; do not modify `PROJECT_SUMMARY.md` directly from a parallel task.
