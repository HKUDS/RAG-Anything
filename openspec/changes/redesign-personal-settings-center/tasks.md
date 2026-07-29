## 1. Discovery, contracts, and safe persistence

- [ ] 1.1 Inspect all overlapping dirty files and existing vision catalog/router behavior before each change; preserve user edits with narrow patches.
- [ ] 1.2 Add typed public/private `ModelProfile` catalog composition for configured LLM, VLM, and embedding adapters, including secret-free public serialization and availability validation.
- [ ] 1.3 Add additive PostgreSQL migrations and typed repositories for user settings, platform policy, task snapshots, quota leases, and any missing profile-aware KB/vector metadata.
- [ ] 1.4 Migrate existing VLM preferences and seed platform policy from legacy runtime settings, retaining `max_async:7`; make any in-memory compatibility path unavailable in production.

## 2. Settings resolution and backend APIs

- [ ] 2.1 Implement immutable resolved-settings models and one precedence resolver returning effective values, sources, constraints, revision, and fingerprint.
- [ ] 2.2 Implement revisioned user settings GET/PATCH/options APIs, inheritance reset, 409 conflicts, model/profile availability errors, and non-secret audit events.
- [ ] 2.3 Implement catalog listing and permission-protected probe APIs, and proxy the legacy vision-model API with deprecation metadata.
- [ ] 2.4 Implement RBAC-protected platform policy read/write APIs with typed validation, revisions, audit, and no credential/host exposure.
- [ ] 2.5 Extend authenticated account APIs for masked email, atomic password-verified profile changes, normalized password changes, refreshed user data, and secret-free audit behavior.

## 3. Runtime isolation, quotas, and KB vector switching

- [ ] 3.1 Replace request-time global environment/config/shared-instance mutation in folder/content/url upload, worker, and retry paths with captured immutable task settings snapshots.
- [ ] 3.2 Pass local retrieval options into hybrid search; scope query/LLM/instance cache keys and bounded BM25 indexes by workspace, permissions/content version, and settings fingerprint.
- [ ] 3.3 Enforce effective personal concurrency with PostgreSQL leases, heartbeat/expiry, bounded interactive waits/429, queued ingestion, and outer provider/worker limits.
- [ ] 3.4 Implement RBAC-protected KB vision settings APIs, profile-aware vector records/files, explicit reindex tasks, query continuity, atomic activation, failure cleanup, and lifecycle audits.
- [ ] 3.5 Add OpenAPI/route smoke coverage for the vision router and ensure deployment excludes `.env` while supporting a read-only model catalog mount.

## 4. Frontend information architecture and migration

- [ ] 4.1 Extend the API client and auth context for new catalog, personal settings, platform policy, account-profile, and compatibility responses without regressing existing dirty changes.
- [ ] 4.2 Complete `/preferences` with independently resilient AI, ingestion, retrieval, runtime, appearance, account, and password sections; show stored/effective/source/constraint state and inheritance controls.
- [ ] 4.3 Add responsive retrieval presets/custom controls, bounded model choice/status/technical disclosure, and upload-scope messaging at desktop and mobile breakpoints.
- [ ] 4.4 Add permission-aware `/admin/platform`, remove legacy settings-page/navigation/metadata usage, and retain the versioned `/settings` redirect.
- [ ] 4.5 Migrate UploadPage and KnowledgeDetailPage off `api.getSettings()` and disable legacy settings mutations before deleting the legacy read proxy in the later compatibility release.

## 5. Verification and acceptance

- [ ] 5.1 Add backend tests for catalog secrecy/RBAC/unavailable profiles, settings revision/inheritance/limits, account audit, and legacy compatibility headers.
- [ ] 5.2 Add isolation tests for two-user concurrent search, task snapshot/retry/restart, durable leases, scoped BM25 caches, and no request-time environment mutation.
- [ ] 5.3 Add KB vision tests for permissions, empty/populated switching, same/cross-dimension reindex, atomic success/failure rollback, and profile-scoped storage.
- [ ] 5.4 Add frontend unit tests for route redirects, independent section failures, effective/source/constraint presentation, retrieval custom controls, and platform permissions; run `npm run test:unit` and `npm run build` with at least the existing 42-test baseline.
- [ ] 5.5 Run focused and relevant full backend tests, OpenAPI smoke checks, and browser acceptance at 1440, 1024, 768, and 390 px in light/dark, keyboard, and error states; start the dev service and report its address.
