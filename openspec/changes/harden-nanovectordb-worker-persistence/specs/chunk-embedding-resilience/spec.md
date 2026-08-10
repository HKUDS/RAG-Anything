## MODIFIED Requirements

### Requirement: Per-chunk embedding resilience
The system SHALL embed multimodal chunks individually rather than as a batch,
so that a single chunk exceeding token limits or a failed durable vector
persistence callback does not cause the system to report incomplete vectors as
a successfully indexed document.

#### Scenario: One chunk fails embedding
- **WHEN** one chunk out of 75 fails with a token-limit error during embedding
- **THEN** that chunk SHALL be skipped with a warning log, and the remaining 74
  SHALL be successfully embedded

#### Scenario: All chunks succeed
- **WHEN** all chunks are within embedding limits and vector persistence succeeds
- **THEN** all chunks SHALL be embedded and durably persisted with no difference
  from batch behavior

#### Scenario: Multiple chunks fail
- **WHEN** N chunks fail embedding
- **THEN** a single warning SHALL be logged with the failure count, and the
  remaining chunks SHALL be successfully embedded

#### Scenario: Vector persistence fails after embedding
- **WHEN** all generated chunk embeddings cannot be persisted by NanoVectorDB
- **THEN** the Worker SHALL fail the document processing lifecycle rather than
  report it successfully indexed
