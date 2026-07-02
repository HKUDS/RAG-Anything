## ADDED Requirements

### Requirement: Embedding requests use batch API
The system SHALL batch multiple single-text embedding requests into a single API call when processing document chunks, controlled by the `EMBEDDING_BATCH_SIZE` environment variable (default: 20).

#### Scenario: Default batch size of 20
- **WHEN** `EMBEDDING_BATCH_SIZE` is not set
- **THEN** embedding requests SHALL be batched in groups of up to 20 texts per API call

#### Scenario: Custom batch size
- **WHEN** `EMBEDDING_BATCH_SIZE` is set to 50
- **THEN** embedding requests SHALL be batched in groups of up to 50 texts per API call

#### Scenario: Single chunk (no batching needed)
- **WHEN** embedding only 1 text
- **THEN** the system SHALL make a single API call without unnecessary batching overhead

### Requirement: Embedding batch failures are handled gracefully
The system SHALL handle batch embedding failures by falling back to individual requests for failed items.

#### Scenario: Batch API returns error
- **WHEN** a batch embedding call of 20 texts fails
- **THEN** the system SHALL retry each text individually and SHALL NOT lose any embedding data

#### Scenario: Partial batch success
- **WHEN** a batch embedding call returns results for only 18 of 20 texts
- **THEN** the system SHALL retry only the 2 missing texts individually

### Requirement: Embedding batch size is configurable via environment variable
The system SHALL read `EMBEDDING_BATCH_SIZE` at startup and apply it globally across all document processing tasks.

#### Scenario: Configuration change takes effect on next upload
- **WHEN** `EMBEDDING_BATCH_SIZE` is changed from 20 to 50
- **THEN** newly uploaded documents SHALL use batch size 50 for embedding
