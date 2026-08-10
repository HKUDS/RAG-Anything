## Why

Knowledge-base cards can show the same update time after a full metadata save. The
legacy `kb_metadata` trigger treats every row in that save as changed, while the
list response presents that metadata timestamp as the card update time. This
makes the list misleading and loses useful historical ordering.

## What Changes

- Return an explicit `last_updated_at` for each knowledge base in the list API
  and use it for the card display and time sort; keep
  `last_content_updated_at` as a compatibility alias.
- Preserve per-KB `updated_at` semantics when a complete metadata snapshot is
  persisted, so creating one knowledge base cannot refresh every existing KB.
- Add a new manifest-managed migration that verifies the legacy metadata
  timestamp trigger is absent and performs a best-effort, per-KB historical
  timestamp recovery from durable upload and corpus-mutation records.
- Record the recovery limitations and required production migration checks in
  the project summary.

## Capabilities

### New Capabilities

- `knowledge-base-update-time`: Expose and preserve a reliable per-KB update
  timestamp for list cards and ordering.

### Modified Capabilities

- `knowledge-base-stats`: Knowledge-base list data gains a per-resource update
  timestamp with stable fallback behavior.

## Impact

- Backend: KB metadata repository, knowledge list router, and list timestamp
  tests.
- Frontend: knowledge-base card rendering and KB time sorting.
- Database: one appended PostgreSQL migration and the migration manifest.
- Operations: release preflight must confirm migration `026` and the new
  recovery migration have been applied before reporting corrected live data.
