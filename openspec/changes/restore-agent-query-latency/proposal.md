## Why

An agent query recorded at 192.31 seconds spent approximately 161.5 seconds
before answer generation.  Interactive requests currently supply task-bound
settings to `get_kb`, which deliberately creates and destroys a complete
LightRAG/graph/HNSW/BM25 instance for every question; scoped BM25 preparation
also runs before RRF channel timeouts apply.  This regresses ordinary knowledge
base questions from their prior 20--30 second range without improving answer
quality.

## What Changes

- Reuse a lease-protected, user-neutral query core for compatible KB corpus
  revisions while preserving request-specific LLM/VLM, permissions, retrieval
  options, and result-cache namespaces.
- Add request-scoped execution context and contextual text-LLM dispatch so a
  shared query core cannot leak a profile or user setting between concurrent
  requests.
- Make BM25 preparation a bounded RRF channel, use revision-keyed single-flight
  derived indexes, and enforce one monotonic retrieval deadline across all
  preparation and channel work.
- Reuse the active query core's chunk reader for controlled legacy-media
  validation rather than initializing another KB instance.
- Add internal phase timing, bounded-cardinality metrics, and deterministic
  latency benchmarks.  The HTTP and SSE contracts, database schema, retrieval
  channels, Top K values, citations, and image recall remain unchanged.
- Keep the existing embedding cache disabled; this change does not make a
  production configuration change to `EMBEDDING_CACHE_ENABLED`.

## Capabilities

### New Capabilities

- `agent-query-latency`: Bounded, observable agent-query execution with a
  reusable retrieval core and request-isolated execution context.

### Modified Capabilities

- `rrf-hybrid-search`: RRF preparation and all channels share a total deadline
  and fuse successful channels when another channel is late.
- `kb-cache-invalidation`: Cached query cores are revision- and lease-aware,
  rather than being finalized while a request still uses them.

## Impact

The change affects the agent query router, KB lifecycle service, model-profile
dispatch, query pipeline, hybrid search, controlled-media validation, metrics,
and focused backend tests.  It introduces no endpoint, SSE payload, migration,
or frontend change.  Upload and retry workers retain their immutable task
snapshot and uncached lifecycle.
