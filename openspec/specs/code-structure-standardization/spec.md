# Code Structure Standardization

后端模块标准化结构规范 — 定义 Router 分层、模块拆分、依赖注入的统一标准。

## ADDED Requirements

### Requirement: Router-based API organization

The system SHALL organize all API routes into 5 dedicated Router modules based on API path prefix, replacing the monolithic `server.py`.

- `routers/auth.py` SHALL handle all `/api/auth/*` and `/api/admin/users/*` endpoints
- `routers/knowledge.py` SHALL handle all `/api/upload/*`, `/api/knowledge/*`, `/api/kb/*`, and `/api/files/*` endpoints
- `routers/agent.py` SHALL handle all `/api/agents/*` endpoints
- `routers/query.py` SHALL handle all `/api/query/*` and `/api/conversations/*` endpoints
- `routers/admin.py` SHALL handle all `/api/settings`, `/api/monitor/*`, `/api/health`, `/api/workflows/*`, and `/api/manufacturing/*` endpoints

Each Router file SHALL be ≤ 400 lines.

#### Scenario: Router file line count

- **WHEN** any Router file is measured by line count
- **THEN** the line count SHALL NOT exceed 400 lines

#### Scenario: API endpoint paths unchanged

- **WHEN** any client sends a request to an existing API path (e.g., `POST /api/query`, `GET /api/agents`)
- **THEN** the endpoint SHALL accept the request with the same path, method, parameters, and response format as before the refactoring

### Requirement: Common dependency extraction

The system SHALL extract shared middleware dependencies (rate limiter, authentication, KB access verification) into a single `dependencies.py` module.

#### Scenario: Shared dependency reuse

- **WHEN** any Router module needs rate limiting or user authentication
- **THEN** it SHALL import the dependency from `raganything/dependencies.py` rather than defining it inline

### Requirement: Server main module simplification

The system SHALL reduce `server.py` to serve only as the application factory: create FastAPI app, register routers, configure CORS/middleware, and define startup/shutdown event handlers.

#### Scenario: Server file line count

- **WHEN** `server.py` is measured by line count after refactoring
- **THEN** the line count SHALL be ≤ 300 lines

### Requirement: Sub-package decomposition for large modules

The system SHALL decompose Python modules exceeding 1000 lines into sub-packages where each sub-module is ≤ 500 lines.

#### Scenario: Sub-module line count

- **WHEN** any sub-module within a refactored package is measured by line count
- **THEN** the line count SHALL NOT exceed 500 lines

#### Scenario: Backward-compatible imports

- **WHEN** any existing code imports from a refactored module (e.g., `from raganything.parser import SomeClass`)
- **THEN** the import SHALL resolve successfully through `__init__.py` re-exports

### Requirement: Manufacturing sub-package passive cleanup

The system SHALL clean up redundant code (unused imports, dead functions, stale comments) within `raganything/manufacturing/` without restructuring its existing module layout.

#### Scenario: Manufacturing imports unchanged

- **WHEN** any existing code imports from `raganything.manufacturing.*`
- **THEN** the import SHALL resolve successfully with the same API surface
