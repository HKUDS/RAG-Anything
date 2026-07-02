## ADDED Requirements

### Requirement: Single source of truth for KB instances
All knowledge base (KB) instance management SHALL be centralized in `raganything/services/kb_service.py`. No other module SHALL maintain its own KB instance registry.

#### Scenario: Creating a KB instance
- **WHEN** the system creates a new RAGAnything KB instance
- **THEN** it SHALL register it through `kb_service.create_kb()` which stores it in the centralized registry

#### Scenario: Retrieving a KB instance
- **WHEN** any router or service needs a KB instance
- **THEN** it SHALL retrieve it via `kb_service.get_kb(kb_name)` from the centralized registry

#### Scenario: Deleting a KB instance
- **WHEN** a KB is deleted
- **THEN** `kb_service.delete_kb()` SHALL clean up all associated resources (LightRAG instance, index, processing tasks) atomically

### Requirement: Centralized WebSocket connection management
All WebSocket connection tracking and broadcasting SHALL be centralized in `raganything/services/ws_service.py`.

#### Scenario: Broadcasting progress to WebSocket clients
- **WHEN** document processing emits progress events
- **THEN** it SHALL broadcast through `ws_service.broadcast_progress()` rather than maintaining its own WebSocket connection set

#### Scenario: Client disconnection cleanup
- **WHEN** a WebSocket client disconnects
- **THEN** `ws_service` SHALL automatically remove the connection from its tracking set

### Requirement: Centralized in-memory state management
All server-level in-memory state (query history, processing task status, active sessions) SHALL be managed by `raganything/services/state_service.py` with thread-safe access patterns.

#### Scenario: Recording query history
- **WHEN** a query is executed
- **THEN** the result SHALL be recorded through `state_service.record_query()` with timestamp, user, KB context, and response metadata

#### Scenario: Tracking processing task status
- **WHEN** a document processing task changes state
- **THEN** `state_service.update_task_status()` SHALL atomically update the status and notify WebSocket clients

#### Scenario: Thread-safe access
- **WHEN** multiple concurrent requests access shared state
- **THEN** `state_service` SHALL use appropriate locking (asyncio.Lock or threading.Lock) to prevent race conditions

### Requirement: No duplicate state in server.py
`server.py` SHALL NOT define or maintain any module-level shared state variables. All state SHALL be accessed through service modules.

#### Scenario: server.py startup
- **WHEN** the FastAPI application starts
- **THEN** `server.py` SHALL import and initialize services from `raganything.services.*` rather than defining `kb_instances`, `processing_tasks`, or similar module-level dicts
