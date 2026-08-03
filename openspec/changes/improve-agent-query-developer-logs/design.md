## Context

`QueryTiming` already records content-free phase durations and Prometheus
metrics, while agent query execution emits additional retrieval, media, and
model logs from several modules.  These records are useful to machines but a
developer must manually join them by `trace_id` to understand one request.

## Goals / Non-Goals

**Goals:**
- Emit one stable, compact, trace-correlated terminal summary at query close.
- Preserve the existing timing records and metrics for dashboards and tooling.
- Represent phase outcomes in execution order, including concurrent retrieval
  channels, without accepting request content as API input.
- Keep summary logging available for successful, error, timeout, and cancelled
  terminal paths.

**Non-Goals:**
- Change query, retrieval, deadline, media, citation, persistence, HTTP, SSE,
  frontend, or database behavior.
- Log raw queries, rewrites, prompts, answers, source text, document paths,
  credentials, user identifiers, or model payloads.
- Replace the existing detailed diagnostic logs.

## Decisions

1. Extend `QueryTiming` with an in-memory ordered phase ledger and emit an
   additive `QUERY_JOURNEY` line from `total()`.  The timing object already
   owns the trace id and terminal lifecycle, so it provides one close point for
   all agent modes and early returns.  A router-side summary would duplicate
   lifecycle handling and miss failures before the event generator starts.

2. Record only bounded labels already accepted by `QueryTiming` plus elapsed
   milliseconds.  The summary format will use a fixed field sequence and an
   ordered `stages` value such as
   `retrieval/vector{outcome=ok,cache_status=na,elapsed_ms=484.0}`.  Stages will sort
   by a fixed lifecycle order and retrieval channel order (`bm25`, `vector`,
   `graph`, aggregate), with insertion order only as a final tie-breaker.
   This is readable in a terminal and deterministic for parsers.  Raw logger
   messages are not aggregated because they can contain content and paths.

3. Add a small set of optional, bounded journey attributes for execution mode
   and media result only where the router already has them.  These attributes
   are counts or allow-listed mode/source values, never knowledge-base names or
   request content.  The initial implementation may omit attributes that are
   not uniformly available across RAG, CoT, and ReAct paths.

4. Make the terminal transition idempotent in `QueryTiming`: the first `total()`
   call closes outstanding phases, emits the existing total metric/log, and
   emits one journey summary; later calls return the original duration without
   a second terminal record.  Test phase ordering, repeated terminal calls,
   concurrent-channel representation, cross-trace isolation, and privacy.
   Existing endpoint tests continue to protect deadline and media behavior.

## Risks / Trade-offs

- [Additional terminal line per query increases log volume] -> The summary is
  one compact line and replaces no existing operational records.
- [A future caller records arbitrary labels] -> Reuse existing bounded label
  normalization before ledger insertion and never serialize exception data.
- [Concurrent retrieval completion changes summary order] -> Sort completed
  stage entries by the fixed lifecycle/channel order before formatting.
- [Timing summaries lack contextual text] -> Detailed component logs remain
  available and share the trace id where applicable; the summary identifies
  the stage to inspect.
- [Early setup failures lack some stages] -> Emit the completed ledger and
  terminal outcome rather than requiring all stages.

## Migration Plan

1. Deploy with the additive summary line enabled at the existing log level.
2. Developers use `QUERY_JOURNEY trace_id=...` to find a terminal overview,
   then inspect matching detailed logs only when required.
3. Rollback is code-only: remove the summary emission.  No persisted data,
   configuration, or external contract changes are involved.

## Open Questions

- None.  The summary intentionally remains limited to timing-owned bounded
  labels until a separate, privacy-reviewed requirement needs additional data.
