# ADR-013: Migrate query_history and Conversations to SQLite (auth.db)

## Status
Proposed

## Supersedes
ADR-012 (Migrate Shared State from In-Memory+JSON to PostgreSQL) -- this ADR reaches a different conclusion based on additional codebase analysis that ADR-012 did not surface. See "Why Not PostgreSQL" below for a point-by-point rebuttal.

## Context

RAG-Anything currently uses three storage mechanisms for mutable application state:

| Data | Current Storage | Mechanism |
|------|----------------|-----------|
| `query_history` | In-memory `list[dict]` + `query_history.json` | `save_query_history()` via atomic tmp+replace per mutation |
| Conversations | `ConversationManager` (in-memory dict, whole-file `conversations.json`) | `asyncio.Lock` serializes all mutations + full file rewrite |
| Agent conversations | `AgentManager` per-thread JSON files (`agent_conversations/{agent_id}/{thread_id}.json`) | No locking, sync `write_text()` per mutation |

Two moves are proposed:
1. **query_history**: Append-only query log. ~1 INSERT per query. Read: admin dashboard (`GET /api/monitor/status`, currently only reports `len()`), plus a planned query history API.
2. **Conversations**: Multi-turn chat history. ~2 messages per query turn. Read: once per query start for context injection and query rewriting.

### System Constraints (Verified Against Code)

These constraints were derived by reading the actual code, not assumptions:

| Constraint | Detail | Source |
|---|---|---|
| C1. Single-process FastAPI app | One uvicorn worker. ADR-011 proposes sticky sessions as the multi-worker path, not a shared database. | `server.py:219-296` (PID-file guard) |
| C2. No Python code connects to PostgreSQL | PG is defined in `docker-compose.yml` but the application's `.env` does not set the env vars that would cause LightRAG to use PG backends. All data access is SQLite or JSON files. | Full codebase grep for `asyncpg`, `psycopg`, `SQLAlchemy` returns zero hits in application code |
| C3. `auth.db` (SQLite) is on every authenticated request's critical path | `get_current_user()` queries SQLite for: user lookup, role lookup, account lock check, token blacklist status. Every HTTP request. No caching. | `dependencies.py:32-84`, `token_blacklist.py:119-139` |
| C4. Three SQLite connection patterns exist, one problematic | `auth.py` uses `aiosqlite` (async, correct). `token_blacklist.py` and `audit.py` use sync `sqlite3` (blocks the asyncio event loop). | `token_blacklist.py:49-51`, `audit.py:44` |
| C5. `PRAGMA foreign_keys=ON` has never been set | SQLite's default is OFF. The `users.role_id REFERENCES roles(id)` column at `auth.py:119` has never been enforced. | `auth.py:62-68` (init_db only sets `journal_mode` and `busy_timeout`) |
| C6. Two independent conversation storage systems exist | `ConversationManager` (`query/conversation.py`) is initialized at startup but appears dormant. `AgentManager` (`services/agent_manager.py`) handles the active agent query path with per-thread JSON files. | `conversation.py:62-281`, `agent_manager.py:220-233` |
| C7. No migration framework exists | The "migration" pattern in `auth.py:162-175` is `try: ALTER TABLE ADD COLUMN / except: pass`. No `schema_version` table, no ordered migrations. | `auth.py:162-175` |

### What Hurts (Code-Verified)

1. **AgentManager has zero locking.** `_save_conversation()` at `agent_manager.py:126` writes to a per-thread JSON file synchronously with no lock. Two concurrent writes to the same thread from a single process are unlikely (asyncio runs one coroutine at a time), but across workers they guarantee data loss. The code is architecturally unprepared for any form of multi-worker deployment.

2. **Sync I/O in async path.** `TokenBlacklist.is_revoked()` calls `sqlite3.connect()` from within an async FastAPI dependency at `dependencies.py:61`, blocking the event loop for ~0.5-2ms per call. At 20+ requests/second with cache misses, this becomes measurable latency.

3. **Whole-file JSON rewrites on every mutation.** `ConversationManager._save_nolock()` rewrites the entire `conversations.json` on every message, create, and delete. With 50 threads of 100 messages each, that is a multi-kilobyte disk write per operation.

