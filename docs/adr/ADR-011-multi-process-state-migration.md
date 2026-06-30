# ADR-011: Multi-Process Shared-State Migration Strategy

## Status
Proposed

## Context

RAG-Anything currently runs as a single uvicorn process with all shared state in Python module-level globals:
- `processing_tasks`: dict (upload task status, ephemeral)
- `processing_events`: list of 200 events (WebSocket push, never read back)
- `ws_clients`: list of WebSocket connections (ephemeral)
- `query_history`: list + JSON file persistence
- `ConversationManager`: dict + JSON file persistence
- `kb_instances`: dict of LightRAG library instances (mtime-based cache invalidation)
- `QueryCache`: OrderedDict TTL+LRU

The question is: which of these states need to be externalized for multi-process deployment, and to which backing store?

### Key Constraints
1. `docker-compose.yml` already provisions PostgreSQL 16 and Redis 7 Alpine containers with healthchecks. The infrastructure overhead exists regardless.
2. SQLite (`auth.db`) is already on every request's critical path for auth/roles/token blacklist.
3. CPU-heavy document processing is already offloaded to subprocess workers; the FastAPI server is primarily I/O-bound.
4. The current `_acquire_server_lock()` in `server.py` explicitly prevents multi-process startup (PID file + port check).
5. LightRAG library instances are non-serializable C-extension-backed objects (NanoVectorDB, connection pools, in-memory indexes).
6. No multi-worker load test has been performed; multi-worker is a design assumption, not a measured requirement.

## Decision

### Two-Tier Strategy: "Simplicity First, Scale When Proven"

**Tier 1 (today — single process, implement immediately):**

| State | Action | Rationale |
|-------|--------|-----------|
| `query_history` | Move to SQLite (auth.db) | ACID persistence, SQL queryability, zero new infra. Replaces fragile JSON file. |
| `ConversationManager` | Move to SQLite (auth.db) | ACID, FK-enforced message integrity, cross-process safety if workers are added later. Replaces JSON file with non-atomic save. |
| `processing_tasks` | Keep in-memory | Single process has no cross-worker visibility problem. Ephemeral state does not need persistence. |
| `processing_events` | Keep in-memory, audit necessity | Written to in 5+ places, never read by any router or service. Consider removing entirely. |
| `ws_clients` | Keep in-memory | Single process = single WS connection pool. No cross-worker broadcast needed. |
| `kb_instances` | Keep in-memory + mtime check | Non-serializable library objects. Filesystem-based invalidation already correct. |
| `QueryCache` | Keep in-memory | Single process = no cache coherence problem. Network round-trip to shared cache negates benefit. |

**Tier 2 (future — multi-worker, when load test proves need):**

| State | Action | Rationale |
|-------|--------|-----------|
| `processing_tasks` | Move to Redis Hash | Ephemeral, write-heavy (progress updates), cross-worker visibility, TTL-based cleanup. Circuit breaker with degraded mode (503 on upload). |
| `processing_events` | Move to Redis List (LTRIM 200) | Ephemeral rolling log. Only migrate if the data is actually consumed. |
| `ws_clients` | Redis PubSub backbone | Cross-worker broadcast. Each worker subscribes to Redis channel; publishes progress updates. |
| `query_history` | Already in SQLite — no further change needed | SQLite WAL mode supports multi-process concurrent readers. Single-writer limitation acceptable at <0.01 QPS. |
| `ConversationManager` | Already in SQLite — no further change needed | Same as above. |
| `kb_instances` | Keep per-process + mtime check | Cannot be shared. Mtime invalidation works correctly across processes (shared filesystem). |
| `QueryCache` | Keep per-process | Hit-rate benefit of shared cache is theoretical (saves ~1 LLM call out of hundreds). Cost is adding Redis as a query hot-path dependency. Not worth it. |

### Why Not PostgreSQL for query_history and ConversationManager?

