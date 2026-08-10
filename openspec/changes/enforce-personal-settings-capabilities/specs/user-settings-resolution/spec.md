## MODIFIED Requirements

### Requirement: Revisioned sparse user settings resolve to explicit effective values
The system SHALL persist user-scoped sparse `models`, `ingestion`, `retrieval`,
and `runtime` overrides in PostgreSQL with schema version, revision, and updated
time. `GET /api/users/me/settings` SHALL return `revision`, `stored`,
`effective`, `sources`, `constraints`, `fingerprint`, and ordered
`available_sections`, while omitting every task section that the caller cannot
access.

#### Scenario: User inherits defaults without a settings row
- **WHEN** an existing user with no user-settings record reads settings
- **THEN** the system returns inherited effective values only for that user's
  available sections and preserves legacy behavior for those sections

#### Scenario: User restores inheritance
- **WHEN** an authorized user PATCHes a section with `values:null` and the
  current expected revision
- **THEN** the stored override for that section is removed and the subsequent
  effective value inherits from the next precedence source

#### Scenario: Unavailable section is not projected
- **WHEN** a user lacks the capability for a section that has a stored override
- **THEN** the response retains no value, source, or constraint for that section
  while preserving the stored database value

### Requirement: Settings options and section schemas are secret-free and bounded
`GET /api/users/me/settings/options` SHALL expose only permitted task sections,
their catalog choices, and policy ranges, never provider hosts, keys, or
environment names. The server SHALL validate the `models`, `ingestion`,
`retrieval`, and `runtime` section schemas: models permit text LLM/VLM ids;
ingestion permits parser, chunk strategy/size, image/table/equation/video
toggles, entity types, and minimum relation degree; retrieval permits preset,
RRF, channel Top K, graph depth, channels, BM25 tokenizer/k1/b; runtime permits
LLM wait time and personal concurrency. `values:null` means remove exactly that
permitted section override.

#### Scenario: Options are restricted by platform policy
- **WHEN** a user requests personal settings options
- **THEN** the response includes only allowed values and ranges applicable to
  that user's permitted sections and no private provider configuration

#### Scenario: Student requests options
- **WHEN** a user lacks both task-setting capabilities
- **THEN** the response has an empty section list and contains no model profile,
  parser, retrieval preset, or runtime-limit data

### Requirement: Settings updates use optimistic concurrency and platform constraints
`PATCH /api/users/me/settings/{section}` SHALL require `expected_revision`,
verify section capability before persistence, atomically update only the
specified permitted section, and return the new projected
stored/effective/source/constraint representation. Requested values that exceed
platform hard limits MUST be constrained and reported; stale revisions MUST
return `409 revision_conflict`; denied sections MUST return 403 without changing
the row.

#### Scenario: Concurrent settings update conflicts
- **WHEN** an authorized user sends a PATCH with a revision older than the
  stored revision
- **THEN** the system returns 409 with code `revision_conflict` and does not
  overwrite settings

#### Scenario: Requested concurrency exceeds policy
- **WHEN** an authorized user saves a personal concurrency value above the
  platform hard limit
- **THEN** the response shows the stored choice and the constrained effective
  limit with its source

#### Scenario: Denied section cannot be written
- **WHEN** a user without the section capability sends a PATCH
- **THEN** the system returns 403 before settings validation, audit profile-id
  recording, or persistence

### Requirement: Resolved settings are immutable task and request inputs
The system SHALL resolve settings once at a request/task boundary into immutable
models and SHALL NOT mutate `os.environ`, shared RAG configuration, shared
`instance.lightrag.chunking_func`, or shared retrieval state during the request.
Resolution for a new authenticated request or enqueue SHALL ignore user-stored
overrides for sections outside the caller's current capability set, then apply
platform, resource, request, and index precedence. All single, batch, folder,
content, URL, retry, and reprocess enqueue paths SHALL atomically persist and
associate a complete PostgreSQL snapshot with the queued task before it runs; a
worker SHALL read only that snapshot by task id, never task arguments,
environment, or current user settings. Missing/unreadable snapshots fail
execution explicitly.

#### Scenario: User changes settings after upload is queued
- **WHEN** a user changes a model or ingestion preference after an upload task
  is accepted
- **THEN** the queued task and its retry continue using the snapshot captured at
  enqueue time

#### Scenario: Permission is removed after an override is saved
- **WHEN** a user loses the capability for a section with a stored override and
  starts a new request or upload
- **THEN** the new work inherits the platform value for that section while the
  stored override and previously queued snapshots remain unchanged

#### Scenario: Requested profile becomes unavailable
- **WHEN** the resolved profile is unavailable at execution time
- **THEN** the affected operation returns 503 with an explicit profile/configuration
  error and does not silently substitute another profile
