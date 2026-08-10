## Why

Upload and parsing controls currently live primarily in personal settings, even though parsing is a property of a knowledge-base corpus and its future indexing tasks. This makes it difficult to keep one knowledge base consistent while preserving a personal fallback and a deliberate one-upload override.

## What Changes

- Add sparse knowledge-base ingestion defaults stored in the existing `kb_metadata.extra` JSONB value with optimistic revision handling.
- Add authenticated GET/PUT knowledge-base ingestion-settings endpoints with effective values, sources, constraints, and capability-aware writes.
- Resolve new upload tasks as platform/environment defaults, personal defaults, knowledge-base defaults, request overrides, then compatibility and hard limits.
- Show KB defaults and one-upload overrides in the knowledge-base detail page while retaining personal upload defaults as fallback preferences.
- Keep `/admin/platform` isolated from KB and personal settings, and preserve five-role capability projection and existing KB access scope.

## Capabilities

### New Capabilities

- `knowledge-base-ingestion-settings`: Persist, resolve, expose, and apply knowledge-base-scoped ingestion defaults for new upload tasks.

### Modified Capabilities

- `personal-settings-center`: Clarify ingestion controls as personal defaults and preserve capability-derived visibility while KB settings take precedence for a configured KB.

## Impact

- Backend: user-settings resolution, KB metadata persistence, knowledge router upload snapshot creation, new KB ingestion-settings API, and focused RBAC/precedence tests.
- Frontend: PreferencesPage copy, KnowledgeDetailPage KB settings and upload override summary, API client methods, and five-role UI contract tests.
- No database migration is required; existing task snapshots remain immutable and existing documents are not reprocessed automatically.
