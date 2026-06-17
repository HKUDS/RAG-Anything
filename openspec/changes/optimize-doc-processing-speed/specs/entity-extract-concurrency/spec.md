## ADDED Requirements

### Requirement: Entity extraction runs with configurable concurrency
The system SHALL support a configurable concurrency level for LLM-based entity extraction across document chunks, controlled by the `ENTITY_EXTRACT_CONCURRENCY` environment variable (default: 3).

#### Scenario: Default concurrency of 3
- **WHEN** `ENTITY_EXTRACT_CONCURRENCY` is not set
- **THEN** entity extraction SHALL process up to 3 chunks concurrently via `asyncio.Semaphore(3)`

#### Scenario: User-defined concurrency
- **WHEN** `ENTITY_EXTRACT_CONCURRENCY` is set to 5
- **THEN** entity extraction SHALL process up to 5 chunks concurrently

#### Scenario: Concurrency set to 1 (backward compatible)
- **WHEN** `ENTITY_EXTRACT_CONCURRENCY` is set to 1
- **THEN** entity extraction SHALL behave as the current serial implementation, processing chunks one at a time

### Requirement: Entity extraction concurrency respects API rate limits
The system SHALL implement an adaptive retry mechanism that reduces concurrency when embedding or LLM API returns 429 (rate limit) responses.

#### Scenario: Rate limit backoff
- **WHEN** the embedding API returns a 429 status code during concurrent extraction
- **THEN** the system SHALL reduce concurrent calls by 50% for the next 60 seconds before gradually restoring

#### Scenario: Maximum retry threshold
- **WHEN** an individual chunk entity extraction fails after 3 retries
- **THEN** the system SHALL log the failure and continue processing remaining chunks without blocking the pipeline
