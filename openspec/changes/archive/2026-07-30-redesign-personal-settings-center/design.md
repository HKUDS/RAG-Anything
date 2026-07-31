## Context

The repository currently contains a global settings API and page, an in-progress preferences page, a vision-model router/service, and mutable environment/configuration paths inside upload and retrieval flows. The working tree is intentionally dirty, including `App.jsx`, `KnowledgeDetailPage.jsx`, `api.js`, vision routes, and model services; this change must layer on those edits without reverting them. RBAC v2 already defines `settings:*` and `kb:*` permissions. Existing installations may have only SQLite auth state today, but production configuration state must be PostgreSQL-backed and cross-worker durable.

## Goals / Non-Goals

**Goals:**

- Resolve one immutable effective setting set at the request/task boundary using the stated precedence order.
- Keep model credentials and provider endpoints server-only while exposing a sanitized model choice catalog.
- Make user, KB-vector-space, and platform-policy ownership explicit; enforce platform constraints without silently changing a choice.
- Make queued/retried work reproducible through durable snapshots and make concurrent retrieval state independent.
- Deliver a responsive personal settings center, an RBAC-protected platform page, compatibility redirects/proxies, audit events, and testable migrations.

**Non-Goals:**

- Adding providers beyond the configured OpenAI-compatible and existing Doubao multimodal embedding adapters.
- Moving a KB's visual vector space into personal settings or mixing profiles in one active vector index.
- Returning credentials, hostnames, private catalog fields, or passwords from any API, audit payload, or UI.
- Replacing existing unrelated in-progress frontend, ODL, or vision work.

## Decisions

### A typed catalog separates public profiles from deployment secrets

`ModelProfile` has a private parsed representation and a public DTO. A catalog service composes `MODEL_PROFILE_CATALOG_FILE`, the existing vision catalog, and legacy environment variables, then validates adapter availability. Only public fields are serialized. The older vision endpoint delegates to this service during one compatibility version.

`MODEL_PROFILE_CATALOG_FILE` takes precedence when set; the service supplements compatible visual profiles from `VISION_MODEL_CATALOG_FILE`/`config/vision_models.json` and then legacy deployment variables. The catalog is a read-only deployment mount, and `.env` is excluded from Docker build context. Parse/configuration errors are explicit unavailable/503 states, never a reason to disclose private catalog fields.

Alternative: passing provider configuration through the UI was rejected because it would disclose deployment credentials and prevents centralized policy.

### Effective settings resolve in one pure service

Use immutable dataclasses/Pydantic models for `ResolvedUserSettings`, `ModelSelection`, `ProcessingTaskSettings`, `RetrievalOptions`, and `QuotaOptions`. Each field is resolved in this exact order: platform hard limit, index compatibility rule, request-scoped explicit selection, sparse user override, agent/KB configuration, platform default, and legacy environment fallback. The resolver returns effective values, sources from that finite set, constraint adjustments, a stable fingerprint, and a revision. KB visual embeddings are KB-owned and cannot be overridden by a user/agent; unknown/forbidden profiles are validation errors and unavailable or incompatible profiles/dimensions/fingerprints produce explicit 503/compatibility failures rather than fallback.

Alternative: mutating `os.environ`, a shared RAG config, or shared search engine fields per request was rejected because it races across users and workers.

### PostgreSQL owns durable settings, policies, snapshots, and leases

Introduce typed repositories and migrations for `user_settings`, `platform_settings`, `task_settings_snapshots`, and quota leases. `user_settings` stores schema version, JSONB sparse overrides, revision, and timestamp; PATCH uses an expected revision under a conditional update and returns `409 revision_conflict` on mismatch. Null section values delete that override and restore inheritance. The existing VLM preference is migrated once. Development fallback, if already needed for local tests, is explicitly non-production only.

All enqueue paths (single, batch, folder, content, URL, retry, and reprocess) atomically associate a complete PostgreSQL snapshot with the queue/job before it becomes runnable. If snapshot creation or lookup fails, execution fails rather than running with live configuration. Workers resolve by task id from the snapshot only, never task argv, environment, or current settings. PostgreSQL lease rows use owner/task identifiers, expiry, heartbeat, and atomic acquisition while provider/worker hard limits remain outer constraints.

