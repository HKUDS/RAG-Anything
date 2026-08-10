## Context

`make_cached_embed_func()` is asynchronous, but it calls synchronous cache methods that create a daemon thread and a new event loop for every PostgreSQL read and write. The process-wide asyncpg pool is created by the worker event loop and is not safe to use from those thread-local loops. The resulting connection failures are swallowed by the cache while asyncpg can retain failed futures, so a later LightRAG vector operation may fail without persisted chunk vectors.

## Goals / Non-Goals

**Goals:**
- Keep all cache access initiated by the embedding provider on its active event loop.
- Preserve best-effort cache behavior: read failure is a miss and write failure does not fail embedding.
- Make cache failures observable without logging embedding content or credentials.

**Non-Goals:**
- Do not change text embedding providers, model identities, vector-store selection, or database schema.
- Do not repair vectors for documents that already failed.
- Do not treat the invalid vision-embedding credential as part of this code change.

## Decisions

### Native asynchronous cache interface

Add asynchronous cache read/write operations and have `cached_embed()` await them directly. The synchronous compatibility methods remain for callers outside an async embedding flow, but the production embedding path will not call them.

Creating a replacement thread with `asyncio.to_thread()` is rejected because the same asyncpg pool would still cross an event-loop boundary. Creating a second pool per cache call is rejected because it increases connection pressure and loses the application lifecycle ownership.

### Best-effort degradation with diagnostics

Cache read exceptions return a cache miss; cache write exceptions are ignored after a warning that identifies only the operation and exception type. The raw embedding call and NanoVectorDB upsert remain able to complete.

### Loop-affinity regression tests

Tests use a pool double that asserts all `acquire`, read, and write operations run on the test's active loop. This directly prevents reintroducing a thread-local event loop in the asynchronous provider path.

## Risks / Trade-offs

- [Cache I/O adds awaited work to embedding] -> Cache failures degrade immediately; normal cache hits avoid provider calls.
- [Other LightRAG PostgreSQL operations can still fail independently] -> Preserve Worker failure propagation and validate with a new cloud upload after deployment.
- [Synchronous cache consumers may exist outside this path] -> Retain their compatibility behavior and confine the change to the async wrapper.

## Migration Plan

1. Deploy the rebuilt app image.
2. Re-upload a small text-only PDF; existing failed documents remain unchanged.
3. Verify `vdb_chunks.json` has chunk entries and automatic tagging succeeds.
4. Roll back by restoring the prior image; no data migration is required.

## Open Questions

- Whether a distinct LightRAG PostgreSQL issue remains after this fix must be determined by the cloud upload acceptance test.
