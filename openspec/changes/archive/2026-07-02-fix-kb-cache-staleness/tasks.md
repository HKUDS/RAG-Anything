## 1. Cache Invalidation in get_kb()

- [x] 1.1 Add `_kb_cache_time: dict[str, float]` global dict to track when each KB instance was created
- [x] 1.2 Add mtime check in `get_kb()` — if `kb_instances[name]` exists, compare `kv_store_doc_status.json` mtime against `_kb_cache_time[name]`
- [x] 1.3 On stale cache: call `finalize_storages()`, `del kb_instances[name]`, log info message, then proceed to recreate
- [x] 1.4 Update `_kb_cache_time[name]` when a new instance is created

## 2. Stuck Document Recovery

- [x] 2.1 Add `_recover_stuck_documents()` function — scan all KBs' `kv_store_doc_status.json`, fix documents with status="handling" + `processing_end_time` set → mark as "completed", clear KB cache
- [x] 2.2 Add `_stuck_recovery_loop()` — create asyncio background task with 300s loop, call `_recover_stuck_documents()` each iteration
- [x] 2.3 Wire the recovery task into FastAPI lifespan startup — run initial scan immediately, then start periodic loop
- [x] 2.4 Handle errors gracefully — single KB failure does not abort the entire scan loop

## 3. Admin Reload API

- [x] 3.1 Add `POST /admin/reload-kb/{kb_name}` endpoint in `raganything/routers/admin.py`
- [x] 3.2 Require `settings:write` permission via `require_permission(Permission.SETTINGS_WRITE)`
- [x] 3.3 Clear cached instance: `finalize_storages()` + `del kb_instances[kb_name]` if exists
- [x] 3.4 Return appropriate JSON response (`ok` if cleared, `skipped` if not in cache)

## 4. Verify

- [x] 4.1 Test: upload document to KB → verify `get_kb()` auto-reloads when doc_status mtime changes
- [x] 4.2 Test: manually set doc_status to "handling" with processing_end_time → wait 300s → verify auto-recovery
- [x] 4.3 Test: `POST /admin/reload-kb/test` → verify cache cleared and next query loads fresh data
- [x] 4.4 Verify existing upload flow still works (cache clearing in `_process_uploaded_file` not broken)
