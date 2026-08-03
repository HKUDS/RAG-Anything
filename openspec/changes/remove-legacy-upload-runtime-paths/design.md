## Context

Queued uploads already persist a complete settings snapshot and the production
worker creates its RAG instance through `kb_service.create_rag`. The worker
also retains a local factory and accepts five configuration arguments that are
not authoritative.

## Goals / Non-Goals

**Goals:**
- Make the durable task snapshot the only ingestion configuration source.
- Keep worker process lifecycle, model preflight, and error semantics intact.

**Non-Goals:**
- No migration, upload API change, model-profile change, or retry schema
  cleanup is included.

## Decisions

- Remove the local worker factory rather than forwarding to it. The service
  factory owns profile fingerprints, cache scope, and preflight providers.
- Remove `--strategy` and `--enable-*` from parent command construction and
  worker argparse. The task id remains because it locates the snapshot.
- Retain legacy queue/retry columns as transport compatibility fields, but do
  not consume them for worker configuration.

## Risks / Trade-offs

- [Tests import the old factory] → move equivalent assertions to the service
  factory and assert the worker passes the immutable task settings.
- [Historic queued data contains legacy fields] → keep consumer signatures
  compatible while ignoring non-authoritative configuration.
