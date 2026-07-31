## ADDED Requirements

### Requirement: Visual embedding profile is a KB-owned setting
The system SHALL expose `GET` and `PUT /api/kb/{kb}/vision-settings` to KB owners or callers with `kb:write`. A visual embedding profile and dimension SHALL be stored on KB metadata rather than user settings; the setting response SHALL identify the active profile and compatibility state.

#### Scenario: Authorized KB owner reads vision settings
- **WHEN** a KB owner requests vision settings
- **THEN** the system returns the active visual profile and index state without exposing provider secrets

#### Scenario: Unauthorized user changes vision settings
- **WHEN** a user without KB write access updates visual settings
- **THEN** the system returns 403 and does not modify KB metadata

### Requirement: Populated visual vector spaces require safe reindex switching
The system SHALL validate target availability, dimension, and compatibility before an empty visual-vector space switches immediately. For a populated space, a profile change without `reindex=true` MUST return `409 reindex_required`; a request with `reindex=true` MUST return `202` with a task id and build the target profile index beside the active one under one active per-KB PostgreSQL lease with heartbeat.

#### Scenario: Immediate switch for KB with no visual vectors
- **WHEN** an authorized caller selects an available visual embedding profile for a KB without visual vectors
- **THEN** the system atomically updates active metadata without creating a reindex task

#### Scenario: Reindex is explicitly confirmed
- **WHEN** an authorized caller changes a populated KB visual profile with `reindex=true`
- **THEN** the system returns 202 and a task id while the old profile remains active for queries

### Requirement: Vector persistence and queries are profile-scoped
The system SHALL record profile id, profile fingerprint, and embedding dimension on visual vector records; NanoVectorDB persistence SHALL use separate files per profile. Queries SHALL filter by workspace, active profile, and profile fingerprint. During reindex, upload and multimodal reprocessing MUST return 409; successful completion atomically activates the target index, invalidates caches, and then cleans old derived data, while failure removes only target data and retains the old index.

#### Scenario: Reindex failure preserves active index
- **WHEN** target visual-index creation fails
- **THEN** the system cleans target index data, leaves the previous profile active, and audits failure

#### Scenario: Cross-dimension reindex succeeds
- **WHEN** a target embedding profile has a different dimension and background reindex completes
- **THEN** active KB metadata and query filtering switch atomically to the target profile/dimension
