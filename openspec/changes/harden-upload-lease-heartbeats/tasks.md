## 1. Lease Renewal and Failure Semantics

- [x] 1.1 Permit an unreclaimed quota lease to be renewed only by its exact owner and lease ID after a delayed worker heartbeat.
- [x] 1.2 Convert worker-owned quota lease loss or heartbeat failure into a structured, retryable quota-stage worker error while preserving external cancellation.
- [x] 1.3 Match completed worker documents using queue-task metadata rather than internal run IDs, with a durable PG status fallback.

## 2. Regression Coverage

- [x] 2.1 Add lease repository regressions for delayed owner renewal and reclaimed-lease fencing.
- [x] 2.2 Add worker lifecycle regressions for quota lease loss, heartbeat exceptions, and external cancellation behavior.
- [x] 2.3 Verify parent upload error parsing preserves retryable quota failures.
- [x] 2.4 Add a completion-snapshot regression for a stale cached document-status view and a worker-owned run ID.

## 3. Validation and Recovery

- [x] 3.1 Run targeted lease, worker, and upload lifecycle tests plus static checks.
- [x] 3.2 Restart the backend after validation and requeue the retained failed upload once, verifying it reaches parsing and durable completion.
- [x] 3.3 Update `PROJECT_SUMMARY.md` with validation results and the hardened lease behavior.
