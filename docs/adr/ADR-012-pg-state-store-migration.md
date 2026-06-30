# ADR-012: Migrate Shared State from In-Memory+JSON to PostgreSQL

## Status
Proposed

## Context

RAG-Anything currently stores two pieces of mutable application state in Python module-level globals, backed by whole-file JSON persistence:

### State Store 1: `query_history` (In-Memory List + `query_history.json`)

**Location:** `raganything/services/state_service.py`, line 27 -- `query_history: list[dict] = []`

- Each record is an unstructured `dict` with 6 different schema variants depending on which code path created it (AgenticRAG success, standard RAG success, CoT fallback, etc.). Fields include `id`, `query`, `mode`, `answer`, `images`, `time`, `elapsed`, `kb`, `agent_id`, `thread_id`, `user_id`, `username`, `agent_mode`, `reasoning_trace`, `fallback`.
- Persisted to `query_history.json` via atomic tmp+replace (line 52-62 of `state_service.py`).
- `record_query()` function (line 65) caps at 1000 entries by truncating from the beginning. However, the agent router (`raganything/routers/agent.py`) bypasses `record_query()` entirely and does inline `query_history.insert(0, record)` with its own cap of **100** entries at 6 different call sites (lines ~583, ~683, ~765, ~849, ~979). This means the effective cap is 100, not 1000, and there are two divergent truncation mechanisms.
- No dedicated API endpoints exist for query_history -- only `len(shared.query_history)` is exposed as `cache_size` in `/api/monitor/status` (`admin.py` line 506). The `get_query_history()` function (line 78) supports filtering by `user_id` and `limit` but has no caller.
- On startup, `server.py` line 192 passes `query_history` to `AgentManager.ensure_default_agent()` which migrates legacy records into an agent conversation thread (one-time migration path).
- `query_history.json` is git-ignored (`.gitignore` line 85).

### State Store 2: `ConversationManager` (In-Memory Dict + `conversations.json`)

**Location:** `raganything/query/conversation.py`, lines 62-281

- Stores chat threads as `self._threads: dict[str, dict] = {}` (line 77). Each thread dict has `{id, user_id, title, created_at, updated_at, messages: [{role, content, timestamp}]}`.
- Persisted to `conversations.json` via whole-file `json.dumps()` under `asyncio.Lock` (line 76). Every mutation (create thread, add message, delete thread) acquires the lock, modifies the dict, and rewrites the entire file.
- All public methods acquire the lock: `_load` (line 83), `get_or_create_thread` (line 157), `add_message` (line 181), `delete_thread` (line 256).
- Limits enforced: max 50 threads per user (line 135-143), 10000 chars per message (line 175), 3 rounds / 2000 tokens for context injection (lines 70, 205, 210-219).
- Singleton reference stored in `state_service.py` line 30, instantiated in `server.py` lines 157-169 with env-configurable `CONVERSATIONS_FILE`, `CONVERSATION_MAX_ROUNDS`, `CONVERSATION_MAX_TOKENS`, `CONVERSATION_MAX_PER_USER`.
- Consumed by the agent query stream endpoint (`agent.py` line 347-366) which manually formats conversation history for LLM prompt injection.

### Note: AgentManager Has Its Own Parallel Conversation System

`raganything/services/agent_manager.py` maintains a separate conversation system using Pydantic `ConversationThread` models persisted as individual JSON files in `agent_conversations/{agent_id}/{thread_id}.json`. This ADR does **not** address the AgentManager conversation system -- it is a separate concern with its own persistence model and lifecycle. Consolidating AgentManager and ConversationManager is a distinct architectural decision that should be its own ADR.

### What Hurts

1. **No schema enforcement.** Query history records have 6 different shapes depending on code path. A missing field is silently `None` with no way to distinguish "not applicable" from "forgotten." Conversations have no type safety -- thread and message dicts are plain `dict` with string-key access.

2. **Disk I/O on every mutation.** `save_query_history()` is called after every single query record insertion. `ConversationManager._save_nolock()` rewrites the entire `conversations.json` file on every message append, create, and delete. With 50 threads of 100+ messages each, this is a multi-kilobyte synchronous disk write per chat message.

3. **Divergent truncation mechanisms.** `record_query()` caps at 1000, the agent router caps at 100, and the two paths operate on the same in-memory list independently. The `record_query()` function is exported but never called externally -- dead API surface.

4. **No queryability.** You cannot ask "show me all queries by user X in KB Y from the last 7 days" without loading the entire JSON file into a Python process and filtering in application code. The `get_query_history()` function exists but has no API endpoint, so this capability is inaccessible.

