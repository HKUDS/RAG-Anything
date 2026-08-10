## 1. Data Model And Authorization Core

- [x] 1.1 Add migration and manifest checksum for `kb_access_grants.access_level`, backfill existing rows from target `kb:write`, and verify constraints/indexes are idempotent.
- [x] 1.2 Add `kb:manage` and central read/operate/manage scope dependencies; preserve ownership, super-admin, and dept-admin own-or-granted boundaries.
- [x] 1.3 Implement transactional member repository operations (list, candidate search, upsert, revoke) with rank/state/redundancy checks, audit records, row locks, and session-generation invalidation.
- [x] 1.4 Implement display-name repository update with `expected_updated_at` optimistic locking and audit-safe metadata preservation.

## 2. API And Route Enforcement

- [x] 2.1 Return per-KB `rename` and `manage_members` capabilities from `/api/kb/list` and add metadata/member/candidate/upsert/revoke endpoints.
- [x] 2.2 Replace every KB content mutation's scope guard with operate-plus-`kb:write` enforcement, including upload, documents/chunks/tags, graph, retry/reprocess, ingestion, and vision settings routes.
- [x] 2.3 Reject legacy `allowed_kbs` in admin user create/update payloads and remove the batch-grant behavior from the admin user route.
- [x] 2.4 Add API error mapping for stale metadata, invalid candidates, redundant grants, and concurrent member changes; ensure all mutations are audited.

## 3. Frontend Experience

- [x] 3.1 Add API wrappers for KB metadata/member/candidate operations and invalidate KB list/detail caches after successful mutations.
- [x] 3.2 Add capability-gated KB card menu and SideDrawer basic-information editor with read-only internal identity, optimistic conflict handling, and unsaved-state preservation.
- [x] 3.3 Add SideDrawer members-and-permissions view with constrained search, owner pinning/non-removability, effective access labels, 44px controls, and mobile full-width layout.
- [x] 3.4 Remove `allowed_kbs` controls and submission from `EditUserModal`, including a clear migration message to KB member management.

## 4. Verification And Documentation

- [x] 4.1 Add migration fresh/upgrade/repeat/failure and access-level backfill tests.
- [x] 4.2 Add five-role backend matrix tests for list/read/write/manage, rename, member mutation, direct API denial, session invalidation, audit, and stable KB identity.
- [x] 4.3 Add frontend unit/source-contract tests for capability gating, drawer state/focus/cache invalidation, mobile-safe controls, and legacy API removal.
- [x] 4.4 Run focused pytest, frontend `test:unit`, build, `py_compile`, OpenSpec strict, migration status, and `git diff --check`; record unverified production/browser boundaries.
- [x] 4.5 Update `PROJECT_SUMMARY.md` current facts and append the dated task record without secrets or generated artifacts.
