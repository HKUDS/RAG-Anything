## ADDED Requirements

### Requirement: Asynchronous embedding cache respects pool loop affinity
The system SHALL perform PostgreSQL cache operations initiated by the asynchronous text-embedding provider on that provider's active event loop and SHALL NOT create a thread-local event loop to access the shared asyncpg pool.

#### Scenario: Cache hit during asynchronous embedding
- **WHEN** an embedding request contains text already cached in PostgreSQL
- **THEN** the cache read SHALL execute on the active embedding event loop
- **AND** the raw embedding provider SHALL not receive that text

#### Scenario: Cache miss during asynchronous embedding
- **WHEN** an embedding request contains uncached text
- **THEN** the raw embedding provider SHALL receive only the uncached text
- **AND** the cache write SHALL execute on the active embedding event loop
- **AND** the returned vectors SHALL retain the original input order

### Requirement: Cache availability does not block vector generation
The system SHALL treat embedding-cache I/O failures as cache degradation and SHALL continue with the raw embedding provider and vector-store write path.

#### Scenario: Cache read fails
- **WHEN** a PostgreSQL cache read raises an exception
- **THEN** the affected text SHALL be treated as a cache miss
- **AND** the raw embedding provider SHALL be called for that text

#### Scenario: Cache write fails
- **WHEN** a PostgreSQL cache write raises an exception after an embedding is generated
- **THEN** the generated embedding SHALL still be returned to the caller
- **AND** the failure SHALL be logged without embedding content or credentials