4. **No schema enforcement.** `query_history` records have 6 different shapes depending on which agent code path created them. A missing field is silently `None` -- no way to distinguish "not applicable" from "forgotten."

5. **No queryability.** You cannot ask "show queries by user X in KB Y from the last 7 days" without loading the entire JSON file into Python and filtering in application code. The `get_query_history()` function exists but has no API endpoint exposing its `user_id` filter.

6. **Startup single-instance guard.** `server.py` enforces single-process via PID file. This already blocks any form of horizontal scaling regardless of storage backend.

## Decision

**Migrate both `query_history` and conversations to SQLite tables in the existing `auth.db`, replacing both the in-memory+JSON stores and the `AgentManager` per-thread JSON files.**

Key design decisions:

### 1. Add tables to existing `auth.db`, not a new database file

The existing `auth.db` is already on every authenticated request's critical path (C3 above). Adding query_history writes and conversation reads to the same database adds no new dependency -- the database is already a hard requirement. A separate `conversations.db` would create a second single point of failure without isolating the blast radius (if either database fails, the application is degraded).

The counter-argument (risk of chat writes starving auth reads) is addressed by WAL mode (see "WAL Mode Configuration" below): WAL allows concurrent readers during writes, so auth reads never block behind chat writes.

### 2. Use aiosqlite (async), not sync sqlite3

All new database access uses `aiosqlite` -- the same driver already used by `auth.py`. The existing sync `sqlite3` usage in `token_blacklist.py` and `audit.py` is a pre-existing issue (C4) that should be fixed independently, not a pattern to replicate.

### 3. Store messages as a JSON text column per thread, not a normalized `messages` table

For conversations, use a single `conversation_threads` table with a `messages` TEXT column containing a JSON array of message objects:

```sql
CREATE TABLE IF NOT EXISTS conversation_threads (
    id          TEXT PRIMARY KEY,                          -- 'th_' + 12-char hex
    user_id     INTEGER NOT NULL REFERENCES users(id),
    agent_id    TEXT,                                       -- NULL for non-agent chats
    title       TEXT NOT NULL DEFAULT '新对话',
    messages    TEXT NOT NULL DEFAULT '[]',                 -- JSON array of {role, content, timestamp}
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ct_user_agent
    ON conversation_threads(user_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_ct_updated
    ON conversation_threads(user_id, updated_at DESC);
```

**Why one row per thread instead of normalized messages:**

| Factor | One Row Per Thread (JSON messages) | Normalized Messages Table |
|--------|-----------------------------------|--------------------------|
| Read pattern fit | `get_context()` reads all messages for one thread. Single-row fetch. Perfect. | Requires `SELECT ... WHERE thread_id = ? ORDER BY created_at`. Additional I/O per message row. |
| Write pattern fit | `add_message()` appends to JSON array in one row. Single UPDATE. | Requires individual INSERT per message. Same write count, more index maintenance. |
| Context window size | Max 3 rounds x 2 messages = 6 messages of ~200 tokens each. <4KB JSON. Trivial. | Same data volume, spread across rows. |
| Schema evolution | Adding a field to messages (e.g., `edited_at`) is a JSON key addition, no DDL. | Requires ALTER TABLE ADD COLUMN. |
| Migration from JSON files | Direct mapping: `threads[thread_id].messages` -> `messages` column. | Requires row-by-row unpacking of message arrays. |
| Query across threads | Not needed. The app never queries "all messages containing X." | Would enable this, but it is not a requirement. |

