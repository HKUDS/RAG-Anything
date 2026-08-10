## 1. Persistence Semantics

- [x] 1.1 Add a shared transient PostgreSQL connection classifier and make claim-aware updates re-raise outages while preserving `None` for successful `UPDATE 0`.
- [x] 1.2 Use asyncpg-compatible pool options (`timeout=10`, `command_timeout=30`, `max_inactive_connection_lifetime=300`) and cover startup compatibility.

## 2. Lease and Worker Recovery

- [x] 2.1 Set upload heartbeat/grace constants to 15 seconds and 180 seconds; stop only on confirmed fencing or bounded grace exhaustion.
- [x] 2.2 Set KB mutation lease TTL to 300 seconds and assert the grace/heartbeat/TTL invariant; prevent expired-lease revival.
- [x] 2.3 Ensure one-time worker termination, registry cleanup, original owner/generation retry, and stale-scanner fallback without late writes.

## 3. Background Loops

- [x] 3.1 Apply capped exponential backoff and recovery logging to retry runner and durable queue scanner.
- [x] 3.2 Apply the same backoff and recovery behavior to terminal tag reconciliation and automatic tag claiming.

## 4. Regression and Acceptance

- [x] 4.1 Add focused regressions for outage vs `UPDATE 0`, short outage recovery, grace exhaustion, owner/generation fencing, and lease TTL ordering.
- [x] 4.2 Add tagging/retry loop tests with no un-awaited coroutine warnings.
- [x] 4.3 Run the required five-file pytest command and document controlled PostgreSQL acceptance gaps/results in `PROJECT_SUMMARY.md`.
