## Context

`/kb/list` currently derives the card timestamp from `kb_metadata.updated_at`.
Before migration 026, a trigger refreshed that value for every row affected by
a full metadata upsert. The repository now avoids explicitly updating conflict
rows, but a deployed database can retain the trigger and already-corrupted
timestamps cannot be reconstructed from metadata alone.

## Goals / Non-Goals

**Goals:**

- Define one explicit list field for the card's per-KB update time.
- Keep the existing list field available to old clients.
- Prevent the legacy trigger from continuing to corrupt timestamps.
- Recover only clearly suspect duplicate timestamp groups with durable
  historical evidence.

**Non-Goals:**

- Reconstruct an exact audit trail for historical KB configuration changes.
- Change authorization, cache TTLs, upload processing, or document timestamps.
- Alter historical migration 026.

## Decisions

- `last_updated_at` is the canonical list-card field and represents the
  persisted KB metadata `updated_at`; `last_content_updated_at` remains an
  equal-valued alias for compatibility. This honors the card's generic
  "更新" label and lets targeted metadata and corpus writes remain visible.
- The frontend chooses `last_updated_at`, then the compatibility alias, then
  `created`, for both display and time sorting. A shared utility owns the
  fallback order so the two views cannot diverge.
- A new migration is appended after migration 030 and added to the manifest.
  It idempotently removes the legacy trigger, then backfills only duplicate
  `updated_at` groups. For each affected KB, it uses the newest available
  terminal upload timestamp or committed corpus-mutation timestamp, falling
  back to `created_at`. This is a best-effort recovery, not an audit claim.
- Existing full-snapshot upserts retain their current conflict clause, which
  does not write `created_at` or `updated_at`. Targeted operations continue to
  update only their own KB timestamp.

## Risks / Trade-offs

- [Historical metadata-only changes cannot be inferred] -> Limit the backfill
  to duplicate groups and document the approximation in migration comments and
  release evidence.
- [A legitimate simultaneous bulk change can resemble a polluted group] ->
  require a read-only preview and backup acknowledgement before production
  apply; the migration is limited to groups with supporting prior evidence.
- [A database has not applied migration 026] -> the new migration repeats the
  idempotent trigger removal and release verification checks both migration IDs.

## Migration Plan

1. Create a logical backup and run the migration runner status/plan commands.
2. Preview duplicate KB timestamps and their proposed inferred values.
3. Apply the manifest-managed migration with backup acknowledgement.
4. Verify migration history, trigger absence, distinct list timestamps, and
   `/kb/list` responses before declaring the production issue resolved.

## Open Questions

None. The user selected generic KB update semantics and best-effort historical
recovery.
