## ADDED Requirements

### Requirement: Revisioned sparse user settings resolve to explicit effective values
The system SHALL persist user-scoped sparse `models`, `ingestion`, `retrieval`, and `runtime` overrides in PostgreSQL with schema version, revision, and updated time. `GET /api/users/me/settings` SHALL return `revision`, `stored`, `effective`, `sources`, `constraints`, and `fingerprint`.

#### Scenario: User inherits defaults without a settings row
- **WHEN** an existing user with no user-settings record reads settings
- **THEN** the system returns inherited effective values with their sources and preserves legacy behavior

#### Scenario: User restores inheritance
- **WHEN** a user PATCHes a section with `values:null` and the current expected revision
- **THEN** the stored override for that section is removed and the subsequent effective value inherits from the next precedence source

### Requirement: Settings updates use optimistic concurrency and platform constraints
`PATCH /api/users/me/settings/{section}` SHALL require `expected_revision`, atomically update only the specified section, and return the new stored/effective/source/constraint representation. Requested values that exceed platform hard limits MUST be constrained and reported; stale revisions MUST return `409 revision_conflict`.

#### Scenario: Concurrent settings update conflicts
- **WHEN** a user sends a PATCH with a revision older than the stored revision
- **THEN** the system returns 409 with code `revision_conflict` and does not overwrite settings

#### Scenario: Requested concurrency exceeds policy
- **WHEN** a user saves a personal concurrency value above the platform hard limit
- **THEN** the response shows the stored choice and the constrained effective limit with its source

### Requirement: Resolved settings are immutable task and request inputs
The system SHALL resolve settings once at a request/task boundary into immutable models and SHALL NOT mutate `os.environ`, shared RAG configuration, or shared retrieval state during the request. Queued and retried tasks SHALL persist and read the complete effective settings snapshot, revision, profile ids, and fingerprint from PostgreSQL.

#### Scenario: User changes settings after upload is queued
- **WHEN** a user changes a model or ingestion preference after an upload task is accepted
- **THEN** the queued task and its retry continue using the snapshot captured at enqueue time

#### Scenario: Requested profile becomes unavailable
- **WHEN** the resolved profile is unavailable at execution time
- **THEN** the affected operation returns 503 with an explicit profile/configuration error and does not silently substitute another profile

### Requirement: Account updates are verified and audited without secrets
The system SHALL return a masked email from `GET /api/auth/me`, provide atomic username/email update at `PUT /api/auth/me/profile` after current-password verification, and normalize the current-password verification behavior of `PUT /api/auth/me/password`. Successful updates SHALL preserve the session, refresh authentication context, and audit only non-secret result metadata.

#### Scenario: Profile update with correct password
- **WHEN** an authenticated user submits a valid new username/email and current password
- **THEN** the system persists both profile fields atomically, preserves login, and returns refreshed non-secret user data

#### Scenario: Incorrect password never enters audit data
- **WHEN** profile or password verification fails
- **THEN** the system rejects the request and audit data contains no supplied password value
