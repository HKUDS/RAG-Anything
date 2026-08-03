## Why

Developer diagnosis of an agent query currently requires correlating flat timing
records with retrieval, media, model, and persistence logs by hand.  A concise,
content-free request summary makes the execution path and its bottleneck clear
without exposing query or document data.

## What Changes

- Add a developer-facing query journey summary emitted once when an interactive
  agent query completes, fails, times out, or is cancelled.
- Accumulate phase outcomes and durations from existing request timing calls so
  the summary identifies retrieval channels, media result, model progress, and
  persistence in request order.
- Keep existing `QUERY_TIMING` records, Prometheus metrics, HTTP/SSE payloads,
  retrieval behavior, media security checks, and response limits unchanged.
- Add focused tests for summary readability, terminal outcome coverage, and
  content-free logging.
- Update the project summary after implementation and verification.

## Capabilities

### New Capabilities
- `agent-query-developer-logging`: Content-free, trace-correlated terminal
  summaries for interactive agent query execution.

### Modified Capabilities
- None.

## Impact

- Affected code: `raganything/services/query_timing.py`, agent query endpoint
  integration, focused timing tests, and `PROJECT_SUMMARY.md`.
- No API, SSE, database schema, dependency, retrieval, citation, or frontend
  contract change.
