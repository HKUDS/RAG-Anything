## ADDED Requirements

### Requirement: Beijing timezone timestamp utility
The system SHALL provide a `beijing_now()` utility function that returns the current time in Beijing timezone (UTC+8) formatted as `YYYY-MM-DDTHH:MM:SS+08:00`.

#### Scenario: beijing_now returns correct format
- **WHEN** `beijing_now()` is called
- **THEN** the returned string matches the pattern `YYYY-MM-DDTHH:MM:SS+08:00`
- **AND** the time value represents current Beijing time (UTC+8)

#### Scenario: beijing_now is importable from utils
- **WHEN** a module executes `from raganything.utils import beijing_now`
- **THEN** `beijing_now` is callable and returns a timestamp string

### Requirement: Document processor uses Beijing time for status timestamps
The document processor (`doc_processor.py`) SHALL use Beijing time for `updated_at` and `created_at` fields in `doc_status` records instead of UTC.

#### Scenario: Successful processing timestamp
- **WHEN** a document is successfully processed
- **THEN** the `updated_at` field in its `doc_status` record contains a Beijing time timestamp ending with `+08:00`

#### Scenario: Failed processing timestamp
- **WHEN** document processing fails
- **THEN** the `updated_at` field in the failure `doc_status` record contains a Beijing time timestamp ending with `+08:00`

#### Scenario: Doc status timestamp method
- **WHEN** `_current_doc_status_timestamp()` is called
- **THEN** it returns a Beijing time timestamp (not UTC) with `+08:00` suffix

### Requirement: Multimodal processor uses Beijing time for status timestamps
The multimodal processor (`multimodal_processor.py`) SHALL use Beijing time for `updated_at` fields in `doc_status` records.

#### Scenario: Multimodal processing completion timestamp
- **WHEN** multimodal processing completes for a document
- **THEN** the `updated_at` field contains a Beijing time timestamp ending with `+08:00`

### Requirement: Chunk processor uses Beijing time for status timestamps
The chunk processor (`chunk_processor.py`) SHALL use Beijing time for `updated_at` fields in `doc_status` records.

#### Scenario: Chunk processing completion timestamp
- **WHEN** chunk processing completes for a document
- **THEN** the `updated_at` field contains a Beijing time timestamp ending with `+08:00`
