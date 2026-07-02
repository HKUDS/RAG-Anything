## ADDED Requirements

### Requirement: Worker reports phased processing progress
The subprocess worker SHALL report processing progress in distinct phases: parsing, chunking, entity-extraction, embedding, and graph-building.

#### Scenario: Phase sequence during document processing
- **WHEN** a document is uploaded for processing
- **THEN** the server SHALL receive progress events with phases in order: `parsing` → `chunking` → `entity-extraction` → `embedding` → `graph-building` → `complete`

#### Scenario: Phase progress includes percentage
- **WHEN** the worker is in the `entity-extraction` phase
- **THEN** each progress event SHALL include `phase: "entity-extraction"`, `current: <N>`, `total: <M>` representing chunks processed vs. total

### Requirement: Frontend displays phased progress
The frontend SHALL render processing progress as a phased progress bar with phase labels.

#### Scenario: Progress bar during upload
- **WHEN** a document is being processed
- **THEN** the user SHALL see the current phase name (e.g., "正在抽取实体...") alongside the overall percentage

#### Scenario: Phase transition is visible
- **WHEN** the processing moves from `chunking` to `entity-extraction`
- **THEN** the frontend SHALL update the phase label within 2 seconds of the transition

### Requirement: Progress reporting is backward compatible
The system SHALL continue to support existing progress API consumers that do not parse phase information.

#### Scenario: Old frontend client
- **WHEN** a frontend client ignores the new `phase` field in progress events
- **THEN** the client SHALL still display overall progress percentage as before without errors
