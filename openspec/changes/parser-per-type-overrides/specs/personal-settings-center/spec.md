## ADDED Requirements

### Requirement: Personal settings expose per-file-type parser overrides
The upload/parsing section SHALL show the global parser selector plus one row per file type (`pdf`, `office`, `image`), each offering a “follow default” first option and then only parsers whose catalog `supported_types` includes that type, with uninstalled parsers disabled. The image row SHALL be labeled to distinguish standalone image file parsing from the multimodal image toggle for images inside documents. The video row SHALL show the enable switch and state that video does not go through a parser but uses frame extraction and transcription. When the options request fails, the global selector SHALL fall back to the currently effective parser plus `docling`, and each per-type selector SHALL offer only “follow default” while remaining editable.

#### Scenario: User overrides only the PDF parser
- **WHEN** a user changes only the PDF row to a supported parser and saves
- **THEN** the saved `parsers_by_type` contains only `pdf` (empty-string keys are omitted), and office/image rows remain “follow default”

#### Scenario: User clears a per-type override back to follow default
- **WHEN** a user changes the PDF row back to “follow default” and saves
- **THEN** the saved `parsers_by_type` no longer contains the `pdf` key and no empty-string values are stored

#### Scenario: Image row is labeled distinctly from the multimodal toggle
- **WHEN** a user views the upload/parsing section
- **THEN** the image row is labeled as standalone image file parsing while the multimodal section still labels its toggle as processing images inside documents

#### Scenario: Options request fails while preferences is open
- **WHEN** the options request fails and the upload/parsing section is visible
- **THEN** the global parser selector offers the currently effective parser and `docling`, every per-type selector offers only “follow default”, and the section remains editable

### Requirement: Personal settings explain video parsing behavior
The upload/parsing section SHALL display, next to the video enable switch, a hint that video files are not parsed by a document parser and instead go through frame extraction and transcription.

#### Scenario: Video row shows the explanatory hint
- **WHEN** a user views the upload/parsing section
- **THEN** the video row shows the enable switch and the hint text about frame extraction and transcription