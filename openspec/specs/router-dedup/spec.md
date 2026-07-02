## ADDED Requirements

### Requirement: Single source of truth for shared helpers

All helper functions shared between `server.py` and Router modules SHALL be defined exclusively in `raganything/routers/shared.py`. `server.py` SHALL import these functions from the `shared` module rather than defining local copies.

#### Scenario: No duplicate function definitions

- **WHEN** comparing `server.py` and `shared.py` after refactoring
- **THEN** no function with identical signature and body exists in both files
- **THEN** `server.py` references all shared helpers via `from raganything.routers import shared` or direct import aliases

#### Scenario: Server lifecycle functions still work

- **WHEN** `server.py` lifecycle handlers (`startup`, `shutdown`) call helper functions like `get_kb()`, `load_kb_meta()`, `create_rag()`
- **THEN** those calls succeed using the imported shared functions
- **THEN** all state mutations (kb_instances, processing_tasks, etc.) are visible to Router modules

#### Scenario: Existing tests pass without modification

- **WHEN** running `pytest tests/ -q`
- **THEN** the test count is >= 356 passed
- **THEN** no new test failures are introduced

### Requirement: server.py reduced to bootstrapping only

`server.py` SHALL contain only app bootstrapping code: imports, FastAPI app creation, middleware registration, Router registration, lifecycle event handlers, and the `if __name__` entrypoint. All business logic helper functions SHALL live in `shared.py`.

#### Scenario: server.py line count below 350

- **WHEN** counting non-blank, non-comment lines in `server.py`
- **THEN** the line count is below 350 (down from 803)