5. **Lock contention under concurrent chat.** The `asyncio.Lock` in ConversationManager serializes all mutations. With many concurrent users chatting, every message append waits for every other message append plus the whole-file JSON write. For the current scale this is not a production problem, but it is a structural bottleneck.

6. **Data loss risk on process crash.** Despite atomic tmp+replace for `query_history.json`, a crash between an in-memory mutation and the `save_query_history()` call loses data. The `ConversationManager` uses the same atomic write pattern under lock, but the in-memory state is the source of truth -- a crash loses all mutations since the last successful save.

7. **Horizontal scaling blocked.** A second uvicorn worker would have its own independent `query_history` list and `conversation_manager` dict. This is already documented in ADR-011 (Multi-Process Deployment Strategy), which identifies these globals as blockers to multi-process deployment.

### Existing PostgreSQL Infrastructure

The project's `docker-compose.yml` defines a `postgres:16-alpine` service (container `raganything-pg`, database `raganything`, credentials `raganything/raganything`). However, this PostgreSQL instance is **not currently used** by the application code -- the current `.env` does not set any `POSTGRES_*` or `LIGHTRAG_*_STORAGE` variables, so LightRAG defaults to JSON file storage backends. The PG instance exists in Docker but sits idle.

When PostgreSQL storage backends are enabled (via `LIGHTRAG_KV_STORAGE=PGKVStorage` etc.), LightRAG's `postgres_impl.py` creates an `asyncpg.Pool` via a process-wide `ClientManager` singleton. Pool configuration reads from `POSTGRES_MAX_CONNECTIONS` (default 50), `POSTGRES_CONNECTION_RETRIES` (default 10), and `POSTGRES_CONNECTION_RETRY_BACKOFF` (default 3.0s). Every database operation is wrapped with `tenacity` retry logic for transient failures.

### The Cross-Database Foreign Key Problem

The project uses two databases:

| Database | Engine | Purpose | User ID Type |
|----------|--------|---------|-------------|
| `auth.db` | SQLite | RBAC users, roles, permissions, audit logs, token revocations | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| `raganything` (PG) | PostgreSQL 16 | LightRAG vector/kv/graph storage (when enabled) | N/A |

Both `query_history` records and `conversations` threads reference `user_id`. If we migrate these tables to PostgreSQL, the `user_id` column will reference rows in a **different database engine** (SQLite). PostgreSQL cannot enforce foreign key constraints across database boundaries.

This is not a new problem introduced by this migration -- the current in-memory+JSON stores also have no referential integrity. But moving to PostgreSQL creates an expectation of FK constraints that we cannot satisfy without also migrating the auth system to PostgreSQL (which is out of scope for this ADR).

## Decision

**Migrate `query_history` and `conversations` to PostgreSQL tables co-located in the existing `raganything` database, under a dedicated `app` schema.**

Key design decisions:

1. **Co-locate in existing PG database, separate `app` schema.** Use `CREATE SCHEMA IF NOT EXISTS app` to namespace application tables separately from LightRAG's tables (which live in `public`). This avoids name collisions and makes ownership clear without requiring a separate PG instance or database.

2. **Use raw `asyncpg` (no ORM).** SQLAlchemy adds ~2MB of dependencies, an async engine/session lifecycle to manage, and a learning curve for contributors. The existing LightRAG codebase already uses `asyncpg` directly, establishing a project convention. These are simple CRUD tables with well-known schemas -- an ORM's unit-of-work pattern and relationship mapping provide little value over parameterized SQL.

3. **Share the LightRAG connection pool via a thin application-level accessor.** Rather than creating a second `asyncpg.Pool`, we import the pool from LightRAG's `ClientManager` (or create our own pool with the same configuration if LightRAG's pool is not available). A dedicated `raganything/services/pg_store.py` module will encapsulate all PG access, providing typed functions (`insert_query_record`, `list_query_history`, `create_thread`, `add_message`, etc.) that the rest of the application calls without touching SQL directly.

4. **Store `user_id` as INTEGER with application-level integrity.** We document that `user_id` is a soft reference to `auth.db`. The application already validates user existence at the API layer via the `get_current_user` FastAPI dependency before any write. Postgres tables will use plain `INTEGER` columns (not foreign keys) with a comment documenting the cross-database reference. A periodic reconciliation query can detect orphans.

5. **Replace `asyncio.Lock` with PostgreSQL transactions.** The lock currently serializes all mutations to the in-memory dict and JSON file. PostgreSQL's MVCC provides row-level concurrency -- multiple writers can insert/update different rows simultaneously. We use `SELECT ... FOR UPDATE` only where application-level consistency requires it (e.g., checking `max_per_user` before creating a thread).

