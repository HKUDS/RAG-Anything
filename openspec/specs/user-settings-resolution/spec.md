# user-settings-resolution Specification

## Purpose
TBD - created by archiving change redesign-personal-settings-center. Update Purpose after archive.
## Requirements
### Requirement: Revisioned sparse user settings resolve to explicit effective values
The system SHALL persist user-scoped sparse `models`, `ingestion`, `retrieval`, and `runtime` overrides in PostgreSQL with schema version, revision, and updated time. `GET /api/users/me/settings` SHALL return `revision`, `stored`, `effective`, `sources`, `constraints`, and `fingerprint`.

#### Scenario: User inherits defaults without a settings row
- **WHEN** an existing user with no user-settings record reads settings
- **THEN** the system returns inherited effective values with their sources and preserves legacy behavior

#### Scenario: User restores inheritance
- **WHEN** a user PATCHes a section with `values:null` and the current expected revision
- **THEN** the stored override for that section is removed and the subsequent effective value inherits from the next precedence source

### Requirement: Settings options and section schemas are secret-free and bounded
`GET /api/users/me/settings/options` SHALL expose only permitted catalog choices and policy ranges, never provider hosts, keys, or environment names. The server SHALL validate the `models`, `ingestion`, `retrieval`, and `runtime` section schemas: models permit text LLM/VLM ids; ingestion permits parser, chunk strategy/size, image/table/equation/video toggles, entity types, and minimum relation degree; retrieval permits preset, RRF, channel Top K, graph depth, channels, BM25 tokenizer/k1/b; runtime permits LLM wait time and personal concurrency. `values:null` means remove exactly that section override.

#### Scenario: Options are restricted by platform policy
- **WHEN** a user requests personal settings options
- **THEN** the response includes only allowed values and ranges applicable to that user and no private provider configuration

### Requirement: Settings updates use optimistic concurrency and platform constraints
`PATCH /api/users/me/settings/{section}` SHALL require `expected_revision`, atomically update only the specified section, and return the new stored/effective/source/constraint representation. Requested values that exceed platform hard limits MUST be constrained and reported; stale revisions MUST return `409 revision_conflict`.

#### Scenario: Concurrent settings update conflicts
- **WHEN** a user sends a PATCH with a revision older than the stored revision
- **THEN** the system returns 409 with code `revision_conflict` and does not overwrite settings

#### Scenario: Requested concurrency exceeds policy
- **WHEN** a user saves a personal concurrency value above the platform hard limit
- **THEN** the response shows the stored choice and the constrained effective limit with its source

### Requirement: Resolved settings are immutable task and request inputs
The system SHALL resolve settings once at a request/task boundary into immutable models and SHALL NOT mutate `os.environ`, shared RAG configuration, shared `instance.lightrag.chunking_func`, or shared retrieval state during the request. All single, batch, folder, content, URL, retry, and reprocess enqueue paths SHALL atomically persist and associate a complete PostgreSQL snapshot with the queued task before it runs; a worker SHALL read only that snapshot by task id, never task arguments, environment, or current user settings. Missing/unreadable snapshots fail execution explicitly.

#### Scenario: User changes settings after upload is queued
- **WHEN** a user changes a model or ingestion preference after an upload task is accepted
- **THEN** the queued task and its retry continue using the snapshot captured at enqueue time

#### Scenario: Requested profile becomes unavailable
- **WHEN** the resolved profile is unavailable at execution time
- **THEN** the affected operation returns 503 with an explicit profile/configuration error and does not silently substitute another profile

### Requirement: Retrieval state and caches are scoped to immutable options
`HybridSearchEngine.search()` SHALL accept local retrieval options and MUST NOT change shared `_enabled_channels`. BM25 index keys SHALL be `workspace + corpus_revision + tokenizer + k1 + b`; equal keys may share bounded read-only indexes, while different keys MUST remain isolated under LRU eviction. Query, LLM, and instance cache keys SHALL include workspace, permission scope, content revision, and settings fingerprint.

#### Scenario: Two users use different retrieval channels concurrently
- **WHEN** two users query the same KB with distinct resolved retrieval options
- **THEN** each result uses only its local options and neither request changes the other's channels or cache identity

### Requirement: Required settings lifecycle events are safely audited
The system SHALL audit personal profile/settings section changes, model switches, KB vector switches, reindex queued/succeeded/failed, and platform policy changes using only actor, section, profile id, KB, revision, and result. Passwords, keys, hosts, and environment variable names MUST NOT be stored in audit details.

#### Scenario: Failed reindex audit contains no secret configuration
- **WHEN** a KB visual-profile reindex fails
- **THEN** the audit record identifies the KB/profile and outcome without credentials or provider endpoint details

### Requirement: Account updates are verified and audited without secrets
The system SHALL return non-secret user profile data from `GET /api/auth/me` without any email field, provide username update at `PUT /api/auth/me/profile` after current-password verification, and normalize the current-password verification behavior of `PUT /api/auth/me/password`. Successful updates SHALL preserve the session, refresh authentication context, and audit only non-secret result metadata.

#### Scenario: Profile update with correct password
- **WHEN** an authenticated user submits a valid new username and current password
- **THEN** the system persists the username, preserves login, and returns refreshed non-secret user data without any email field

#### Scenario: Incorrect password never enters audit data
- **WHEN** profile or password verification fails
- **THEN** the system rejects the request and audit data contains no supplied password value

