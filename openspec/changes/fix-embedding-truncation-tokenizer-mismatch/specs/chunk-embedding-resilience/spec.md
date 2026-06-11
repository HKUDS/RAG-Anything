## ADDED Requirements

### Requirement: Character-based chunk truncation
The system SHALL truncate multimodal chunk content to a maximum of 8000 characters before embedding, independent of any tokenizer implementation, to prevent embedding API failures caused by tokenizer mismatch.

#### Scenario: Chunk under character limit
- **WHEN** chunk content is 5000 characters or fewer
- **THEN** the chunk SHALL be embedded as-is without truncation

#### Scenario: Chunk exceeds character limit
- **WHEN** chunk content exceeds 8000 characters
- **THEN** the content SHALL be truncated to exactly 8000 characters with a truncation notice appended, and the truncated version SHALL be embedded

#### Scenario: Tokenizer mismatch
- **WHEN** LightRAG's internal tokenizer (o200k_base) reports a safe token count but the qwen embedding API would count more tokens
- **THEN** the character-based truncation SHALL still keep the content within the API's 8192-token ceiling

### Requirement: Per-chunk embedding resilience
The system SHALL embed multimodal chunks individually rather than as a batch, so that a single chunk exceeding token limits does not block the remaining chunks.

#### Scenario: One chunk fails embedding
- **WHEN** one chunk out of 75 fails with a token-limit error during embedding
- **THEN** that chunk SHALL be skipped with a warning log, and the remaining 74 SHALL be successfully embedded

#### Scenario: All chunks succeed
- **WHEN** all chunks are within embedding limits
- **THEN** all chunks SHALL be embedded successfully with no difference from batch behavior

#### Scenario: Multiple chunks fail
- **WHEN** N chunks fail embedding
- **THEN** a single warning SHALL be logged with the failure count, and the remaining chunks SHALL be embedded successfully
