# Code Quality Baseline

代码质量基线规范 — 定义冗余消除、命名规范、异常处理、注释标准和 AI 调试友好度的可验证要求。

## ADDED Requirements

### Requirement: Dead code elimination

The system SHALL remove all unused imports, unreferenced functions, unreferenced variables, and commented-out legacy code across the entire backend codebase.

#### Scenario: No unused imports

- **WHEN** a static analysis tool (e.g., `ruff` or `autoflake`) scans the backend codebase
- **THEN** zero unused import violations SHALL be reported

#### Scenario: No dead functions

- **WHEN** a static analysis tool (e.g., `vulture`) scans for unreferenced functions
- **THEN** zero dead functions SHALL be reported (excluding intentionally exported package APIs)

### Requirement: Common utility extraction

The system SHALL extract duplicated logic patterns into shared utility functions. Patterns to extract include:
- Error response JSON construction
- Pagination parameter parsing
- SSE event formatting
- Background task scheduling

#### Scenario: Duplicate error response elimination

- **WHEN** any module needs to construct a standard error JSON response
- **THEN** it SHALL use the shared utility function instead of inlining the JSON construction

### Requirement: Naming convention consistency

The system SHALL apply consistent naming conventions across all backend modules:
- Functions: `snake_case`, verb-led
- Classes: `PascalCase`
- Variables: `snake_case`, noun-based
- Constants: `UPPER_SNAKE_CASE`
- Private members: `_` prefix

#### Scenario: Naming convention compliance

- **WHEN** any new or modified function, class, or variable is defined
- **THEN** its name SHALL follow the specified convention

### Requirement: Public function documentation

The system SHALL document all public functions and classes with docstrings that include:
- A one-line summary of purpose
- `Args:` section listing parameter names, types, and descriptions
- `Returns:` section describing return value and type
- `Raises:` section listing exceptions that may be raised

#### Scenario: Missing docstring

- **WHEN** a public function or class is defined without a docstring
- **THEN** a docstring SHALL be added before the refactoring is considered complete

### Requirement: Unified exception handling

The system SHALL define business exception classes in `raganything/exceptions.py` and map them to HTTP responses at the Router layer.

#### Scenario: Business exception handling

- **WHEN** a business logic error occurs (e.g., knowledge base not found, document parse failure)
- **THEN** the code SHALL raise a typed business exception rather than directly calling `raise HTTPException`

### Requirement: AI-debugging-friendly code structure

The system SHALL organize code such that:
- Individual functions SHALL be ≤ 80 lines (recommendation; hard limit 120 lines)
- Maximum nesting depth SHALL NOT exceed 3 levels
- Complex conditional chains SHALL be extracted into named helper functions

#### Scenario: Function length check

- **WHEN** any function exceeds 120 lines
- **THEN** it SHALL be split into smaller functions with clear single responsibilities

#### Scenario: Nesting depth check

- **WHEN** any code block contains more than 3 levels of nesting (if/for/while/try)
- **THEN** the inner logic SHALL be extracted into a named helper function

### Requirement: Stale comment and temporary code removal

The system SHALL remove all:
- Commented-out old code blocks
- `# TODO` comments that reference completed tasks
- `# FIXME` markers for already-fixed issues
- Temporary debugging `print()` or `logger.debug()` calls
- `# test` or `# debug` comment markers

#### Scenario: Stale debugging artifacts

- **WHEN** searching the codebase for `print(` calls used as temporary debug output
- **THEN** zero such calls SHALL remain in production code (logging via loguru is acceptable)

### Requirement: Regression test coverage

The system SHALL maintain 100% pass rate on all existing pytest tests after refactoring.

#### Scenario: Full test suite pass

- **WHEN** `pytest` is executed against the refactored codebase
- **THEN** all tests SHALL pass with the same results as before the refactoring
