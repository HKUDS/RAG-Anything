## ADDED Requirements

### Requirement: Table chunk template places analysis before raw structure
The table chunk template SHALL position the LLM-generated `Analysis` section before the raw `Structure` section, so that the readable description appears early in the chunk content within the LLM's effective attention window.

#### Scenario: LLM receives table chunk context
- **WHEN** a table chunk is included in RRF retrieval context
- **THEN** the `Analysis` section (human-readable table description) SHALL appear before the `Structure` section (raw bbox data)

#### Scenario: Structure is too long
- **WHEN** the raw `Structure` data exceeds 2000 characters
- **THEN** the system SHALL truncate it and append a truncation notice, ensuring the `Analysis` section is not buried

### Requirement: Table structure data is simplified in chunks
The `Structure` field in table chunks SHALL include only the `text` content and positional information necessary to understand row/column relationships. Redundant metadata (bbox coordinates, header flags, fillable flags, section markers) SHALL be stripped to reduce noise.

#### Scenario: Table chunk structure simplification
- **WHEN** a table with 20 cells is processed into a chunk
- **THEN** the `Structure` field SHALL contain only `{row, col, text}` for each cell, not the full bbox data
