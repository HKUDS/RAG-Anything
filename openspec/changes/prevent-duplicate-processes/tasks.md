## 1. Shared Infrastructure: Cross-Platform File Lock

- [x] 1.1 Create `raganything/utils/process_lock.py` with `FileLock` class supporting Windows (`msvcrt.locking`) and Unix (`fcntl.flock`)
- [x] 1.2 Implement `acquire(timeout=0)` non-blocking lock acquisition with boolean return
- [x] 1.3 Implement `release()` and `__enter__`/`__exit__` context manager protocol
- [x] 1.4 Implement `is_locked()` convenience method to check lock status without acquiring
- [x] 1.5 Auto-create `<working_dir>/.locks/` directory on first lock file creation

## 2. Server Startup Lock

- [x] 2.1 Add PID file creation in `server.py` startup sequence: write `<working_dir>/.server.pid` with PID + ISO timestamp
- [x] 2.2 Add PID file validation on startup: check if existing PID is alive, exit with error if so, proceed if stale
- [x] 2.3 Add port pre-check in `server.py`: attempt `socket.bind()` before uvicorn startup, exit gracefully if port in use
- [x] 2.4 Register `atexit` handler to clean `.server.pid` on graceful and abnormal shutdown
- [x] 2.5 Clean up `.server.pid` on SIGTERM/SIGINT via signal handler

## 3. Upload API Dedup Guard

- [x] 3.1 Add `_compute_file_hash(file_path)` helper in `kb_service.py` using SHA256 on first N bytes of file content
- [x] 3.2 Add `_is_file_being_processed(kb_name, file_hash)` check against active `processing_tasks` dictionary
- [x] 3.3 Modify upload endpoint in `kb_service.py` to return HTTP 409 Conflict when duplicate detected
- [x] 3.4 Include `existing_task_id` in 409 response body for frontend tracking
- [x] 3.5 Add WebSocket broadcast of `{"type": "duplicate", ...}` when duplicate upload is rejected
- [x] 3.6 Clean up completed task entries from dedup tracking when worker finishes/fails

## 4. Worker File Lock

- [x] 4.1 Add `_check_doc_status_not_processing(doc_id)` guard in `process_worker.py` before processing: query `doc_status`, reject if status is "processing" with updated_at within 5 minutes
- [x] 4.2 Add `FileLock` acquisition in `process_worker.py` `process_file()`: lock file at `<working_dir>/.locks/<file_hash>.lock`
- [x] 4.3 Worker exits with code 3 if lock acquisition fails or doc_status guard triggers
- [x] 4.4 Server (`kb_service.py`) interprets worker exit code 3 as "conflict" and marks task accordingly

## 5. Integration & Verification

- [x] 5.1 Manual test: start server twice, verify second instance exits with "Server already running"
- [x] 5.2 Manual test: upload same file twice simultaneously, verify second request returns 409
- [x] 5.3 Manual test: kill worker mid-processing, verify lock releases and new worker can acquire it
- [x] 5.4 Verify stale PID file in `.server.pid` doesn't block restart after crash
- [x] 5.5 Verify no regressions in existing upload flow (single upload → processing → completed)
