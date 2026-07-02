# Tasks: Fix Codebase Audit Findings

## 1. Security — Authentication & Authorization (P0)

- [ ] 1.1 Add `Depends(get_current_user)` to all 15 manufacturing endpoints in `raganything/routers/manufacturing.py`
- [ ] 1.2 Add token validation to WebSocket endpoints (`/ws`, `/ws/workflow-run/{run_id}`) in `raganything/routers/admin.py`
- [ ] 1.3 Add `Depends(get_current_user)` and path validation to `/api/knowledge/files/image` in `raganything/routers/knowledge.py`
- [ ] 1.4 Add `require_permission()` to admin settings, monitor, and workflow endpoints in `raganything/routers/admin.py`
- [ ] 1.5 Fix JWT secret race condition: move SECRET_KEY generation from module import to `init_db()` with `BEGIN IMMEDIATE` transaction in `raganything/services/auth.py`
- [ ] 1.6 Fix file upload path traversal: sanitize `file.filename` with `os.path.basename()` + extension allowlist in `raganything/routers/knowledge.py` and `raganything/routers/admin.py`
- [ ] 1.7 Remove `unsafe-inline` and `unsafe-eval` from CSP in `server.py` SecurityHeadersMiddleware

## 2. Security — Prompt Injection Defense (P0)

- [ ] 2.1 Add `validate_query_input()` call to agent query stream endpoint (`raganything/routers/agent.py:280`)
- [ ] 2.2 Add `validate_query_input()` to 5 manufacturing query endpoints in `raganything/routers/manufacturing.py`
- [ ] 2.3 Add `validate_query_input()` to workflow run endpoint in `raganything/routers/admin.py`
- [ ] 2.4 Add Unicode NFKC normalization + zero-width character stripping to `validate_query_input()` in `raganything/utils/security.py`
- [ ] 2.5 Add Chinese-language injection patterns to `PROMPT_INJECTION_PATTERNS` in `raganything/utils/security.py`
- [ ] 2.6 Add document content scanning for injection payloads during ingestion in `raganything/services/kb_service.py`
- [ ] 2.7 Add `system_prompt` field validation in AgentCreateRequest/AgentUpdateRequest models in `raganything/routers/agent.py`
- [ ] 2.8 Create `raganything/prompt/protection.py` with unified prompt assembly function using XML tag delimiters
- [ ] 2.9 Harden `QUERY_SYSTEM_PROMPT` with explicit injection refusal rules in `raganything/routers/shared.py`
- [ ] 2.10 Harden ReAct and CoT system prompts with injection defense rules in `raganything/agentic_rag/engine.py`
- [ ] 2.11 Add security audit logging on injection detection in `raganything/utils/security.py`

## 3. Data Integrity (P0)

- [ ] 3.1 Convert `save_kb_meta()` to atomic write (`.tmp` + `replace`) in `raganything/services/kb_service.py`
- [ ] 3.2 Convert `save_query_history()` to atomic write with 5-second debounce in `raganything/services/state_service.py`
- [ ] 3.3 Add `asyncio.Lock` per KB name to `get_kb()` in `raganything/services/kb_service.py`
- [ ] 3.4 Remove `is_admin` from `create_user()` INSERT statement in `raganything/services/auth.py`
- [ ] 3.5 Add index on `users.role_id` in `raganything/services/auth.py` `init_db()`
- [ ] 3.6 Narrow `init_db()` migration exception handling to catch only `sqlite3.OperationalError` with "duplicate column" in `raganything/services/auth.py`
- [ ] 3.7 Consolidate role/permission definitions: `auth.py` and `migrate_to_rbac.py` must import from `permissions.py`

## 4. Architecture Cleanup (P1)

- [ ] 4.1 Create `raganything/middleware.py`: extract SecurityHeadersMiddleware, RequestSizeMiddleware from `server.py`
- [ ] 4.2 Create `raganything/bootstrap.py`: extract startup logic (KB migration, stuck doc recovery, agent manager init) from `server.py`
- [ ] 4.3 Merge duplicate `Limiter` instances: keep single instance in `raganything/dependencies.py`, use it in `server.py` for `app.state.limiter`
- [ ] 4.4 Split `raganything/routers/shared.py` God Module: routers import directly from canonical sources; keep only router-shared concerns
- [ ] 4.5 Eliminate circular lazy imports: extract event bus or observer pattern for kb_service ↔ ws_service ↔ state_service communication
- [ ] 4.6 Ensure `get_current_user` and `get_admin_user` have single canonical definition in `dependencies.py` only

## 5. Code Quality (P1)

- [ ] 5.1 Remove dead code: duplicate `validate_query_input`, `_DEGRADED_HINT`, `PROMPT_INJECTION_PATTERNS`, `RequestSizeMiddleware` from `server.py`
- [ ] 5.2 Fix `rerank_chunks` import: add `from raganything.query import rerank_chunks` in `raganything/query/pipeline.py`
- [ ] 5.3 Fix `await` on sync `llm_func`: make function async or remove `await` in `raganything/services/kb_service.py`
- [ ] 5.4 Fix mutable default argument `history_messages=[]` in `llm_func` in `raganything/services/kb_service.py`
- [ ] 5.5 Replace 13+ `except Exception: pass` instances with logged warnings (exclude destructor/shutdown paths)
- [ ] 5.6 Remove duplicate docstrings (e.g., `delete_kb` in kb_service.py) and duplicate import statements
- [ ] 5.7 Remove duplicate `from typing import Optional` in `raganything/services/kb_service.py`
- [ ] 5.8 Extract chunking strategy swap pattern to `@asynccontextmanager` in `raganything/chunking/`
- [ ] 5.9 Consolidate `_DEGRADED_HINT`/`DEGRADED_CONTEXT_HINT` to single canonical definition in `raganything/query/utils.py`
- [ ] 5.10 Remove root-level backward-compat wrappers `auth.py` and `agent_manager.py`; update all consumers

## 6. Database & Performance (P1)

- [ ] 6.1 Merge `get_current_user()` queries: reduce 3 DB round-trips to 1 in `raganything/dependencies.py`
- [ ] 6.2 Standardize on `aiosqlite` for ALL database access: replace sync `sqlite3.connect()` in `audit.py` and `token_blacklist.py`
- [ ] 6.3 Set `busy_timeout` on all SQLite connections (not just in `init_db()`)
- [ ] 6.4 Replace `SELECT *` with explicit column lists (excluding `password_hash`) in user queries
- [ ] 6.5 Add `busy_timeout` PRAGMA to every `aiosqlite.connect()` call in `raganything/services/auth.py`

## 7. Testing & Validation

- [ ] 7.1 Create `tests/security/test_injection_defense.py`: test all patterns + bypass payloads + benign queries
- [ ] 7.2 Create `tests/security/test_auth_endpoints.py`: verify all previously-unauthenticated endpoints return 401
- [ ] 7.3 Create `tests/test_atomic_writes.py`: verify tmp+replace pattern for kb_meta and query_history
- [ ] 7.4 Update `verify_bypass.py` to import patterns from `raganything.utils.security` instead of its own copy
- [ ] 7.5 Run full test suite and verify no regressions
