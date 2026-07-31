## Why

A valid upload can be cancelled before parsing when synchronous worker bootstrap delays its event loop beyond the 30-second quota lease TTL. The resulting `CancelledError` is incorrectly reported as an unretryable bootstrap failure, so users are asked to upload again even though the retained file and model are valid.

## What Changes

- Allow the current lease owner to renew its own expired-but-not-reclaimed quota lease, preventing event-loop bootstrap stalls from self-cancelling an otherwise exclusive upload.
- Preserve lease fencing: a worker whose expired lease has been reclaimed by another owner must stop and report a retryable lease-loss failure.
- Emit a structured, retryable `quota_lease_lost` worker failure instead of an unclassified `CancelledError`.
- Read freshly committed child-worker document status before treating a completed upload as missing.
- Add regressions for delayed heartbeats, genuine lease loss, and the public worker error contract.

## Capabilities

### New Capabilities

- `upload-lease-resilience`: Durable upload lease renewal and failure reporting resilient to temporary event-loop stalls.

### Modified Capabilities

- `upload-failure-detection`: Worker failures caused by a lost processing lease are classified as retryable and actionable.

## Impact

- `raganything/services/user_settings.py`
- `process_worker.py`
- `raganything/services/kb_service.py`
- Upload lifecycle tests and the upload failure contract
- PostgreSQL `user_quota_leases` semantics; no schema migration is required
