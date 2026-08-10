## Why

On the production host, PDF text embedding and graph extraction complete, but
the NanoVectorDB chunk file remains empty after the Worker exits. The document
is then incorrectly treated as graph-complete with zero searchable vectors,
causing automatic tagging to fail and leaving unusable document residue.

## What Changes

- Make Worker finalization verify that each in-memory NanoVectorDB store was
  persisted successfully while the knowledge-base processing lock is held.
- Treat a skipped or failed chunk-vector persistence callback as a Worker
  failure instead of reporting document processing complete.
- Prevent the server process's pre-Worker KB cache from overwriting the
  Worker-owned NanoVectorDB snapshot when the cache is invalidated afterward.
- Add regression coverage for stale cross-process update flags and failed VDB
  persistence callbacks.

## Capabilities

### New Capabilities

- `nanovectordb-worker-persistence`: Ensures successful Worker ingestion has
  durable chunk vectors before completion is reported.

### Modified Capabilities

- `chunk-embedding-resilience`: A completed document requires durable chunk
  vector persistence, not only successful embedding and graph extraction.

## Impact

- Affected code: `raganything/raganything.py`,
  `raganything/services/kb_service.py`, Worker lifecycle tests, and focused
  persistence tests.
- No public API, database migration, or model-provider contract changes.
- Existing zero-vector documents are not repaired automatically and require
  re-upload or explicit reprocessing after deployment.
