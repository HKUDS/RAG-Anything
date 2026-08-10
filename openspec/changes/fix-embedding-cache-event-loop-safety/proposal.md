## Why

The worker's asynchronous text-embedding path currently performs PostgreSQL cache I/O in a new thread and event loop while reusing an asyncpg pool owned by the worker loop. This can close or corrupt in-flight connections, leaving parsed documents without persisted text vectors and causing automatic tagging to fail.

## What Changes

- Make text embedding-cache reads and writes asynchronous when invoked by the asynchronous embedding provider.
- Keep all asyncpg pool operations on the embedding caller's active event loop.
- Preserve cache failures as cache misses or no-ops, while recording concise diagnostic warnings.
- Add regression coverage for cache hits, misses, and cache I/O failures using a loop-bound pool double.

## Capabilities

### New Capabilities
- `embedding-cache-event-loop-safety`: Ensures asynchronous embedding cache access never crosses event-loop or thread boundaries when using asyncpg.

### Modified Capabilities
- `chunk-embedding-resilience`: Embedding cache failures must degrade to direct provider calls without preventing the remaining chunk vectors from being generated.

## Impact

- Affected code: `raganything/embedding/embedding_cache.py` and focused tests.
- No database migration, API contract, or persisted data rewrite.
- Existing failed uploads are not repaired automatically; documents must be reprocessed after deployment.
