## Context

Upload workers currently use nullable results from claim-aware PostgreSQL updates. A connection reset can therefore be mistaken for `UPDATE 0`, causing a false `upload_claim_lost` cancellation. The same outage also drives retry and tagging loops, which currently log on a short fixed interval. This change spans the state repository, upload queue, KB mutation lease, retry/tagging loops, and focused tests.

## Goals / Non-Goals

**Goals:**

- Preserve the distinction between database unavailability and an authoritative owner/generation mismatch.
- Keep heartbeat grace bounded by the durable fencing windows and stop an uncertain worker at most once.
- Requeue after recovery with provenance-scoped cleanup and no late writes or duplicate processors.
- Use only asyncpg 0.31-compatible pool arguments and bounded exponential backoff with recovery logging.

**Non-Goals:**

- No HTTP API or database schema changes.
- No filename-only ownership inference and no automatic revival of an expired lease.
- No live PostgreSQL fault injection in unit tests; deployment acceptance remains an operational step.

## Decisions

1. `pg_state_repo` exposes one transient-connection classifier covering `OSError` and asyncpg connection/connection-establishment failures. Claim-aware updates return `None` only after a successful SQL command with zero affected rows; connection failures are re-raised.
2. Upload heartbeats run every 15 seconds and tolerate at most 180 seconds of consecutive database failures. A successful `UPDATE 0` or a changed owner/generation cancels immediately. KB mutation leases use a 300-second TTL, the same 15-second heartbeat, and a compile-time assertion that `grace + heartbeat_interval < ttl`.
3. Grace exhaustion performs one bounded worker termination and removes in-memory registrations. If PostgreSQL is available the original owner/generation atomically enters retry after existing provenance cleanup; otherwise durable `processing` state is left for the five-minute stale scanner.
4. Retry, durable queue, terminal-tag reconciliation, and automatic-tag claim loops use capped exponential backoff. They emit one full exception at outage start and one recovery INFO, with subsequent failures represented by attempt and delay fields.

## Risks / Trade-offs

- [A prolonged outage leaves processing rows visible] -> The stale scanner remains the durable recovery authority at 300 seconds.
- [A worker may have partially written data before termination] -> Retry cleanup is keyed by task/file provenance and runs before reprocessing.
- [A pool outage can affect unrelated operations] -> Exceptions remain visible to callers and logs; no silent fallback converts them to ownership loss.

## Migration Plan

Deploy code without a migration. Run the focused test suite, then perform the three controlled PostgreSQL outage/owner-fencing acceptance scenarios and inspect durable upload, task, chunk, media, and graph state. Roll back by restoring code; no persisted schema rollback is needed.

## Open Questions

None.