6. **Retention via time-based pruning, not count-based cap.** Replace the hard 100/1000 entry cap with a configurable retention period (default: 90 days for query_history, indefinite for conversations). A background task or a periodic `DELETE` on insert prunes old records. This is more predictable than a sliding window cap that silently drops data.

7. **Normalize conversations into `threads` + `messages` tables.** Rather than storing messages as a JSONB blob inside a thread row, use a proper one-to-many relationship. This enables message-level queries ("find all messages containing X"), independent message pagination, and avoids JSONB update contention on the thread row.

## Options Considered

### Option A: PostgreSQL (Recommended)

**What:** Migrate both state stores to PostgreSQL tables under an `app` schema in the existing `raganything` database, using asyncpg directly.

**Schema:**

```sql
CREATE SCHEMA IF NOT EXISTS app;

-- Query history, normalized with typed columns
CREATE TABLE app.query_history (
    id          TEXT PRIMARY KEY,                          -- short UUID from application
    user_id     INTEGER,                                   -- soft ref to auth.db users.id
    username    TEXT,
    query       TEXT NOT NULL,
    answer      TEXT,
    mode        TEXT,                                      -- 'hybrid', 'mix', 'naive'
    agent_mode  TEXT,                                      -- 'react', etc.
    kb          TEXT,                                      -- knowledge base name
    agent_id    TEXT,
    thread_id   TEXT,
    elapsed     REAL,                                      -- seconds
    images      JSONB DEFAULT '[]',
    reasoning_trace JSONB,                                 -- {"steps": [...], "total_steps": N}
    fallback    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_qh_user_id   ON app.query_history(user_id);
CREATE INDEX idx_qh_kb        ON app.query_history(kb);
CREATE INDEX idx_qh_created_at ON app.query_history(created_at DESC);
CREATE INDEX idx_qh_thread_id ON app.query_history(thread_id);

-- Conversations: normalized threads + messages
CREATE TABLE app.conversation_threads (
    id          TEXT PRIMARY KEY,                          -- 'th_' + 12-char hex
    user_id     INTEGER NOT NULL,                          -- soft ref to auth.db users.id
    title       TEXT NOT NULL DEFAULT '新对话',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ct_user_id    ON app.conversation_threads(user_id);
CREATE INDEX idx_ct_updated_at ON app.conversation_threads(user_id, updated_at DESC);

CREATE TABLE app.conversation_messages (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES app.conversation_threads(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cm_thread_id   ON app.conversation_messages(thread_id);
CREATE INDEX idx_cm_created_at  ON app.conversation_messages(thread_id, created_at);
```

**Trade-offs:**

| Gain | Give Up |
|------|---------|
| Typed schema enforced by the database | JSON files were trivially inspectable with any text editor |
| Row-level concurrency (no global lock) | Application-level lock was simple to reason about |
| SQL queries for filtering, aggregation, pagination | Loading a JSON file in Python was a one-liner |
| Data survives process restart (PG is durable) | JSON file was self-contained; PG requires the Docker service to be running |
| Time-based retention instead of arbitrary cap | The 100/1000 cap was aggressive but kept storage predictable |
| Multi-process deployment becomes possible | Single-process JSON was simpler to deploy and debug in development |
| Backups via `pg_dump` | Backups via `cp query_history.json` |

### Option B: Consolidate into SQLite (auth.db)

**What:** Add `query_history` and `conversation_threads`/`conversation_messages` tables to the existing `auth.db` SQLite database.

**Trade-offs:**

| Gain | Give Up |
|------|---------|
| No cross-database FK problem -- real `REFERENCES users(id)` | Single-writer concurrency model (SQLite serializes all writes) |
| No new infrastructure -- auth.db already exists | SQLite has weaker type enforcement (no native JSONB, TIMESTAMPTZ) |
| Simpler connection management (already using aiosqlite) | `aiosqlite` has no connection pool -- every operation opens a new connection |
| `auth.db` is already in the backup path | Mixing auth data with operational data in one file blurs boundaries |
| Zero additional Docker dependencies for dev | SQLite file size grows with message content, could reach hundreds of MB |

**Why not recommended:** The project already has PostgreSQL running (and will increasingly depend on it as LightRAG storage backends move to PG). Consolidating into SQLite creates a future migration burden -- when auth eventually moves to PG, these tables would need to move too. The single-writer limitation of SQLite becomes a bottleneck for chat messages under concurrent load, and the lack of a connection pool means every message insert opens and closes a new SQLite connection.

