## ADDED Requirements

### Requirement: Knowledge-base ingestion defaults are sparse and revisioned
The system SHALL persist only explicit ingestion overrides in `kb_metadata.extra.ingestion_defaults`, SHALL preserve unrelated metadata, and SHALL expose a monotonically increasing revision for optimistic updates.

#### Scenario: Empty KB settings inherit
- **WHEN** a knowledge base has no `ingestion_defaults` object or an empty object
- **THEN** its new upload tasks inherit platform and personal settings without materializing effective values into KB metadata

#### Scenario: Stale KB update is rejected
- **WHEN** a client PUTs ingestion settings with an `expected_revision` different from the stored revision
- **THEN** the API returns HTTP 409 and leaves the existing KB settings unchanged

### Requirement: KB ingestion settings API is capability and scope protected
The system SHALL provide `GET /kb/{kb}/ingestion-settings` and `PUT /kb/{kb}/ingestion-settings`, SHALL enforce KB access, SHALL require `kb:write` for writes, and SHALL validate parser, chunking, and ingestion values against the shared settings schema and platform policy.

#### Scenario: Authorized writer reads effective settings
- **WHEN** a user with KB read access requests the endpoint for an accessible KB
- **THEN** the response includes `stored`, `effective`, `sources`, `constraints`, and `revision` without exposing credentials or unrelated platform settings

#### Scenario: Student cannot write KB settings
- **WHEN** a student submits a PUT for an accessible KB
- **THEN** the API returns HTTP 403 and does not persist any value

#### Scenario: Invalid parser is rejected
- **WHEN** a writer submits a parser or per-file parser that is unsupported or disallowed by platform policy
- **THEN** the API returns HTTP 422 and preserves the prior settings

### Requirement: New upload tasks resolve KB settings before request overrides
All file, batch, folder, URL, and pasted-content upload routes SHALL resolve settings in this order: environment compatibility defaults, platform defaults, personal defaults, KB ingestion defaults, explicit request overrides, then index compatibility and platform hard limits. The resulting effective values SHALL be persisted in the immutable task snapshot.

#### Scenario: KB defaults beat personal defaults
- **WHEN** a user personal default and the target KB both set the same ingestion field
- **THEN** the new task snapshot contains the KB value and marks its source as the KB layer

#### Scenario: One-upload override wins
- **WHEN** an upload request explicitly supplies a supported ingestion override
- **THEN** the task snapshot contains that request value and later retries reuse it without re-reading current personal or KB settings

#### Scenario: Platform constraint still wins
- **WHEN** the KB or request asks for a value outside a platform allow-list or hard limit
- **THEN** the effective snapshot is rejected or constrained according to existing settings policy and the response identifies the constraint

### Requirement: Knowledge-base UI separates defaults from one-upload choices
The preferences page SHALL describe ingestion controls as personal upload defaults. The knowledge-base detail page SHALL show the current KB effective source, expose persistent KB defaults only to `kb:write` users, and keep one-upload overrides visibly scoped to the current upload.

#### Scenario: Student sees read-only KB detail
- **WHEN** a student opens an accessible knowledge base
- **THEN** the page shows documents and read-only processing status without upload, KB-default editing, retry, cancel, or delete controls

#### Scenario: Writer resets one-upload overrides
- **WHEN** a KB writer chooses reset for the current upload
- **THEN** the upload controls return to the current KB effective values without changing personal or KB defaults
