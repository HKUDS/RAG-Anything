## Why

A transient PostgreSQL network interruption currently collapses into the same `None` result as a fenced `UPDATE 0`, so an upload can be reported as `upload_claim_lost` even though no competing owner reclaimed it. The background retry and tagging loops then emit repeated tracebacks while durable recovery is delayed or ambiguous.

## What Changes

- Distinguish authoritative claim/lease loss from temporary database unavailability at claim-aware persistence boundaries.
- Keep upload and KB-mutation heartbeat grace periods within their durable fencing windows, stopping workers only after ownership is disproved or the bounded uncertainty window expires.
- Requeue interrupted uploads durably after connectivity returns without allowing late writes or duplicate workers.
- Apply bounded exponential backoff and recovery logging to upload retry, durable queue, and document-tag reconciliation loops.
- Use only asyncpg-supported pool options and verify startup/runtime reconnect behavior.

## Capabilities

### New Capabilities

- `upload-claim-db-resilience`: Defines upload ownership, database-outage tolerance, durable recovery, and background-loop behavior during transient PostgreSQL failures.

### Modified Capabilities

- `upload-concurrency-control`: Clarifies that the in-memory dispatch queue is reconstructed from durable upload state and that a database interruption must not create concurrent processors for one upload.

## Impact

The change affects the PostgreSQL state repository, upload claim and KB-mutation lease handling, durable upload retry/recovery, automatic-tag reconciliation, focused backend tests, and operational logs. It does not change HTTP APIs, RBAC, stored user data, or require a schema migration.
