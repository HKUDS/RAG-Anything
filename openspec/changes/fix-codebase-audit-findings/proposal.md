# Proposal: Fix Codebase Audit Findings

## Why

A comprehensive multi-expert audit of the RAG-Anything codebase (97 Python files, ~15K LOC, post-major-refactoring) identified **30 blocker-level**, **36 warning-level**, and **15 advisory-level issues** spanning architecture, security, database integrity, and code quality. The most critical findings include: 15+ unauthenticated API endpoints, trivially bypassable prompt injection defense, non-atomic data persistence risking corruption on crash, global mutable state without synchronization, and pervasive code duplication. These issues collectively compromise system security, data integrity, and long-term maintainability. Fixing them now — before production deployment or further feature development — prevents compounding technical debt and reduces the risk of data loss or security breach.

## What Changes

### Security Fixes (P0 — Critical)
- Add authentication (`Depends(get_current_user)`) to 15 manufacturing endpoints currently accepting unauthenticated requests
- Add authentication to unauthenticated WebSocket endpoints (`/ws`, `/ws/workflow-run/{run_id}`)
- Add authentication and path validation to `/files/image` endpoint (arbitrary file read vulnerability)
- Fix JWT secret race condition in multi-worker deployments by moving key generation into `init_db()` with DB-level synchronization
- Fix file upload path traversal by sanitizing `file.filename` (basename extraction + allowlist)
- Remove `unsafe-inline` and `unsafe-eval` from Content-Security-Policy header
- Add RBAC permission checks (`require_permission`) to admin settings, monitor, and workflow endpoints
- Add audit logging for blocked injection attempts

### Prompt Injection Defense (P0 — Critical)
- Add `validate_query_input()` to 5 query-bearing endpoints currently unprotected: agent query stream, manufacturing QA/stream, fault diagnosis
- Add Unicode normalization (NFKC) + zero-width character stripping before regex matching
- Add Chinese-language injection patterns to detection regexes
- Add document content scanning for injection payloads at ingestion time (indirect injection defense)
- Add `system_prompt` field validation in AgentCreateRequest/AgentUpdateRequest
- Consolidate prompt assembly into a single function with XML tag delimiters for instruction/data separation
- Harden system prompts with explicit injection refusal rules

### Data Integrity (P0 — Critical)
- Convert `save_kb_meta()` to atomic write pattern (`.tmp` + `replace`)
- Convert `save_query_history()` to atomic write with debounce batching
- Add `asyncio.Lock` to `get_kb()` to prevent concurrent initialization race condition
- Remove `is_admin` column from new user INSERT (eliminate dual source-of-truth with RBAC)
- Add index on `users.role_id`
- Narrow `init_db()` exception handling to catch only "duplicate column" errors

### Architecture Cleanup (P1 — High)
- Eliminate `routers/shared.py` God Module — split into focused facade modules
- Eliminate service-layer circular lazy imports (kb_service ↔ ws_service ↔ state_service)
- Merge duplicate `Limiter` instances (server.py vs dependencies.py) into single source
- Merge duplicate `get_current_user`/`get_admin_user` (routers/shared vs dependencies)
- Extract middleware from `server.py` into dedicated `raganything/middleware.py`
- Extract startup logic from `server.py` into `raganything/bootstrap.py`

### Code Quality (P1 — High)
- Remove dead code: duplicate `validate_query_input`, `_DEGRADED_HINT`, `RequestSizeMiddleware` in server.py
- Fix `rerank_chunks` called without import in pipeline.py (runtime `NameError`)
- Fix `await` on sync `llm_func` in kb_service.py (runtime `TypeError`)
- Fix mutable default argument `history_messages=[]` in kb_service.py
- Replace 13+ `except Exception: pass` instances with logged warnings
- Remove duplicate docstrings and duplicate import statements
- **BREAKING**: Remove root-level backward-compat wrappers `auth.py` and `agent_manager.py` (deprecated, re-export only)

## Capabilities

### New Capabilities
- `auth-hardening`: Authentication and authorization fixes across manufacturing, WebSocket, admin, and image-serving endpoints
- `injection-defense`: Multi-layered prompt injection defense (input normalization + Chinese patterns + document scanning + prompt hardening + XML delimiters)
- `data-integrity`: Atomic file writes, concurrent access synchronization, schema fixes
- `architecture-cleanup`: Module consolidation, import hygiene, middleware extraction, service boundary enforcement
- `code-quality`: Dead code removal, bug fixes, exception handling, deduplication

### Modified Capabilities
<!-- No existing specs to modify — this is a greenfield audit fix -->

## Impact

### Affected Code
- **server.py**: middleware extraction, startup logic extraction, dead code removal, import consolidation
- **raganything/routers/**: manufacturing.py (auth), admin.py (RBAC + WebSocket auth), knowledge.py (path traversal + image auth), query.py (prompt assembly), agent.py (injection validation + system_prompt validation), shared.py (God Module split)
- **raganything/services/**: kb_service.py (atomic writes + asyncio.Lock + dead code), auth.py (JWT secret race + is_admin removal + index), token_blacklist.py (connection pooling), state_service.py (atomic writes + debounce), ws_service.py (framework coupling)
- **raganything/utils/security.py**: Unicode normalization + Chinese patterns + audit logging
- **raganything/query/pipeline.py**: rerank_chunks import fix + prompt assembly consolidation
- **raganything/config.py**: single configuration source-of-truth
- **raganything/dependencies.py**: limiter consolidation
- **New files**: `raganything/middleware.py`, `raganything/bootstrap.py`, `raganything/prompt/protection.py`

### APIs Affected
- 15 manufacturing endpoints now require authentication (**BREAKING** for unauthenticated clients)
- `/files/image` now requires authentication (**BREAKING** for unauthenticated access)
- WebSocket endpoints now require authentication token query parameter (**BREAKING**)
- Admin endpoints now enforce RBAC permission checks
- Root-level `auth.py` and `agent_manager.py` removed (**BREAKING** — import from `raganything.services.*` instead)

### Dependencies
- New: `unicodedata` (stdlib, for NFKC normalization)
- No new third-party dependencies required
