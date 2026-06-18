## Context

After Phase A of the backend refactoring (Router integration), `server.py` was reduced from 3,666 to 803 lines. However, ~300 lines of helper functions (`get_kb`, `create_rag`, `_process_uploaded_file`, `load_kb_meta`, `save_kb_meta`, `kb_dir`, `extract_image_paths`, `validate_query_input`, auth dependencies, etc.) are duplicated between `server.py` and `raganything/routers/shared.py`.

Additionally, `admin.py` (861 lines) hosts 36 routes spanning workflows, settings, monitoring, health, AND manufacturing — exceeding the 400-line target. The manufacturing section (300+ lines) is self-contained and a natural candidate for extraction.

**Current state:**
- `server.py`: 803 lines — imports, middleware, lifecycle, router registration + ~300 lines of duplicated helpers
- `shared.py`: 742 lines — same helpers + shared state
- `admin.py`: 861 lines — 36 routes in 5 loosely-related groups
- ruff: 58 remaining issues (pre-existing style problems)

## Goals / Non-Goals

**Goals:**
- Eliminate all duplicated helper functions between `server.py` and `shared.py` — `shared.py` becomes the single source of truth
- Reduce `server.py` below 300 lines (only app bootstrap remains)
- Split `admin.py` into `admin.py` (<400 lines) + `manufacturing.py` (<400 lines)
- Reduce ruff errors to zero (fix 58 remaining issues)
- Zero API contract changes, zero business logic changes, zero test regressions

**Non-Goals:**
- Not changing any function behavior or API path
- Not touching `raganything/parser/`, `raganything/processor/`, `raganything/query/` subpackages
- Not modifying `agent_manager.py`, `auth.py`, or `process_worker.py`
- Not introducing new test files
- Not splitting `agent.py` (669 lines) or `query.py` (593 lines) — deferred to future

## Decisions

### D1: `shared.py` as single source of truth

**Decision:** Move ALL remaining helper functions from `server.py` into `shared.py`. `server.py` imports them.

**Alternatives considered:**
- **Keep both copies, add lint warning**: Fragile — any bug fix requires double-patching. Rejected.
- **Create separate `helpers.py` module**: Adds another import layer without benefit. Rejected.
- **Import from server.py in routers**: Creates circular import risk (routers ← server ← routers). Rejected.

**Rationale:** `shared.py` already contains identical copies of these functions. Routers already import from `shared.py`. Consolidating here requires only deleting from `server.py` and adding import aliases.

### D2: Extract manufacturing routes to `routers/manufacturing.py`

**Decision:** Move all `/api/manufacturing/*` routes (12 endpoints) + `_get_manufacturing()` helper into a new `manufacturing.py` router. Register it alongside the existing 5 routers.

**Rationale:** The manufacturing section has clear domain boundaries (knowledge graph, process library, fault cases, code parsing, dashboard). It imports from `raganything.manufacturing.*` — a distinct subsystem. The 12 routes are self-contained and don't share state with other admin routes.

### D3: ruff fixes — targeted approach

**Decision:** Fix E741 (`l` → meaningful name) and F841 (unused variables) only. Skip E501 (line length) — pre-existing and cosmetic.

**Rationale:** E741 affects readability without risk. F841 removes dead code safely. Other issues are cosmetic and don't block completion.

### D4: Import pattern in `server.py`

**Decision:** `server.py` will import functions from `_shared_state` (already aliased to `shared` module):
```python
from raganything.routers import shared as _shared_state
get_kb = _shared_state.get_kb
create_rag = _shared_state.create_rag
# ... etc
```

**Rationale:** Preserves existing code patterns in `server.py`'s lifecycle handlers that call these functions by short names. Adding `_shared_state.` prefix to every call site is noisy and unnecessary.

## Risks / Trade-offs

- **[Risk] `shared.py` grows too large**: Manufacturing helpers (`_get_manufacturing`, etc.) could be added to shared.py if admin router needs them → **Mitigation**: Keep manufacturing helpers inside `manufacturing.py`, not shared.
- **[Risk] Circular import**: If `shared.py`'s functions reference `server.py`-specific objects → **Mitigation**: Shared state (dicts, lists) is already in `shared.py`. No function currently imports from `server.py`.
- **[Trade-off] `server.py` still >300 lines if middleware kept inline**: The CORS + security + request size middleware (~80 lines) could be extracted → **Mitigation**: Accept 250-300 lines as realistic target; middleware is app bootstrap, not business logic.