### KB vector configuration is profile-bound and reindexed side-by-side

The active visual-embedding profile belongs to KB metadata. Vector records include profile identity, fingerprint, and dimension; NanoVectorDB files are scoped by profile. Changing a populated index requires explicit `reindex=true`, creates one lease/heartbeat-governed active job per KB, and atomically changes active metadata only on success. Queries continue reading the old active index until switch; ingestion/reprocessing returns a conflict during reindex. Success invalidates caches before old derived index cleanup; failure cleans only target data.

Alternative: selecting visual embeddings per user was rejected because a shared KB would mix incompatible vector spaces.

### Retrieval and cache keys carry resolved scope

`HybridSearchEngine.search(options)` receives a local `RetrievalOptions` value rather than changing `_enabled_channels`. The known high-risk mutations in folder/content/URL uploads, processing worker, admin runtime settings, and shared retrieval state are replaced by local immutable inputs or snapshot-scoped instances. `runtime_settings` becomes a startup-only legacy seed, not runtime persistence. BM25 indexes use workspace, corpus revision, tokenizer, k1, and b in their key; bounded LRU eviction removes only the matching derived index. Query, LLM, and instance-cache keys include workspace, permissions, content version, and settings fingerprint.

### Frontend separates personal and administrative surfaces

`/preferences` uses independently loaded/saved sections so model-catalog failure does not block theme or account security. It shows stored/effective/source/constraint state and supports restore inheritance. `/admin/platform` is permission-gated with `settings:read`/`settings:write`; it contains policy values, never secrets. `/settings` remains a one-version authenticated redirect, selecting platform management for `settings:read` holders and preferences otherwise. Deprecated `/api/settings` emits a header during migration and loses mutations before its read endpoint is removed.

### Auditing records stable identifiers, not secrets

Audit events record actor, section, profile id, KB, revision, and outcome for profile/settings/account/platform/vector lifecycle changes. Passwords, API keys, providers' hostnames, and raw settings secrets are excluded by construction.

## Risks / Trade-offs

- [PostgreSQL is unavailable in a test/development setup] → repositories expose clear availability failures; production cannot use a process-memory fallback, while tests use an isolated repository fixture.
- [Existing dirty files overlap the migration] → inspect diffs before every edit, use narrow patches, and add adjacent modules where possible.
- [Background workers still receive legacy arguments] → introduce snapshot-aware adapters with compatibility shims, then route all enqueue/retry paths through the snapshot creator before removing legacy mutation.
- [Large profile reindex consumes storage and time] → reserve target storage under platform limits, retain the old index during work, and clean target data on failure.
- [Policy changes race with PATCH] → use revisions/conditional writes and report both stored and constrained effective values.
- [Responsive settings UI becomes coupled to model availability] → isolate section queries and error boundaries; account/theme/password flows have independent clients.

## Migration Plan

1. Add catalog/config parsing and typed PostgreSQL schema/migrations without altering legacy request behavior.
2. Migrate existing VLM preference rows, seed platform defaults from `runtime_settings.json` (including `max_async:7`), and verify sanitized DTOs/OpenAPI routes.
3. Introduce resolver, snapshots, cache/index keys, and worker adapters; run dual-path compatibility tests before removing per-request global mutation.
4. Add KB vision-setting/reindex lifecycle and profile-scoped vector persistence.
5. Ship `/preferences` and `/admin/platform`, redirect `/settings`, migrate frontend callers, and deprecate the legacy API.
6. Disable legacy settings writes/resets, monitor audit/route smoke tests, then remove legacy reads in the following compatibility release.

Rollback keeps the prior active vector index and legacy read proxy available; database migrations are additive and policy/user rows can be ignored by the previous release. Never roll back or discard unrelated working-tree changes.

## Open Questions

- Confirm exact additive migration numbers after inspecting the existing migration sequence; production migrations, not runtime `CREATE TABLE IF NOT EXISTS`, are the source of truth.
- Extend the existing untracked vision router/service/catalog and current processing-task/retry persistence instead of replacing them; confirm exact compatibility adapters during implementation.
