## MODIFIED Requirements

### Requirement: Settings change for image processing triggers KB rebuild
Personal image-processing settings SHALL be resolved into an immutable task snapshot at submission time rather than changing global settings or clearing all cached KB instances. KB-level visual embedding profile changes SHALL follow the guarded reindex lifecycle.

#### Scenario: Toggle image processing for a future task
- **WHEN** a user saves a new image-processing setting
- **THEN** only later tasks initiated by that user receive the new resolved setting and existing tasks/other users' cached execution state remain unchanged

### Requirement: Settings change for table processing triggers KB rebuild
Personal table-processing settings SHALL be resolved into immutable task snapshots and MUST NOT clear shared KB instances or mutate global configuration.

#### Scenario: Toggle table processing
- **WHEN** a user saves a table-processing setting
- **THEN** subsequent tasks for that user use the setting while persistent KB data and other execution contexts remain unchanged

### Requirement: Settings change for equation processing triggers KB rebuild
Personal equation-processing settings SHALL be resolved into immutable task snapshots and MUST NOT clear shared KB instances or mutate global configuration.

#### Scenario: Toggle equation processing
- **WHEN** a user saves an equation-processing setting
- **THEN** subsequent tasks for that user use the setting while persistent KB data and other execution contexts remain unchanged
