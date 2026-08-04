## Context

The agent router currently resolves an immutable user settings snapshot, then
passes that snapshot to `get_kb`.  The task-bound branch intentionally bypasses
the KB cache, initializes all LightRAG storage and derived retrieval state, and
is finalized when the SSE generator exits.  It protects profile isolation but
makes every interactive question pay for graph, HNSW, and BM25 initialization.
The scoped BM25 path also resolves data before RRF's channel timeout wrappers.

The existing cached KB object is heavyweight and its LRU eviction directly
finalizes storage.  Therefore simply restoring `get_kb(name)` is insufficient:
an in-flight streaming request must prevent the cached instance it uses from
being finalized.  The project already has immutable retrieval options and VLM
`ContextVar` dispatch; those provide the isolation pattern for text LLM calls.

## Goals / Non-Goals

**Goals:**

- Reuse a compatible query core without sharing a caller's LLM, VLM, permission
  scope, retrieval options, or result-cache namespace.
- Bound all RRF preparation and channels with one monotonic deadline and return
  usable-channel fusion rather than waiting for an unbounded slow operation.
- Make phase latency and cache lifecycle measurable without exposing diagnostic
  data through SSE or the UI.
- Preserve ingestion/retry task snapshots, media ownership checks, query API,
  SSE schema, retrieval channels, citations, and image recall.

**Non-Goals:**

- No model replacement, schema migration, frontend change, Top K reduction, or
  automatic change to `EMBEDDING_CACHE_ENABLED`.
- No cross-process KB cache, automatic provider retry policy, or rework of
  LightRAG's persistence format.

## Decisions

### Lease-aware cached query cores

`acquire_query_kb()` is the cached interactive acquisition path and returns an
async lease.  `KBInstanceKey` captures KB name, workspace, corpus revision,
storage/index compatibility identity, and active visual-embedding profile
fingerprint; it excludes user, LLM, VLM, permission, and settings fingerprints.
The cache publishes an instance only after `_ensure_lightrag_initialized()`
succeeds, and concurrent same-key acquisition is single-flight.  A corpus or
index change replaces the cache entry; an old entry is marked retiring and
finalized only after its last lease releases.  LRU eviction follows the same
rule.  Failed initialization is never published.

This evolves the existing `KBCache` rather than introducing a second cache, so
administrator reload, deletion, and shutdown keep one lifecycle authority.
`set_default_workspace()` is removed from the interactive fast path; if a
LightRAG initialization path still requires it after validation, it is held
inside the per-key initialization critical section and the initialized storage
workspace is verified before publishing.
Task-bound `get_kb(..., task_settings=...)` remains for ingestion and retries.

### Explicit request context plus contextual LLM proxy

The router creates a frozen internal `QueryExecutionContext` containing a
trace ID, KB/workspace, captured corpus revision, RBAC-derived permission
scope, settings and canonical retrieval fingerprints, immutable retrieval
options, selected LLM/VLM profile fingerprints, cache scope, and an absolute
retrieval deadline.  It contains no prompt, answer, secret, or host.  It passes
retrieval values explicitly to all local query paths.  A shared instance uses
text-LLM and VLM proxies selected through `ContextVar`, because LightRAG model
callbacks cannot receive that context directly.  The context is set before
query work and reset in `finally`; absence or stale profile fingerprints fails
closed.

The LLM, VLM, and result-cache namespaces include profile, workspace, corpus
revision, permission scope, settings, and canonical retrieval fingerprints.
Only derived, user-neutral BM25 state uses the query-core cache.  The pipeline
must not read query scope from an instance attribute.

### RRF deadline and BM25 single flight

The Agent sets one absolute monotonic retrieval deadline using
`AGENT_RETRIEVAL_TIMEOUT` with a 12-second default.  The RRF engine receives
the deadline through its internal execution context.  BM25 cache lookup,
PostgreSQL work, chunk reads, and index build are one BM25 channel coroutine,
started alongside vector and graph channels.  Every awaited operation receives
only the remaining time.

Revision-bearing options construct `BM25IndexKey` before accessing PostgreSQL;
a cache hit makes no PG request.  Same-key misses share an owned build task.
A caller timing out detaches from, rather than cancels, the build; successful
completion atomically publishes the index and failures remove the task.  RRF
fuses completed channel results at the deadline.  This preserves all channels
while bounding their effect on response latency.

### Media reader reuse and observability

Controlled-media resolution accepts an optional authorized active chunk reader.
The Agent supplies the reader from its leased KB; legacy callers without a
reader retain the existing compatible acquisition path.

`QueryTiming` uses `time.perf_counter()` and structured events.  Metrics use
only phase/channel/outcome/cache-status labels.  Trace IDs are log fields, not
metric labels, and prompts, answers, paths, users, and credentials are never
recorded.

## Risks / Trade-offs

- [A retiring instance can temporarily exceed the cache capacity] → retain it
  only while leased, then run normal LRU convergence on release.
- [A non-cancellable provider/worker can outlive a request] → detach and
  observe its task, enforce the caller deadline, and count late work.
- [A stale corpus revision can reuse a derived index] → use the authoritative
  revision supplied by the existing KB metadata/update service and invalidate
  affected entries on corpus mutation.
- [ContextVar propagation can be lost in spawned tasks] → create child tasks
  while the request context is active and add concurrent isolation tests.
- [Twelve seconds can exclude a late channel] → preserve successful channels,
  retain the configurable channel budget, and report the specific timeout.

## Migration Plan

1. Add timing and lifecycle counters, then run focused tests and the
   deterministic benchmark on an isolated backend port.
2. Deploy the code with `AGENT_RETRIEVAL_TIMEOUT=12` where no explicit value is
   configured; confirm health, cache hit, phase latency, and detached-task
   counters before normal traffic.
3. Roll back by restoring the prior application revision and restarting the
   backend.  No database or derived-data rollback is required.

## Open Questions

None.  Existing embedding-cache behavior remains explicitly outside this
change until its namespace and worker-lifecycle audit is complete.