The normalized approach (ADR-012's recommendation) optimizes for a query pattern the application does not have, at the cost of making the common read pattern (load all messages for a thread) N+1 instead of a single row fetch.

### 4. Use real FOREIGN KEY references to `users(id)`

Unlike ADR-012's PG proposal (which cannot enforce FK across database engines), SQLite tables in `auth.db` can use real `REFERENCES users(id)` constraints. This requires enabling `PRAGMA foreign_keys=ON` (see WAL Configuration below) -- a pre-existing bug fix, not new complexity added by this change.

### 5. Replace `asyncio.Lock` with optimistic application-level consistency

The `ConversationManager` lock serializes all mutations. Since the migration target is a single process (and ADR-011 explicitly chooses sticky sessions over shared-database multi-worker), we can replace the lock with row-level consistency where needed:

- `add_message()`: simple `UPDATE ... SET messages = json_insert(messages, ...)` -- no coordination needed beyond SQLite's internal serialization.
- `get_or_create_thread()`: check `max_per_user` via `SELECT COUNT(*) WHERE user_id = ?`, then INSERT. The race window between SELECT and INSERT is acceptable: at worst, a user briefly exceeds the cap by 1 thread, which self-corrects on the next attempt.
- `delete_thread()`: simple `DELETE WHERE id = ?`.

### 6. Time-based retention for query_history (configurable), not count-based cap

Replace the hard 100/1000 entry dual-truncation mechanism with a configurable retention period (default: 90 days). A periodic cleanup on INSERT prunes old records:

```sql
DELETE FROM query_history
WHERE created_at < datetime('now', ?)
RETURNING id;
```

This is more predictable than a sliding window cap that silently drops data. The `RETURNING` clause provides auditability (log which records were pruned).

### 7. Unify ConversationManager and AgentManager conversation storage

The migration eliminates both the `ConversationManager` (in-memory dict + `conversations.json`) and the `AgentManager` per-thread JSON files. Both are replaced by the same `conversation_threads` table. The `agent_id` column distinguishes agent-scoped threads from general chat threads. This reduces the codebase from three conversation storage mechanisms (two JSON-based + one DB) to one.

### 8. No ORM, no migration framework (yet)

Continue the existing pattern: `CREATE TABLE IF NOT EXISTS` in `init_db()` for table creation, and `ALTER TABLE ADD COLUMN` wrapped in try/except for schema additions. This pattern works for the current team size (1-3 developers) and schema complexity (4-5 tables with <15 columns each). If the schema evolves to require renames, type changes, or multi-step migrations, introduce a minimal `schema_version` table at that point -- not before it is needed.

## WAL Mode Configuration (Prerequisite, Not Optional)

Before or alongside this migration, the following PRAGMAs must be set on `auth.db` connections. Some are already partially configured; others are absent and represent existing correctness or performance gaps.

| PRAGMA | Current State | Required State | Rationale |
|--------|--------------|----------------|-----------|
| `journal_mode=WAL` | Set once in `init_db()`, persistent | **Keep as-is.** Already correct. | Allows concurrent readers during writes. Critical for auth reads not blocking behind chat writes. |
| `foreign_keys=ON` | **Never set.** Default is OFF. | **Must set on every connection.** | Real FK enforcement for `user_id REFERENCES users(id)`. Without this, the FK is decorative. |
| `busy_timeout=5000` | Set once in `init_db()`, but NOT persistent -- other connections use 0. | **Must set on every connection.** | 5-second wait before "database is locked" error. Without this, write contention causes immediate failures instead of brief waits. |
| `synchronous=NORMAL` | Default (FULL). | **Set on write connections.** | In WAL mode, NORMAL is safe (WAL protects against corruption) and ~50% faster for writes. Removes one fsync per write. |
| `journal_size_limit=67108864` | Not set. | **Set once in init_db().** | Caps WAL file at 64MB. Without this, a runaway write transaction can fill the disk with WAL growth. |

These PRAGMAs should be applied via a single helper function (e.g., `_configure_connection()`) called by every function that opens an `auth.db` connection. This is a pre-existing quality gap that this migration makes more urgent, but is not caused by it.

## Schema

### query_history

```sql
CREATE TABLE IF NOT EXISTS query_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    username        TEXT,
    query           TEXT NOT NULL,
    answer          TEXT,
    mode            TEXT,              -- 'hybrid', 'mix', 'naive', 'react'
    agent_mode      TEXT,
    kb              TEXT,              -- knowledge base name(s)
    agent_id        TEXT,
    thread_id       TEXT,
    elapsed         REAL,              -- seconds
    images          TEXT DEFAULT '[]',  -- JSON array of image URLs
    reasoning_trace TEXT,              -- JSON: {"steps": [...], "total_steps": N}
    fallback        INTEGER DEFAULT 0, -- boolean
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_qh_user_time
    ON query_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qh_kb
    ON query_history(kb);
```

### conversation_threads

```sql
CREATE TABLE IF NOT EXISTS conversation_threads (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    agent_id    TEXT,                  -- NULL for general chat, agent ID for agent-scoped threads
    title       TEXT NOT NULL DEFAULT '新对话',
    messages    TEXT NOT NULL DEFAULT '[]',  -- JSON array: [{role, content, timestamp}]
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ct_user_agent
    ON conversation_threads(user_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_ct_updated
    ON conversation_threads(user_id, updated_at DESC);
```

### Indexing rationale

Only two composite indexes per table. The access patterns are:

- `query_history`: always filtered by `user_id` (optional) and ordered by `created_at DESC` with `LIMIT 50`. The `idx_qh_user_time` composite index covers both the filtered and unfiltered cases (SQLite can use a trailing subset of a composite index). The `idx_qh_kb` index is included only if KB-filtered queries are expected on the admin dashboard -- if not, omit it.
- `conversation_threads`: always filtered by `user_id` (mandatory for isolation), optionally filtered by `agent_id`. The `idx_ct_user_agent` composite index covers both. `idx_ct_updated` supports the "list my recent threads" query.

## Why Not PostgreSQL (Rebuttal to ADR-012)

ADR-012 recommended PostgreSQL for these workloads. This section explains why that recommendation is not adopted, addressing each of its arguments.

### 1. "The project already has PostgreSQL running"

**Finding: No Python code in RAG-Anything connects to PostgreSQL.** The `docker-compose.yml` defines a `postgres:16-alpine` service, but the application's `.env` is not configured to use PG backends. LightRAG defaults to JSON file storage when PG env vars are absent. The PG container runs but sits idle -- the application has zero dependency on it.

Moving state to PG would **create a new hard dependency** where none currently exists. Moving state to SQLite would add tables to a dependency that **already is hard** (C3: every authenticated request queries `auth.db`).

### 2. "The single-writer limitation of SQLite becomes a bottleneck for chat messages under concurrent load"

**Finding: At this project's scale, SQLite WAL mode has >100x capacity headroom.**

The bottleneck for this system is LLM inference latency (seconds per query), not database write throughput. At 50 concurrent users, each generating ~2 messages per 10-second query cycle, that is ~10 writes/second. SQLite in WAL mode on SSD handles ~500-1000 writes/second before serialization becomes the bottleneck.

ADR-012's concurrency concern would be valid for a system doing hundreds of writes/second per table. That is not this system, and ADR-011's own user target (20-50 concurrent) confirms this.

### 3. "Consolidating into SQLite creates a future migration burden -- when auth eventually moves to PG, these tables would need to move too"

**Finding: Auth migration to PG is not planned, not proposed in any ADR, and would require solving a problem (cross-database FK integrity) that ADR-012 itself identifies as HIGH risk.**

This is speculative complexity. The current auth system works in SQLite, uses SQLite-specific patterns (auto-increment IDs, datetime strings, JSON text columns), and has no migration path to PG. If and when auth moves to PG, the combined migration (auth + state tables) is proportionally the same effort as migrating state tables alone. There is no "burden" being deferred -- the work is the same regardless of timing.

### 4. ADR-012 did not surface critical codebase findings

ADR-012 was written without discovering:

- **Two conversation storage systems** (ConversationManager + AgentManager). Its migration plan would have left the AgentManager JSON files untouched, creating three conversation storage mechanisms instead of one.
- **`PRAGMA foreign_keys=OFF`** (C5). ADR-012's PG schema correctly notes that cross-database FKs are impossible, but fails to mention that SQLite FKs are possible if enabled -- and that they are currently disabled.
- **Sync sqlite3 blocking the event loop** (C4). ADR-012 proposes an elaborate dual-write migration strategy (4 phases) without acknowledging that the current codebase has event-loop-blocking database calls that should be fixed first.
- **auth.db is on every request's critical path** (C3). ADR-012 treats PG as "already a dependency" and SQLite as "adding a new dependency," when the reverse is true.

### 5. The reversibility calculus is inverted

ADR-012 implies PG is the forward-looking choice. In practice:

- **SQLite -> PG later**: `pgloader` handles the data migration. Code migration (aiosqlite -> asyncpg) requires rewriting ~40-75 database access functions. This is 2-3 engineering weeks. But this migration is only needed if the application outgrows SQLite's write throughput -- which, at <50 concurrent users, it will not.
- **PG -> SQLite later**: Same data migration cost in reverse, plus removing the PG dependency from application startup. More work, not less.

The more reversible choice is SQLite, because it defers the code migration cost to the future point when it is actually needed, rather than paying it now against a speculative future.

## Options Considered

### Option A: SQLite (auth.db) -- Recommended

**What:** Add `query_history` and `conversation_threads` tables to existing `auth.db`. Replace both `ConversationManager` and `AgentManager` JSON file storage with DB access. Fix PRAGMAs as prerequisite.

| Gain | Give Up |
|------|---------|
| Real FK constraints (after enabling foreign_keys) | JSON files are trivially inspectable with any text editor |
| Single-row fetch for conversation context (no N+1) | Normalized messages table would enable message-level queries (not needed) |
| WAL concurrent reads -- auth reads never block behind chat writes | SQLite single-writer means very high write throughput (>500/sec) would serialize |
| Zero new infrastructure dependency | PG's JSONB would provide indexing on JSON fields (not needed) |
| True reversibility -- SQLite file can be `pgloader`'d to PG later | PG backup ecosystem (pg_dump, PITR) is richer |
| Unifies 3 conversation storage systems into 1 | -- |
| Migration: read JSON, INSERT into SQLite, keep JSON as backup | -- |

### Option B: PostgreSQL (ADR-012's recommendation) -- Not Recommended

**What:** Create `app` schema in PG with normalized `query_history` + `conversation_threads` + `conversation_messages` tables. Use asyncpg with a dedicated connection pool.

| Gain | Give Up |
|------|---------|
| Full relational schema with normalized messages | Application now depends on PG being up (new hard dependency) |
| JSONB with indexing capabilities | FK constraints cannot reference `auth.db` users (cross-database) |
| Rich backup ecosystem (pg_dump, PITR, WAL archiving) | Migration irreversibility: 2-3 weeks of code rewrite to go back |
| Connection pooling built into asyncpg | Development setup requires Docker PG running (currently it does not) |
| Multi-process ready out of the box | PG is already the RAG pipeline's availability bottleneck; now also the chat bottleneck |

**Why not recommended:** PG is the right database for LightRAG's graph/vector workloads (large datasets, complex queries, spatial indexing). It is the wrong database for user session data that is small, append-heavy, read-by-primary-key, and benefits from being co-located with the identity system that already validates every request. Using PG for these workloads couples two previously independent failure domains: a PG outage now breaks both RAG queries AND conversation persistence. With SQLite, a PG outage breaks RAG queries but conversations and auth continue to function.

### Option C: Keep JSON + Harden -- Not Recommended

**What:** Fix the identified issues without changing storage backend. Add Pydantic validation, unify truncation, add API endpoints, debounce saves.

| Gain | Give Up |
|------|---------|
| Zero infrastructure changes | No queryability (still load entire JSON to filter) |
| Fastest to implement | No FK enforcement, no type safety at rest |
| Lowest risk | Multi-process scaling remains blocked |
| -- | Three conversation storage systems remain (ConversationManager, AgentManager, DB) |

**Why not recommended alone:** This treats symptoms without addressing structural problems. However, JSON hardening (atomic writes, try/except, debounced saves) should be implemented as a **stopgap** if the DB migration is delayed, because several of the identified bugs (no try/except around AgentManager writes, whole-file rewrites) can cause data loss today regardless of migration plans.

## Prerequisites and Implementation Order

Before either `query_history` or conversations can be migrated:

### P0: Fix PRAGMAs (1 hour)

Add `_configure_connection()` to `auth.py` that sets `foreign_keys=ON`, `busy_timeout=5000`, `synchronous=NORMAL`, `journal_mode=WAL` on every connection. Apply to `auth.py`, `token_blacklist.py`, and `audit.py`. This is a correctness fix independent of the migration.

### P0: Fix sync sqlite3 in async path (2 hours)

Replace `sqlite3` (sync) with `aiosqlite` (async) in `token_blacklist.py` and `audit.py`. Each `sqlite3.connect()` call currently blocks the asyncio event loop for 0.5-2ms on every authenticated request with a cache miss.

### P1: Add missing try/except to AgentManager._save_conversation() (30 minutes)

`agent_manager.py:126` calls `json.dumps()` and `Path.write_text()` with no error handling. An exception here propagates to the SSE response stream and breaks the user's query response. Wrap in try/except, log warning, continue. This is a production resilience fix independent of migration.

### P2: Add DDL to init_db() (1 hour)

Add `CREATE TABLE IF NOT EXISTS` for `query_history` and `conversation_threads` to `auth.py:init_db()`. This is idempotent and safe to deploy before any code uses the tables.

### P3: Implement data access layer (3-4 hours)

Create `raganything/services/conversation_store.py` and extend `raganything/services/state_service.py` with typed accessor functions backed by aiosqlite:

```python
# query_history accessors (in state_service.py or a new module)
async def insert_query_record(entry: QueryRecord) -> int: ...
async def list_query_history(limit: int = 50, user_id: int = None,
                             kb: str = None) -> list[QueryRecord]: ...
async def prune_old_queries(retention_days: int = 90) -> int: ...

# conversation accessors (new module: conversation_store.py)
async def create_thread(user_id: int, agent_id: str = None,
                        title: str = "新对话") -> ThreadRecord: ...
async def get_thread(thread_id: str) -> ThreadRecord | None: ...
async def add_message(thread_id: str, role: str, content: str) -> None: ...
async def get_context(thread_id: str, max_rounds: int = 3,
                      max_tokens: int = 2000) -> ConversationContext: ...
async def delete_thread(thread_id: str, user_id: int) -> bool: ...
async def list_user_threads(user_id: int, agent_id: str = None,
                            limit: int = 50) -> list[ThreadSummary]: ...
```

### P4: Migrate existing data (1-2 hours)

One-shot migration script (`scripts/migrate_state_to_sqlite.py`):
- Read `query_history.json` -> INSERT each record into `query_history` table
- Read `conversations.json` -> INSERT each thread into `conversation_threads` table
- Walk `agent_conversations/` directory -> INSERT each thread into `conversation_threads` table with `agent_id` set
- Dry-run mode prints counts and validation errors without writing
- Idempotent: `INSERT OR IGNORE` on primary key conflicts

### P5: Switch application to use DB accessors (2-3 hours)

- Replace `record_query()` calls with `await insert_query_record()`
- Replace `ConversationManager` usage with `conversation_store` accessors
- Replace `AgentManager._save_conversation()` with `conversation_store.add_message()`
- Keep JSON persistence code as fallback during transition (one release cycle)
- Remove after verification

### P6: Remove JSON persistence and dead code (1 hour)

- Remove `ConversationManager` class and `conversations.json` references
- Remove `AgentManager` per-thread JSON file I/O
- Remove `query_history.json` I/O
- Remove `asyncio.Lock` from `ConversationManager`
- Remove `query_history` global list
- Keep JSON files as migration artifacts (do not delete user data)

## Consequences

### What Becomes Easier

1. **Queryability.** "Show all queries by user 5 in KB 'manufacturing' from the last 7 days" becomes a SQL query with an index. The admin dashboard can expose query history search without loading an entire JSON file.

2. **Data integrity.** Real FOREIGN KEY constraints (once enabled). Type checking via column types. NOT NULL enforcement. No more silently-missing fields across 6 different record shapes.

3. **Multi-worker readiness.** With state in SQLite (WAL mode), multiple workers can share `auth.db`. WAL allows concurrent readers during writes. The single-writer limitation is a non-issue at this scale. This unblocks ADR-011's sticky-session strategy without requiring PG for session data.

4. **Reduced code surface.** Three conversation storage systems collapse to one. The `asyncio.Lock` and whole-file rewrite patterns disappear. `ConversationManager` class (~220 lines) is removed.

5. **Backup simplicity.** `auth.db` is a single file. Backup is `cp auth.db backups/auth-$(date).db`. No `pg_dump`, no WAL archiving, no point-in-time recovery configuration needed.

6. **Development setup unchanged.** Developers who run without Docker (using local Python) continue to work with SQLite. No PG dependency is added to the development workflow.

### What Becomes Harder

1. **Debugging state.** You can no longer `cat query_history.json | jq` to inspect records. Mitigation: add a `scripts/db_inspect.py` CLI that runs common diagnostic queries with formatted output.

2. **Schema changes require migrations.** Adding a column now requires `ALTER TABLE ADD COLUMN` rather than appending a key to a dict. Mitigation: continue the existing `init_db()` idempotent pattern. If it becomes insufficient (column renames, type changes), introduce a minimal `schema_version` table at that point.

3. **WAL file management.** WAL mode creates `auth.db-wal` and `auth.db-shm` files. These must be included in the Docker bind mount and in backups. An attacker with filesystem access can reconstruct recent writes from the WAL file. Mitigation: set `journal_size_limit` to cap WAL growth. WAL files are temporary -- checkpointing merges them into the main database.

### Failure Mode Comparison

| Failure | Current (JSON + in-memory) | Proposed (SQLite auth.db) | ADR-012 (PG) |
|---------|---------------------------|--------------------------|--------------|
| PG down | RAG queries fail. Auth works. Chat works. Query history works. | Same as current. | **RAG queries fail. Auth works. Chat fails. Query history fails.** |
| SQLite corrupted | Auth fails (all requests 401). Chat works. RAG works. | Auth fails. **Chat fails. Query history lost.** | Auth fails. Chat works (in PG). RAG works. |
| Disk full | JSON writes fail silently. Messages lost on restart. | SQLite writes fail with error. Application can handle and retry. | PG writes fail. SQLite writes fail. Application may crash. |
| App crash (SIGKILL) | In-memory state lost since last JSON save. | SQLite WAL auto-recovery on next open. Last committed transaction preserved. | PG transaction rollback. Last committed transaction preserved. |

**Key insight: The proposed approach does not increase the blast radius of any single failure mode.** A PG outage remains the same (RAG broken, everything else works). A SQLite outage becomes worse (conversations lost alongside auth), but this is the cost of co-location and is offset by the fact that SQLite corruption is extremely rare with WAL mode and proper PRAGMAs, while PG unavailability is a daily operational reality in Docker-based deployments (container restarts, volume issues, OOM kills).

### What the Team is Explicitly Accepting

1. **SQLite single-writer at high concurrency.** If the application grows beyond ~200 concurrent chatters generating ~40 writes/second, SQLite write serialization becomes a bottleneck. This threshold is far above ADR-011's 20-50 user target. If reached, migrating to PG at that point is a known, bounded cost (2-3 weeks).

2. **No migration framework (yet).** The `try/except ALTER TABLE` pattern is simple but fragile. It works for nullable column additions, not for renames or type changes. The team accepts this risk given the current schema simplicity and will introduce a `schema_version` table when the first complex migration is needed.

3. **auth.db becomes more critical.** Conversations and query history will share a file with auth data. If `auth.db` is corrupted, the impact is larger. Mitigation: regular backups (single file copy), WAL mode for crash recovery, and potentially a separate `conversations.db` if write volumes become a concern.

4. **Reversibility cost is deferred.** Migrating from SQLite to PG later requires 2-3 weeks of code rewrite (aiosqlite -> asyncpg across ~40-75 functions). The team accepts this cost being deferred to the point when it is actually needed, rather than paying it now.

## References

- ADR-011: Multi-Process Deployment Strategy (identifies in-memory globals as scaling blockers, recommends sticky sessions over shared-database multi-worker)
- ADR-012: Migrate Shared State from In-Memory+JSON to PostgreSQL (superseded by this ADR)
- `raganything/services/state_service.py` -- current query_history implementation
- `raganything/query/conversation.py` -- current ConversationManager implementation
- `raganything/services/agent_manager.py` -- current AgentManager conversation storage (per-thread JSON files)
- `raganything/services/auth.py` -- SQLite RBAC schema, init_db(), migration pattern
- `raganything/services/token_blacklist.py` -- sync sqlite3 usage blocking event loop
- `raganything/services/audit.py` -- sync sqlite3 audit logger
- `raganything/dependencies.py` -- get_current_user() critical path hitting auth.db on every request
- `docker-compose.yml` -- PostgreSQL service definition (unused by application code)
