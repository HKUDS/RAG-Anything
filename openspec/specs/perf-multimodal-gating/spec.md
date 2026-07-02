# perf-multimodal-gating

Documented per-scenario guidance for selectively disabling VLM-heavy multimodal processing to accelerate document ingestion.

## ADDED Requirements

### Requirement: Per-mode multimodal processing toggles

The system SHALL support independent enable/disable toggles for each multimodal processing type: `ENABLE_IMAGE_PROCESSING`, `ENABLE_TABLE_PROCESSING`, `ENABLE_EQUATION_PROCESSING`.

#### Scenario: Image processing disabled for text-heavy documents
- **WHEN** `ENABLE_IMAGE_PROCESSING=false` is set in `.env`
- **THEN** the document processing pipeline SHALL skip VLM image description generation
- **AND** images SHALL still be extracted and stored, but without AI-generated captions
- **AND** processing time per image SHALL be reduced by the VLM call duration (~10-30s)

#### Scenario: All multimodal processing enabled (default)
- **WHEN** all `ENABLE_*_PROCESSING` are set to `true` (or not set)
- **THEN** all multimodal content SHALL be processed with VLM description generation

### Requirement: Configuration guidance in .env

The `.env` file SHALL include comments documenting which multimodal toggles to disable for common document types.

#### Scenario: User reads .env for guidance
- **WHEN** a user opens `.env`
- **THEN** they SHALL see guidance comments recommending:
  - Disable `ENABLE_IMAGE_PROCESSING` for image-sparse documents
  - Disable `ENABLE_EQUATION_PROCESSING` for non-academic documents
  - Keep `ENABLE_TABLE_PROCESSING` for data-heavy reports