1. **Fault domain separation**: PostgreSQL is LightRAG's internal storage. If PG goes down, RAG queries already fail. Adding conversations and query history to PG means a PG outage also kills chat history and query logging — it cascades the blast radius.
2. **Locality**: SQLite is a local file with zero network latency. At this write volume (<0.01 QPS), PG's concurrency advantage is purely theoretical.
3. **Infrastructure cost asymmetry**: SQLite is already a project dependency (auth.db). Adding `asyncpg` as an application dependency would be the project's first direct PG connection — it currently only talks to PG through LightRAG's internal classes.
4. **Reversibility**: SQLite-to-PG migration is a known path (same SQL, same schema). PG-to-SQLite is also possible. Starting with SQLite defers the PG dependency decision.

### Why Not Redis for Everything?

1. **Redis not needed for single-process**: All current state management works correctly with module-level dicts + asyncio.Lock. Adding Redis is premature.
2. **Redis as hard dependency increases fragility**: A Redis outage would require circuit breaker logic, degraded modes, and recovery procedures. For ephemeral task state, this may be acceptable. For persistent user data, it is not.
3. **Redis is the right tool for the wrong time**: If multi-worker proves necessary, Redis Hash + List + PubSub is the correct solution. But the necessity must be proven first.

### Critical Bugs Fixed as Prerequisites

Regardless of migration path, three bugs in the current codebase must be fixed (discovered during analysis):

1. **query_history list reference desync** (`agent.py` rebinds `query_history = query_history[:100]` — creates a new list; `state_service.py` still holds reference to old list. Subsequent writes go to different list objects.)
2. **Zero concurrency control** on `processing_tasks`, `query_history`, `conversation_manager` — multiple async coroutines can corrupt these structures.
3. **ConversationManager non-atomic save** (`_save_nolock` writes directly to `conversations.json` — a crash mid-write produces a truncated file; on restart, all conversation history is discarded.)

## Consequences

### What Becomes Easier
- **Data integrity**: SQLite ACID replaces JSON file "best effort" for query_history and conversations.
- **Queryability**: SQL queries for filtering query history by user, date range, KB, agent mode — currently requires loading + filtering entire list in Python.
- **Cross-process safety (future)**: SQLite WAL mode handles multi-process reads. The schema is ready for PG migration if needed.
- **Deployment simplicity**: No new infrastructure for Tier 1. The existing auth.db grows two tables.
- **Auditability**: Query history with proper timestamps and user attribution enables usage analytics that the current 1000-entry ring buffer cannot support.

### What Becomes Harder
- **Schema evolution**: Adding a field to `query_history` now requires a migration (ALTER TABLE) instead of just appending a key to a dict. Mitigation: JSONB column (PG) or TEXT column with JSON (SQLite) for extensible fields.
- **Local development**: Developers must run SQLite migrations on first setup. Mitigation: auto-migration in `init_db()` (pattern already used by auth tables).
- **Debugging**: Can't `print(query_history)` in a repl. Mitigation: add a `--debug` CLI flag that dumps tables.

### Risks
- **SQLite single-writer limitation**: If query volume grows to hundreds per second, WAL mode writer contention becomes real. Mitigation: PG migration path is documented and the schema is identical.
- **processing_events removal**: If events are consumed by a dashboard or monitoring system not visible in the current codebase, removal would break it. Mitigation: audit before removing; add deprecation warning first.

### Multi-Worker Gating Criteria
Before implementing Tier 2, the following must be true:
1. Load test shows single-worker p95 latency > 500ms at 2x peak load
2. OR, CPU profiling shows the event loop saturated (>80% utilization) during normal operation
3. AND, the measured bottleneck is the FastAPI process (not LLM API latency, not subprocess workers)

## Supersedes
None (new decision)

## References
- `raganything/services/state_service.py` — current query_history + processing_tasks management
- `raganything/services/ws_service.py` — current ws_clients + processing_events management
- `raganything/query/conversation.py` — current ConversationManager implementation
- `raganything/query_cache.py` — current QueryCache implementation
- `raganything/services/kb_service.py` — current kb_instances + mtime cache invalidation
- `raganything/resilience.py` — existing CircuitBreaker class (reusable for Redis in Tier 2)
