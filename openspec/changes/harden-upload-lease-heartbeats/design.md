## Context

Uploads use three independent guards: a durable upload claim in the server, a KB mutation lease in the server, and a user quota lease in the isolated worker. The worker quota lease expires after 30 seconds. Synchronous LightRAG bootstrap can block the worker event loop longer than that, preventing the heartbeat coroutine from running. The first delayed heartbeat then sees an expired row, cancels the worker, and the top-level launcher reduces the cause to `CancelledError`.

## Goals / Non-Goals

**Goals:**
- Preserve a valid worker's quota lease across a temporary event-loop stall when no other worker has reclaimed it.
- Preserve exclusive concurrency when another worker has reclaimed the expired lease.
- Expose genuine lease loss as a retryable, structured upload failure.
- Test the persistence and worker error contracts without requiring a live model service.

**Non-Goals:**
- Changing configured concurrency limits, queue ordering, or automatic retry backoff.
- Silently continuing after a lease is owned by another worker.
- Retrying the user's failed upload until its state is classified and the fix is deployed.

## Decisions

### Owner-scoped lease renewal

`heartbeat_quota_lease()` will renew a row matched by its immutable lease ID and owner even if its recorded expiry has just passed. A later claimant atomically deletes expired rows before creating its own lease; once that occurs, the old owner update affects zero rows and must stop. This avoids a false cancellation after local event-loop starvation while retaining the database as the fencing authority.

Alternative: increase the TTL globally. Rejected because it delays crash recovery and cannot guarantee that a blocking bootstrap never exceeds the new value.

### Structured worker lease-loss outcome

The worker heartbeat records lease loss before cancelling the processing task. `process_file()` catches that cancellation, emits `stage=quota`, `root_type=QuotaLeaseLost`, and a retryable `quota_lease_lost` failure. External cancellation is re-raised unchanged so explicit deletion and process shutdown retain their existing behavior.

Alternative: retry inside the worker after lease loss. Rejected because it could write concurrently with the worker that reclaimed the lease.

### Tests at the lease and worker boundaries

Tests will assert SQL does not require an unexpired timestamp for an owner-matched renewal, assert a changed owner remains fenced, and assert a marked quota loss returns a structured retryable worker exit instead of escaping to the generic bootstrap handler.

## Risks / Trade-offs

- [A crashed worker's row remains renewable until another claimant or cleanup acts] → Renewal still requires the exact lease ID and owner; new acquisition deletes expired rows atomically and fences the prior worker.
- [A real concurrent takeover stops a worker after partial processing] → Existing document quality/cleanup paths and retry behavior continue to handle partial state; the worker reports the failure as retryable.
- [Other lease types have different semantics] → This change is scoped to `user_quota_leases`; upload-claim and KB-mutation lease behavior is unchanged.

## Migration Plan

1. Deploy code without a database migration.
2. Run lease and worker lifecycle regressions.
3. Restart the backend only after tests pass, then requeue the retained failed upload once and monitor its durable state through completion.
4. Roll back by restoring the previous code; no persisted data needs rollback.

## Open Questions

None. The observed failure and task state establish the required boundary behavior.
