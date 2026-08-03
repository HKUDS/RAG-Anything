## MODIFIED Requirements

### Requirement: Resolved settings are immutable task and request inputs
The system SHALL resolve settings once at a request/task boundary into immutable models and SHALL NOT mutate `os.environ`, shared RAG configuration, shared `instance.lightrag.chunking_func`, or shared retrieval state during the request. All single, batch, folder, content, URL, retry, and reprocess enqueue paths SHALL atomically persist and associate a complete PostgreSQL snapshot with the queued task before it runs; a worker SHALL read only that snapshot by task id, never task arguments, command-line configuration, environment, or current user settings. Missing/unreadable snapshots fail execution explicitly.

#### Scenario: User changes settings after upload is queued
- **WHEN** a user changes a model or ingestion preference after an upload task is accepted
- **THEN** the queued task and its retry continue using the snapshot captured at enqueue time

#### Scenario: Requested profile becomes unavailable
- **WHEN** the resolved profile is unavailable at execution time
- **THEN** the affected operation returns 503 with an explicit profile/configuration error and does not silently substitute another profile

#### Scenario: Worker command-line input conflicts with its snapshot
- **WHEN** a queued worker receives legacy ingestion command-line fields that differ from the persisted task snapshot
- **THEN** it ignores those fields and uses only the persisted snapshot
