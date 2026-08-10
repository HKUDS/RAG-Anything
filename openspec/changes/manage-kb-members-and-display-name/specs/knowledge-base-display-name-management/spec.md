## ADDED Requirements

### Requirement: KB display names can be updated without changing identity
An authorized caller SHALL update only `kb_metadata.display_name` through a
KB metadata API.  The request SHALL include the current metadata version and
the service SHALL reject a stale version with 409 Conflict.  The internal KB
name, workspace, indexes, documents, ownership, and grant rows SHALL remain
unchanged and the successful update SHALL be audited.

#### Scenario: Concurrent display-name update is rejected
- **WHEN** a caller submits a display-name update with an outdated metadata version
- **THEN** the service SHALL return 409 Conflict and preserve the current display name

#### Scenario: Display-name update preserves stable KB data
- **WHEN** an authorized caller successfully changes a KB display name
- **THEN** the internal KB name and all dependent workspace, document, index, and grant identities SHALL remain unchanged
