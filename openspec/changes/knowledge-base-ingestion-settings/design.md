## Context

The application already stores personal task settings in PostgreSQL, persists KB metadata in `kb_metadata.extra` JSONB, and writes immutable `task_settings_snapshots` before upload workers run. Upload routes already accept a small set of request-level overrides. The missing layer is a durable KB-specific ingestion default that can be resolved without changing existing KB visibility or the five-role permission model.

## Goals / Non-Goals

**Goals:**

- Store only explicit KB ingestion overrides and preserve inheritance from platform and personal defaults.
- Resolve KB defaults consistently for file, batch, folder, URL, and pasted-content uploads.
- Expose effective values and their source, with optimistic concurrency and server-side validation.
- Keep student pages read-only and derive all settings/upload controls from capabilities.

**Non-Goals:**

- No new database table or migration.
- No automatic reprocessing of existing documents.
- No change to KB ownership, `allowed_kbs`, platform settings, model permissions, or historical task snapshots.
- No change to the generic `resource_settings` precedence used by other callers.

## Decisions

- **Use `kb_metadata.extra.ingestion_defaults`:** The existing JSONB round-trip already preserves unknown metadata and is used by KB-scoped settings. Store only explicitly set ingestion fields plus a monotonic `revision`; empty/null fields are removed so personal/platform changes continue to inherit.
- **Use a dedicated resolver layer:** Add a `knowledge_base_settings` argument to settings resolution and apply it after stored personal settings but before request overrides. Do not pass KB values through the existing `resource_settings` argument because its current order intentionally lets personal settings win.
- **Use the existing KB access guard plus `kb:write`:** Read settings only after `verify_kb_access` and `kb:read`/authenticated access; write settings with the same owner-or-KB-write guard used by KB visual settings. This preserves department-admin scope and does not infer global access from role names.
- **Use optimistic revision updates:** GET returns the KB ingestion revision; PUT requires `expected_revision`. The update reads and writes the JSONB metadata under a transaction and returns 409 on a stale revision.
- **Keep request override compatibility:** Existing query parameters remain accepted. The upload snapshot helper merges the KB layer and explicit request values before persisting the immutable snapshot, so retries never re-read mutable defaults.
- **Progressive disclosure in the UI:** Preferences retains a concise “上传默认偏好” section. Knowledge detail shows the KB effective source and exposes long-lived defaults to `kb:write` users; the upload panel exposes only per-upload adjustments and a reset-to-effective action.

## Risks / Trade-offs

- [Concurrent metadata writers] → Update only the ingestion sub-object inside a transaction and reject stale revisions; preserve unrelated `extra` keys.
- [A KB override can surprise a user] → Display source and effective values beside controls and make request overrides visibly “仅本次上传”.
- [Students may receive unnecessary settings requests] → Gate catalog and write-control loading on `kb:write`; keep backend capability checks authoritative.
- [Legacy snapshots lack the new layer] → Continue reading their stored settings unchanged; only newly enqueued tasks use current KB defaults.

## Migration Plan

1. Deploy code that reads missing `ingestion_defaults` as empty and writes the new JSONB sub-object only when configured.
2. Verify API, role matrix, precedence, and upload snapshot tests.
3. Roll back by disabling the new UI/API callers; existing metadata and snapshots remain compatible because the new JSONB key is additive.