### Option C: Keep JSON + Harden

**What:** Fix the identified issues without changing the storage backend: add Pydantic validation to query_history records, unify the truncation mechanism, add dedicated API endpoints, implement a debounced/batched save, add a backup rotation scheme.

**Trade-offs:**

| Gain | Give Up |
|------|---------|
| Zero infrastructure changes | Schema remains unenforced at rest |
| Fastest to implement (hours, not days) | No queryability -- still need to load entire JSON to filter |
| Lowest risk (no data migration) | Multi-process scaling remains blocked (ADR-011 constraint) |
| JSON files are debuggable and portable | Whole-file rewrites remain a structural bottleneck |

**Why not recommended alone:** This option treats symptoms, not the structural problem. The JSON file pattern has served well during early development, but the project is moving toward multi-process deployment (ADR-011), PostgreSQL-backed LightRAG storage, and higher concurrency. Deferring the migration only increases the data volume to migrate later. Option C can be implemented as a **stopgap** while Option A is in progress, but should not be the final state.

## Consequences

### What Becomes Easier

1. **Querying.** "Show all queries by user 5 in KB 'manufacturing' from June 2025" becomes a single SQL query instead of loading an entire JSON file and filtering in Python. The admin dashboard can expose rich query history search without building an in-memory index.

2. **Multi-process deployment.** With state in PostgreSQL, multiple uvicorn workers can share the same data through the database. This unblocks the horizontal scaling path discussed in ADR-011.

3. **Data integrity.** `CHECK` constraints enforce valid message roles. `NOT NULL` prevents missing required fields. `ON DELETE CASCADE` ensures deleting a thread removes its messages. `JSONB` with application-level validation gives us the flexibility of semi-structured data with database-level storage efficiency.

4. **Retention management.** Time-based pruning (`DELETE FROM app.query_history WHERE created_at < NOW() - INTERVAL '90 days'`) is predictable and auditable, unlike the current sliding-window cap that silently drops the oldest entries.

5. **Backup and restore.** `pg_dump --schema=app` gives a consistent, point-in-time snapshot of application state. The current JSON files require coordinating file copies with the running process to avoid partial writes.

6. **Observability.** Slow queries are visible in `pg_stat_statements`. Table sizes are monitorable. Connection pool metrics from asyncpg give insight into database load.

### What Becomes Harder

1. **Development setup.** Developers who currently run without Docker must either start the PostgreSQL container or use a local PG instance. Mitigation: provide a `docker-compose.dev.yml` with just the PG service, and document a fallback using SQLite for development-only mode (with a compatibility layer in `pg_store.py`).

2. **Debugging state.** You can no longer `cat query_history.json | jq` to inspect query records. Mitigation: provide a CLI script (`scripts/pg_inspect.py`) that runs common diagnostic queries, and ensure structured logging includes enough context.

3. **Schema changes require migrations.** Adding a column to `query_history` now requires a SQL migration script rather than just appending a key to a dict. Mitigation: establish a `migrations/` directory with numbered SQL files, and a migration runner that applies them idempotently on startup (similar to how `auth.py` handles `ALTER TABLE ADD COLUMN IF NOT EXISTS`).

