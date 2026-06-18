## Why

`server.py` (803 lines) and `raganything/routers/shared.py` (742 lines) contain ~300 lines of duplicated helper functions (`get_kb`, `create_rag`, `_process_uploaded_file`, `load_kb_meta`, `save_kb_meta`, etc.). This duplication is a maintenance hazard — any bug fix or enhancement to these functions must be applied in two places. Additionally, `admin.py` (861 lines) exceeds the 400-line router target and needs splitting.

## What Changes

- **Deduplicate helper functions**: Extract shared helper functions from `server.py` and `raganything/routers/shared.py` into a single source of truth (`shared.py`), then import them in `server.py`
- **Split oversized router**: Extract manufacturing routes from `admin.py` (860→<400) into `routers/manufacturing.py`
- **Reduce server.py below 300 lines**: By removing all duplicated helpers and keeping only app bootstrap (imports, middleware, lifecycle, router registration)
- **Reduce ruff errors**: Fix remaining 58 ruff issues (mostly `E741 ambiguous variable 'l'` and `F841 unused variables`) to bring the count to zero
- **Add missing docstrings**: Public functions in `raganything/routers/` lacking Google-style docstrings

## Capabilities

### New Capabilities
- `router-dedup`: Deduplicate shared helper functions — `shared.py` becomes the single source of truth; `server.py` imports from it
- `router-manufacturing-split`: Extract manufacturing routes from `admin.py` into a dedicated `manufacturing.py` router module

### Modified Capabilities
<!-- None — this is a pure refactoring with no requirement-level changes. All API paths, business logic, and database operations remain unchanged. -->

## Impact

- Affected files: `server.py`, `raganything/routers/shared.py`, `raganything/routers/admin.py`, new `raganything/routers/manufacturing.py`
- No API changes, no breaking changes
- All 84 routes preserved with identical paths
- Test baseline: 356 passed (2 pre-existing failures unchanged)
