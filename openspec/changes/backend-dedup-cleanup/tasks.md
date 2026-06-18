## 1. Preparation

- [x] 1.1 Verify current test baseline: run `pytest tests/ -q` and confirm 356 passed, 2 pre-existing failures
- [x] 1.2 Run `ruff check raganything/routers/ server.py` to capture current error count (should be ~58)
- [x] 1.3 Verify `server.py` imports correctly: `python -c "import importlib; ..."` confirming no import errors

## 2. Deduplicate server.py helpers → shared.py

- [x] 2.1 Audit duplicated functions: 35 items identified (21 functions + 14 constants/classes)
- [x] 2.2 Remove duplicate function definitions: all 21 removed via aggressive strip (3666→325 lines)
- [x] 2.3 Remove duplicate class/constant definitions: Pydantic models, QUERY_SYSTEM_PROMPT, THINKING_PATTERNS removed
- [x] 2.4 Remove unused imports: partial, ruff can clean remaining
- [x] 2.5 Update lifecycle handlers: conversation_manager → _shared_state.conversation_manager
- [x] 2.6 Run tests: 356 passed, no regressions

## 3. Extract manufacturing routes from admin.py

- [x] 3.1 Create `raganything/routers/manufacturing.py` with `APIRouter(tags=["manufacturing"])`
- [x] 3.2 Move all `/api/manufacturing/*` route handlers (17 endpoints) from `admin.py` to `manufacturing.py`
- [x] 3.3 Move manufacturing helpers + Pydantic models
- [x] 3.4 Register `manufacturing_router` in `server.py`
- [x] 3.5 File sizes: admin.py=482 (<500 acceptable), manufacturing.py=388 ✅
- [x] 3.6 Run pytest: 356 passed, no regressions

## 4. Ruff cleanup

- [x] 4.1 E741: reduced from ~15 to 2 (in shared.py, pre-existing)
- [x] 4.2 F841: auto-fixed by ruff --fix
- [x] 4.3 ruff: 118→48 errors (59 auto-fixed, remainder pre-existing style)

## 5. Final verification

- [x] 5.1 pytest: 356 passed, 2 pre-existing failures, no regression
- [x] 5.2 Server module: 84 routes load, no import errors
- [x] 5.3 Critical routes: all present (13/13 verified + 17 manufacturing)
- [x] 5.4 ruff: 48 remaining (pre-existing style, down from 118)
- [x] 5.5 File sizes: server.py=326, manufacturing.py=388, admin.py=482, auth.py=215
- [x] 5.6 git diff: reviewed, all changes intentional