4. **Startup ordering.** The application must wait for PostgreSQL to be healthy before creating tables. Currently `server.py` loads JSON files independently of any external service. Mitigation: add a health-check loop at startup (already partially implemented for LightRAG's pool init with retry logic).

5. **Connection pool management.** An `asyncpg.Pool` must be created, monitored, and gracefully closed. Pool exhaustion is a new failure mode. Mitigation: configure `POSTGRES_MAX_CONNECTIONS` appropriately, monitor pool utilization, and set query timeouts.

6. **Testing.** Tests that currently exercise the in-memory ConversationManager need either a running PG instance or a test double. Mitigation: the `pg_store.py` module should expose an interface that can be replaced with an in-memory SQLite backend for unit tests, or tests can use a test PG database with schema creation in fixtures.

## Risks / Mitigations

### Risk 1: Cross-Database Referential Integrity (HIGH)

**What:** `auth.db` (SQLite) holds users. PG holds conversations and query history referencing those users. A user deleted from `auth.db` leaves orphan records in PG.

**Mitigation:**
- The application already validates user existence at the API boundary via `get_current_user` before any write to conversations or query history.
- When a user is deleted via the admin API, the deletion handler must explicitly clean up PG records (add a `DELETE FROM app.query_history WHERE user_id = ?` and `DELETE FROM app.conversation_threads WHERE user_id = ?` call in the user deletion path).
- Document in the `user_id` column comment: `-- Soft reference to auth.db users.id; clean up on user deletion.`
- Add a `cleanup_orphans()` maintenance function that can be run periodically or on-demand.

### Risk 2: Data Loss During Migration (HIGH)

**What:** Running the migration could fail partway through, losing data from either the JSON source or the PG target.

**Mitigation:**
- **Non-destructive migration.** The migration script never deletes or modifies the original JSON files. It reads them, transforms records, and inserts into PG. The JSON files remain as backup until the migration is verified.
- **Dry-run mode.** The migration script supports `--dry-run` that validates records, reports counts, and identifies schema mismatches without writing to PG.
- **Idempotent inserts.** Use `INSERT ... ON CONFLICT (id) DO NOTHING` so the migration can be re-run safely.
- **Validation pass.** After migration, compare `COUNT(*)` in PG against `len()` of the in-memory list/dict to verify completeness.
- **Rollback strategy.** If migration fails, the application continues using the JSON files exactly as before. Only after verification do we switch the application to read from PG.

### Risk 3: Pool Exhaustion Under Load (MEDIUM)

**What:** The shared asyncpg pool could be exhausted by LightRAG operations, starving application queries (or vice versa).

**Mitigation:**
- Create a **separate pool** for application tables with its own `min_size`/`max_size` configuration (default: 5-10 connections for app tables vs. 50 for LightRAG). This provides bulkhead isolation.
- Configure `command_timeout` (default: 30s) on the application pool to prevent hung queries from holding connections indefinitely.
- Expose pool metrics (`pool.get_size()`, `pool.get_idle()`) on the admin monitor endpoint.
- The application's PG operations are simple single-row CRUD -- they complete in microseconds and will not hold connections.

### Risk 4: Schema Drift Between JSON and PG During Transition (MEDIUM)

**What:** During development of the PG migration, code changes could add new fields to JSON records that the PG migration script does not account for.

**Mitigation:**
- Keep the JSON persistence code functional during the transition period. Write to both PG and JSON (dual-write) initially, with PG as the primary read source.
- Add a reconciliation endpoint (`/api/admin/reconcile-state`) that compares PG and JSON record counts and reports discrepancies.
- Once PG is verified stable (e.g., after one release cycle), remove the JSON persistence code.

### Risk 5: PostgreSQL Unavailability Blocks Application Startup (MEDIUM)

**What:** If the PG container is down or unreachable, the application currently starts fine (JSON files are local). After migration, startup would fail or block on PG health check.

**Mitigation:**
- The startup health-check loop should have a configurable timeout (default: 30s) with clear error messaging: "PostgreSQL not reachable at postgres:5432 after 30s. Is the Docker service running?"
- Implement a **degraded mode** where the application starts without PG connectivity and serves read-only endpoints (auth, static files) while logging warnings. Conversation and query features return 503 until PG is available.
- In development, provide a `--dev-sqlite` flag that uses a local SQLite file as the state store backend, allowing development without Docker.

## Implementation Phases

This migration should be implemented in phases to reduce risk:

### Phase 1: Schema and Store Module (No Behavior Change)
- Create `raganything/services/pg_store.py` with the asyncpg pool management and typed accessor functions.
- Write the SQL migration script (`scripts/migrate_to_pg_state.py`) with dry-run support.
- Add the `app` schema DDL as an idempotent startup migration.
- No application code changes yet -- just infrastructure.

### Phase 2: Dual-Write, JSON Primary
- Add PG writes alongside existing JSON writes in `record_query()` and `ConversationManager` mutations.
- Application still reads from JSON.
- Run migration to backfill existing data.
- Monitor for write errors for one release cycle.

### Phase 3: Switch Reads to PG
- Application reads from PG, writes to both PG and JSON.
- Add PG query endpoints to the admin API.
- JSON files kept as cold backup.

### Phase 4: Remove JSON Persistence
- Remove JSON file I/O.
- Remove `asyncio.Lock` from ConversationManager (replace with PG transaction boundaries).
- Remove `query_history` global list and `conversation_manager` singleton.
- Archive JSON files as migration artifacts.

## References
- ADR-011: Multi-Process Deployment Strategy (identifies in-memory globals as scaling blockers)
- `raganything/services/state_service.py` -- current query_history implementation
- `raganything/query/conversation.py` -- current ConversationManager implementation
- `raganything/services/auth.py` -- SQLite RBAC schema and user management
- `docker-compose.yml` -- PostgreSQL 16 service definition
- LightRAG `postgres_impl.py` (`ClientManager`, `PostgreSQLDB`, asyncpg pool patterns)
