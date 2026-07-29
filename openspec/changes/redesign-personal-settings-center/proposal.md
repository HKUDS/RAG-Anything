## Why

The current global settings surface and mutable process-level configuration cannot safely express per-user model, ingestion, retrieval, and runtime preferences. They also make visual-model selection, shared knowledge-base vector compatibility, and cross-worker resource limits difficult to operate securely.

This change separates personal choices, knowledge-base vector-space choices, and administrator-controlled platform policy while retaining one-version compatibility for the existing settings and visual-model APIs.

## What Changes

- Add a sanitized, server-owned model-profile catalog for configured LLM, VLM, and embedding models, plus profile discovery and administrator probe endpoints.
- Add PostgreSQL-backed, revisioned user settings with explicit effective-value sources, constraints, immutable runtime resolution, and task snapshots.
- Add platform-policy persistence and an administrator-only `/admin/platform` interface for defaults, allow-lists, and resource hard limits; credentials and provider hosts remain deployment-only.
- Add knowledge-base visual-vector settings with profile-aware storage and guarded, atomic reindex switching.
- Replace the legacy settings page with the personal `/preferences` center, retain a permission-aware `/settings` redirect, and migrate existing callers from global settings APIs.
- **BREAKING** Stop treating mutable `os.environ`, shared RAG configuration, and shared retrieval-engine fields as request-scoped state; request and worker execution use resolved immutable settings instead.
- Preserve existing saved VLM preferences and legacy behavior for users without a new settings row; mark legacy settings APIs deprecated before removing write paths.

## Capabilities

### New Capabilities

- `model-profile-catalog`: Sanitized server-side model catalog, availability validation, compatibility projection, and administrator probes.
- `user-settings-resolution`: Revisioned per-user settings, effective-value resolution, constraints, auditing, and immutable execution snapshots.
- `platform-settings-policy`: Typed platform defaults, allow-lists, resource hard limits, and administrator management APIs/UI.
- `knowledge-base-vision-profiles`: KB-owned visual embedding selection, profile-aware vector storage, and safe reindex switching.
- `personal-settings-center`: Personal settings and account-management UI with isolated section lifecycle and a legacy-route redirect.

### Modified Capabilities

- `multimodal-settings-rebuild`: Replace global settings-cache rebuild semantics with per-user task snapshots and KB-owned visual-vector reindex behavior.
- `rbac-authorization`: Apply `settings:read` and `settings:write` permissions to platform and model-probe administration while preserving KB write authorization for vision settings.
- `adaptive-concurrency`: Resolve user concurrency within platform/worker/provider limits and enforce it through durable cross-worker leases.

## Impact

Affected systems include FastAPI routers and services for auth, knowledge, vision, model resolution, search, upload workers and caching; PostgreSQL migrations/repositories; vector storage metadata; frontend routes, navigation, auth context, settings API client and pages; Docker build context and model-catalog deployment configuration. The implementation requires focused backend and frontend tests, OpenAPI route smoke checks, and browser validation at the required breakpoints.
