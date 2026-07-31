## ADDED Requirements

### Requirement: Upload failure details preserve lease-loss cause
The system SHALL preserve a structured quota lease-loss worker error through the parent upload failure handler so the task is eligible for the normal retry workflow.

#### Scenario: Worker emits a quota lease-loss error
- **WHEN** an isolated worker exits with a structured retryable `QuotaLeaseLost` error
- **THEN** the upload record SHALL store the error detail and SHALL be classified as retryable rather than an unretryable bootstrap cancellation

### Requirement: Child-worker completion status is observed durably
The system SHALL not mark an upload failed solely because a parent-process cache does not yet expose the document record committed by its isolated worker.

#### Scenario: Worker run identifiers differ from queue task identifiers
- **WHEN** a worker has persisted a processed document with an internal `track_id` that is not the upload task ID
- **THEN** the parent SHALL match the document by its filename and any explicit task-ID metadata, persist the task snapshot, and finish the upload successfully

#### Scenario: Cached document status is stale after worker completion
- **WHEN** the parent cannot find the processed document through its cached LightRAG status store
- **THEN** it SHALL query the durable PostgreSQL document-status workspace before reporting `processed_document_status_missing`
