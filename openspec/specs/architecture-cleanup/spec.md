# Architecture Cleanup

## ADDED Requirements

### Requirement: Single Limiter instance for the application
There SHALL be exactly one `slowapi.Limiter` instance shared between rate-limit route decorators and the exception handler registration.

#### Scenario: Rate limit exceeded on query endpoint
- **WHEN** a user exceeds the rate limit on `/api/query`
- **THEN** the system returns HTTP 429 with a proper error response (not 500)

#### Scenario: Limiter used in route decorator and app.state
- **WHEN** the FastAPI app starts
- **THEN** `app.state.limiter` references the same instance used in `@limiter.limit()` decorators

### Requirement: get_current_user has a single canonical definition
The `get_current_user` dependency SHALL be defined only in `raganything/dependencies.py`. `routers/shared.py` SHALL re-export it rather than defining a duplicate.

#### Scenario: Auth dependency resolution
- **WHEN** any router endpoint declares `Depends(get_current_user)`
- **THEN** the dependency resolves to the single implementation in `dependencies.py`

### Requirement: Startup logic is extracted from server.py
Server startup logic (KB metadata migration, stuck doc recovery, agent manager init) SHALL be extracted to `raganything/bootstrap.py` as discrete async functions.

#### Scenario: Server startup
- **WHEN** the FastAPI application starts
- **THEN** `server.py` calls bootstrap functions from `raganything/bootstrap.py` rather than containing the implementation inline

#### Scenario: Testing startup logic
- **WHEN** a unit test needs to verify KB migration behavior
- **THEN** the test can import and call the bootstrap function directly without starting the full FastAPI server

### Requirement: Middleware is extracted from server.py
All custom middleware classes (SecurityHeadersMiddleware, RequestSizeMiddleware) SHALL be defined in `raganything/middleware.py` and imported by `server.py`.

#### Scenario: Middleware reuse
- **WHEN** a test or alternative entry point needs the same middleware
- **THEN** it imports from `raganything/middleware.py` without duplicating class definitions

### Requirement: Service layer does not depend on web framework types
Service modules SHALL NOT import from `fastapi`. WebSocket connections SHALL be stored as protocol-agnostic wrappers.

#### Scenario: Testing ws_broadcast without FastAPI
- **WHEN** `ws_broadcast()` is called in a test environment
- **THEN** it functions correctly without requiring a running FastAPI server

## REMOVED Requirements

### Requirement: Root-level backward-compatibility wrappers
**Reason**: Deprecated. `auth.py` and `agent_manager.py` at the project root are thin re-export wrappers that encourage incorrect import paths.
**Migration**: Change all imports from `import auth` to `from raganything.services import auth`, and from `import agent_manager` to `from raganything.services import agent_manager`.

### Requirement: Duplicate RequestSizeMiddleware in shared.py
**Reason**: Dead code. The middleware at `routers/shared.py:122-139` is never used; the canonical copy at `server.py:104-122` is the active one.
**Migration**: After extracting the canonical copy to `raganything/middleware.py`, both old locations are removed.
