## 1. Baseline and observability

- [x] 1.1 Add an internal monotonic query timing helper and bounded structured metrics without changing HTTP or SSE payloads.
- [x] 1.2 Instrument settings/quota, query-core acquisition, RRF/BM25 phases, media, LLM, persistence, and total completion without logging sensitive content.

## 2. Lease-aware query core

- [x] 2.1 Introduce revision- and compatibility-keyed query-core acquisition with single-flight initialization and lease accounting.
- [x] 2.2 Make cache replacement, LRU eviction, KB deletion, reload, and shutdown retire leased cores before one-time finalization.
- [x] 2.3 Remove interactive `task_settings` instance construction and per-stream finalization while retaining uncached ingestion/retry factories.
- [x] 2.4 Replace shared instance query scope/model binding with immutable request execution context and contextual text-LLM/VLM dispatch.

## 3. Bounded retrieval and media reuse

- [x] 3.1 Propagate one absolute retrieval deadline through standard, retrieval-only, tag, CoT, and agentic retrieval paths.
- [x] 3.2 Run BM25 preparation as a deadline-bounded concurrent RRF channel with revision-first cache lookup and detached single-flight builds.
- [x] 3.3 Reuse the active leased chunk reader for controlled media validation while preserving the fail-closed legacy fallback.

## 4. Tests and benchmarks

- [x] 4.1 Add lifecycle and isolation tests for concurrent profiles, options, KB workspaces, revision replacement, eviction, cancellation, and task-bound ingestion.
- [x] 4.2 Add RRF/BM25 deadline, revision-hit, single-flight, and late-channel tests.
- [x] 4.3 Add media-reader reuse, timing privacy, and SSE cleanup regression tests.
- [x] 4.4 Add deterministic cold/warm latency benchmark coverage and document real-provider smoke criteria.

## 5. Verification and closeout

- [x] 5.1 Run OpenSpec strict validation, focused suites, relevant backend suite, static checks, and benchmark; record environment-limited checks accurately.
- [x] 5.2 Perform controlled backend restart and cold/warm smoke validation when the configured providers are reachable.
- [x] 5.3 Update `PROJECT_SUMMARY.md`, validate its size/record limits, and leave the change ready for review/archive.
