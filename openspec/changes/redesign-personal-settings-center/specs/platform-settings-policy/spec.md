## ADDED Requirements

### Requirement: Platform policy is typed, durable, and credential-free
The system SHALL store platform defaults, allowed values, resource hard limits, retrieval preset version, and read-only state in a typed PostgreSQL repository separate from generic/JWT settings storage. It SHALL seed legacy runtime defaults including `max_async:7` and SHALL never store or return provider hosts, keys, or key environment-variable names in platform API payloads.

#### Scenario: Administrator reads platform policy
- **WHEN** a caller with `settings:read` requests platform configuration
- **THEN** the system returns defaults, allowed values, constraints, and state without host or credential fields

#### Scenario: Runtime defaults migration
- **WHEN** the platform policy repository is initialized with existing runtime settings
- **THEN** its default personal concurrency baseline retains the configured `max_async` value of 7

### Requirement: Platform policy administration is RBAC-protected and audited
The system SHALL require `settings:read` to view platform policy and `settings:write` to modify it. Writes SHALL validate typed ranges/allow-lists, use optimistic revision control, and audit actor, changed section, revision, and result.

#### Scenario: Editor cannot change platform limits
- **WHEN** a user lacking `settings:write` submits a platform-policy update
- **THEN** the system returns 403 and leaves the policy unchanged

#### Scenario: Invalid allowed model is rejected
- **WHEN** an administrator adds a model id absent from the server catalog to an allow-list
- **THEN** the system rejects the write with a validation error

### Requirement: Personal concurrency is enforced through durable leases
The system SHALL enforce user concurrency through PostgreSQL leases with expiry and heartbeat, subject to provider and worker global hard limits. Interactive work SHALL wait only for its configured bounded interval before returning 429; ingestion work SHALL remain queued.

#### Scenario: Interactive request exceeds personal quota
- **WHEN** all active leases for a user consume that user's effective limit beyond the configured wait interval
- **THEN** the interactive request returns 429 and the active lease records remain intact

#### Scenario: Worker crash releases expired quota
- **WHEN** a worker stops heartbeating a lease past its expiry
- **THEN** another worker can reclaim the quota capacity without manual cleanup
