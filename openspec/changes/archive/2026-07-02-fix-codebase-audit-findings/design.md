# Design: Fix Codebase Audit Findings

## Context

After a major architectural refactoring (100+ commits, branch `feature/custom-enhancements`), a comprehensive multi-expert audit of 97 Python files in the RAG-Anything codebase identified 81 issues across architecture, security, database, and code quality domains. The refactoring substantially improved code organization (extracting services, routers, shared facades) but introduced or left unaddressed several critical problems: 15 unauthenticated API endpoints, trivially bypassable prompt injection defense, non-atomic data persistence, global mutable state without synchronization, and pervasive code duplication.

The system is a FastAPI-based multimodal RAG document processing server with RBAC authentication, multi-knowledge-base management, and agentic RAG capabilities. It uses SQLite for auth data, JSON files for metadata, and LightRAG for vector/graph storage.

## Goals / Non-Goals

**Goals:**
- Close all critical security gaps (unauthenticated endpoints, path traversal, arbitrary file read, JWT race condition)
- Deploy multi-layered prompt injection defense (normalization + regex + Chinese patterns + XML delimiters + document scanning)
- Ensure data integrity through atomic writes and concurrent access synchronization
- Clean up architecture: eliminate God Module, circular imports, code duplication
- Fix runtime bugs (missing imports, sync/await mismatches, mutable defaults)

**Non-Goals:**
- Full migration from SQLite to PostgreSQL (separate change)
- Complete rewrite of RAGAnything mixin hierarchy (too high-risk; addressed via documentation)
- Adding new features beyond audit fixes
- Replacing the regex-based injection filter with an ML classifier (this change adds Unicode normalization and Chinese patterns; ML classifier is a future enhancement)

## Decisions

### D1: Authentication Fix Strategy — Per-Endpoint Depends vs Router-Level

**Choice**: Add `Depends(get_current_user)` to each manufacturing endpoint individually rather than applying a router-level dependency.

**Rationale**: The manufacturing router may have some endpoints intended for public access in the future. Per-endpoint auth makes intentionality explicit. However, for the WebSocket endpoints, we use token-as-query-parameter validation since WebSocket upgrade requests cannot carry Bearer headers.

**Alternatives considered**: Router-level `dependencies=[Depends(get_current_user)]` would be safer (no endpoint can accidentally omit auth) but would break any intentionally public endpoints.

### D2: Atomic Writes — Write-to-Temp-then-Replace Pattern

**Choice**: Use `Path.write_text()` on a `.tmp` file then `Path.replace()` for all JSON metadata files.

**Rationale**: On NTFS (Windows), `os.replace()` is atomic — it's a `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING` flag. This prevents truncated/corrupt files on crash. Same pattern already used successfully in `_fix_stuck_doc_status()`.

**Alternatives considered**: File locking (`fcntl`/`msvcrt`) would add complexity without guaranteeing atomicity. Append-only journal with periodic compaction would be more robust but over-engineered for the current scale.

### D3: Limiter Consolidation — Single Instance in dependencies.py

**Choice**: Keep the single `Limiter` instance in `dependencies.py` (already used by all routers via `shared.py` re-export) and remove the duplicate in `server.py` line 59. Register the exception handler using the dependencies limiter.

**Rationale**: Two independent limiter instances with different defaults (one with `default_limits=["120/minute"]`, one without) creates unpredictable rate-limiting behavior. The dependencies.py instance is the one actually used by route decorators.

### D4: God Module Split — routers/shared.py

**Choice**: Split `routers/shared.py` into:
- `raganything/routers/shared.py` → keep only router-shared concerns (logger, thinking message translation, image path extraction)
- Re-exports moved to their canonical source modules; routers import directly from `services/`, `dependencies`, `utils/`

**Rationale**: The 49-symbol re-export facade from 7 modules creates hidden transitive dependencies. Each router should explicitly import only what it needs from the canonical source.

### D5: Prompt Injection Defense — XML Delimiters

**Choice**: Wrap user queries in `<user_query>` tags, retrieval context in `<retrieved_data>` tags, and conversation history in `<conversation_history>` tags. Add explicit precedence rules in hardened system prompts.

**Rationale**: XML tag delimiters are recognized by Claude/GPT-class models as structural boundaries. This provides instruction/data separation that regex alone cannot achieve. The hardened system prompt explicitly states that content inside `<retrieved_data>` is untrusted data, not instructions.

### D6: JWT Secret — DB-Synchronized Generation

**Choice**: Move `SECRET_KEY` generation from module-import-time to `init_db()` with `BEGIN IMMEDIATE` transaction to serialize multi-worker access.

**Rationale**: Module-level `secrets.token_hex(32)` generates different keys per worker process. By persisting and loading from the `settings` table with an immediate transaction, all workers converge on the same key. Environment variable `JWT_SECRET` still takes precedence when set.

## Risks / Trade-offs

- **[Breaking] Unauthenticated endpoints now require auth**: Any external clients accessing manufacturing endpoints without tokens will receive 401. → Mitigation: Document in release notes; provide migration window.
- **[Breaking] Root-level auth.py and agent_manager.py removed**: Any scripts importing from root-level wrappers will break. → Mitigation: Update all known consumers (query.py, process_worker.py, examples/) to import from `raganything.services.*`.
- **[Performance] Unicode normalization adds ~0.1ms per query**: Negligible for the 100ms budget. → Acceptable.
- **[Complexity] XML delimiter approach requires coordinated system prompt + tag sanitization**: If sanitization misses a closing tag variant, attackers could break out of data boundaries. → Mitigation: Comprehensive tag sanitization function with test suite.
- **[Race condition] asyncio.Lock in get_kb() serializes KB initialization**: Under high concurrency, lock contention could delay requests. → Acceptable trade-off: correctness over throughput for initialization path.
