## Why

The upload worker retains a second RAG factory and accepts command-line settings
that are immediately replaced by the durable task snapshot. Maintaining both
paths allows configuration drift and obscures the snapshot-only contract.

## What Changes

- Remove the worker-local RAG factory and make the service factory the only
  factory used for queued uploads.
- Remove worker command-line configuration that is derived from task settings.
- Keep the task id as the configuration authority and retain explicit failure
  for absent or invalid snapshots.
- Move test coverage from the retired worker factory to the service factory and
  subprocess boundary.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-settings-resolution`: queued workers use only their persisted task
  snapshot for ingestion configuration.

## Impact

`process_worker.py`, `raganything/services/kb_service.py`, upload retry code,
and focused upload/worker tests change. HTTP APIs, database schema, and RBAC do
not change.
