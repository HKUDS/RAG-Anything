## ADDED Requirements

### Requirement: Release probe contract
The operations package SHALL document separate liveness, readiness, and degraded-service semantics. It SHALL preserve the existing health endpoint until a shared-entrypoint owner implements an approved contract. The proposed contract SHALL specify endpoint paths, HTTP status codes, response shape, required versus degradable dependency checks, and the prohibition on secrets, user data, raw exceptions, or connection strings.

#### Scenario: Required dependency is unavailable
- **WHEN** a future readiness implementation cannot reach a required PostgreSQL dependency
- **THEN** it returns HTTP 503 with a non-sensitive `not_ready` response
- **AND** the liveness endpoint remains HTTP 200 while the process can serve the probe

#### Scenario: Optional external service is unavailable
- **WHEN** a degradable external graph or vector service is unavailable
- **THEN** the aggregate health response is `degraded` without exposing connection details
- **AND** the runbook identifies the affected user capabilities and escalation owner

### Requirement: Prometheus and alert integration contract
The operations package SHALL provide deploy-owned Prometheus scrape and alert examples for application availability/error/latency, PostgreSQL, Redis, filesystem capacity, upload queue, SSE error rate, backup freshness, and certificate expiry. Every alert SHALL declare severity, a sustained evaluation period, actionable labels, and a runbook reference. Metrics not currently emitted by the application SHALL be documented as required integration points rather than fabricated.

#### Scenario: A metric source is not yet deployed
- **WHEN** an alert category such as upload queue or SSE error rate lacks a verified metric source
- **THEN** its configuration documents the expected metric name, owner, and acceptance query
- **AND** the release checklist marks the alert as an integration dependency

#### Scenario: Alert fires for stale backup
- **WHEN** the backup-freshness metric indicates the newest verified backup is older than the RPO
- **THEN** the alert has at least warning severity and references the backup incident runbook
- **AND** the alert labels identify the deployment without user data or secrets

### Requirement: Administrator incident and on-call runbook
The operations package SHALL provide a Chinese administrator runbook usable without source-code changes. It SHALL include contact/ownership placeholders, severity definitions, acknowledgement and escalation expectations, safe diagnostic commands, backup creation and verification, isolated restore, recovery acceptance, alert triage, communication expectations, and post-incident evidence.

#### Scenario: Non-development operator responds to a critical incident
- **WHEN** a critical availability or data-protection alert is received
- **THEN** the runbook directs the operator through acknowledgement, impact classification, escalation, evidence capture, and recovery decision points
- **AND** the steps do not require editing application source or printing secrets

#### Scenario: Recovery drill is completed
- **WHEN** an operator completes an isolated restore drill
- **THEN** the runbook directs them to record timing, backup identifier, validation result, RPO/RTO assessment, exceptions, and follow-up owner in the evidence template
