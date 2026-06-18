## ADDED Requirements

### Requirement: Maximum file size limit
No Python source file in the `raganything/` package SHALL exceed 500 lines of code (excluding blank lines and docstrings). Files exceeding this limit SHALL be split by responsibility.

#### Scenario: Existing file exceeds 500 lines
- **WHEN** `modalprocessors.py` (1672 lines) is split
- **THEN** each resulting file SHALL contain ≤500 lines, with one class or closely related group of functions per file

#### Scenario: New file approaches limit
- **WHEN** a new or modified file reaches 450 lines during development
- **THEN** developers SHALL evaluate whether the file should be split before exceeding 500 lines

### Requirement: Maximum function length
No function or method SHALL exceed 100 lines. Functions exceeding this limit SHALL be decomposed into smaller private helper functions.

#### Scenario: Long method decomposition
- **WHEN** a method like `DocProcessorMixin._process_single_document()` exceeds 100 lines
- **THEN** it SHALL be refactored into a sequence of single-responsibility private methods: `_validate_document()`, `_extract_content()`, `_insert_to_lightrag()`, `_update_status()`

### Requirement: Maximum class length
No class SHALL exceed 300 lines. Classes exceeding this limit SHALL be split into a base class with focused subclasses or delegate to collaborator classes.

#### Scenario: Large class splitting
- **WHEN** a class like `RAGAnything` (716 lines via mixins) exceeds 300 lines in its own file
- **THEN** new functionality SHALL be added via focused Mixin classes rather than extending the base class directly

### Requirement: Single responsibility per module
Each `.py` file SHALL have exactly one primary responsibility. A file named `image_processor.py` SHALL contain only image-related processing logic, not table or equation processing.

#### Scenario: Modal processor organization
- **WHEN** the `modalprocessors/` sub-package is organized
- **THEN** `image.py` SHALL contain only `ImageModalProcessor`, `table.py` only `TableModalProcessor`, `equation.py` only `EquationModalProcessor`

### Requirement: Stale backup file cleanup
No `.bak` files or refactoring artifacts SHALL remain in the repository. All deleted modules (`parser.py`, `processor.py`, `query.py`) SHALL have their `.bak` backups removed.

#### Scenario: Repository cleanup
- **WHEN** the code decomposition is complete
- **THEN** `git status` SHALL show zero `.bak` files in the `raganything/` directory
