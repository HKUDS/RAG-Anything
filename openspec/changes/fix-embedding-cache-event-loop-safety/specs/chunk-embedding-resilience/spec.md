## MODIFIED Requirements

### Requirement: Per-chunk embedding resilience
The system SHALL embed multimodal chunks individually rather than as a batch, so that a single chunk exceeding token limits or experiencing embedding-cache degradation does not block the remaining chunks.

#### Scenario: One chunk fails embedding
- **WHEN** one chunk out of 75 fails with a token-limit error during embedding
- **THEN** that chunk SHALL be skipped with a warning log, and the remaining 74 SHALL be successfully embedded

#### Scenario: All chunks succeed
- **WHEN** all chunks are within embedding limits
- **THEN** all chunks SHALL be embedded successfully with no difference from batch behavior

#### Scenario: Multiple chunks fail
- **WHEN** N chunks fail embedding
- **THEN** a single warning SHALL be logged with the failure count, and the remaining chunks SHALL be embedded successfully

#### Scenario: Cache access degrades
- **WHEN** a PostgreSQL embedding-cache read or write fails while embedding a chunk
- **THEN** the chunk SHALL continue through the raw embedding provider and vector-store write path
