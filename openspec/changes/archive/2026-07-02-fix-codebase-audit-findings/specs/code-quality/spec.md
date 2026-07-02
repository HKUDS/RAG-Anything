# Code Quality

## ADDED Requirements

### Requirement: Dead code is removed
The codebase SHALL NOT contain duplicate function definitions, dead code, or unreachable code paths.

#### Scenario: Prompt injection validation
- **WHEN** `validate_query_input` is called from any endpoint
- **THEN** the canonical implementation in `raganything/utils/security.py` is used (not the dead copy in `server.py`)

#### Scenario: Degraded hint constant
- **WHEN** a degraded context hint is needed
- **THEN** a single canonical constant is referenced (not one of 3+ duplicate definitions)

### Requirement: Runtime bugs are fixed
The codebase SHALL NOT contain code paths that raise `NameError` or `TypeError` at runtime under any configuration.

#### Scenario: Rerank enabled
- **WHEN** `RERANK_ENABLED=true` and the rerank code path is triggered
- **THEN** `rerank_chunks` is properly imported and callable (no `NameError`)

#### Scenario: Agentic chunking fallback
- **WHEN** the agentic chunking fallback `llm_func` is called
- **THEN** the function is correctly async and callable with `await` (no `TypeError`)

#### Scenario: llm_func with default history_messages
- **WHEN** `llm_func` is called without explicit `history_messages` argument
- **THEN** the default value is `None` and initialized to `[]` inside the function body (no mutable default argument)

### Requirement: Exception handling does not silently swallow errors
All `except Exception: pass` blocks SHALL at minimum log a warning with exception context, unless the code is in a destructor/shutdown path where logging may not be available.

#### Scenario: Non-critical operation failure in query pipeline
- **WHEN** a non-critical operation in the query pipeline raises an exception
- **THEN** a warning is logged with the exception message and traceback

#### Scenario: Shutdown finalization failure
- **WHEN** `finalize_storages()` fails during interpreter shutdown
- **THEN** the error is silently ignored (destructor context, logging may not be available)

### Requirement: Duplicate code is consolidated
Constants, middleware, and utility functions that appear in multiple files SHALL have a single canonical definition.

#### Scenario: PROMPT_INJECTION_PATTERNS
- **WHEN** prompt injection patterns are needed
- **THEN** they are imported from `raganything/utils/security.py` (not duplicated in `server.py`)

#### Scenario: DEGRADED_HINT
- **WHEN** a degraded context hint is needed
- **THEN** exactly one constant is defined and imported (not three slightly-different copies)

### Requirement: Docstrings and comments are not duplicated
No file SHALL contain duplicate docstrings, duplicate import statements, or repeated identical comment blocks.

#### Scenario: delete_kb function
- **WHEN** viewing `kb_service.py` `delete_kb()` function
- **THEN** the docstring appears exactly once

#### Scenario: server.py startup event
- **WHEN** viewing `server.py` `startup()` function
- **THEN** the ConversationManager initialization comment appears exactly once (not twice)

### Requirement: Chunking strategy swap uses a context manager
The temporary chunking strategy swap pattern SHALL be extracted to an `@asynccontextmanager` to eliminate triplicated code across upload endpoints.

#### Scenario: Upload with custom chunking strategy
- **WHEN** a file is uploaded with a non-default chunking strategy
- **THEN** the strategy is temporarily applied and restored in a finally block via a single context manager call
