## 1. Migration Contract And Production Configuration

- [x] 1.1 Identify the authoritative production-environment and enabled-provider configuration sources; implement a redacted validator for required secret, PostgreSQL, and enabled-provider credential names.
- [x] 1.2 Remove runtime generation, database persistence, and stdout/stderr logging of JWT secrets and bootstrap administrator passwords; preserve only explicitly permitted non-production test behavior.
- [x] 1.3 Obtain a separately owned additive PostgreSQL migration for `users.session_generation`, archival metadata, and active-super-admin quorum indexes; review its idempotence, backfill, and rollback contract without editing `migrations/` in this change owner scope.
- [x] 1.4 Add startup tests for each missing production requirement and assert captured diagnostics contain variable names only, never secret values.

## 2. Registration And Account Lifecycle

- [x] 2.1 Close `POST /auth/register` by default, add an explicit non-production opt-in guard, and remove normal registration navigation/client calls.
- [x] 2.2 Implement archive/disable lifecycle operations in the repository and router, preserving identity/audit references and returning lifecycle state only to authorized user-management views.
- [x] 2.3 Bind access and refresh tokens to account session generation; reject stale generation in HTTP dependencies, refresh, WebSocket authentication, SSE, and token-based controlled-media paths.
- [x] 2.4 Increment session generation atomically for archive, disable, password replacement, and role change, retaining token JTI/family revocation for logout/replay.
- [x] 2.5 Add repository-transaction protection for the final active non-archived `super_admin`, including concurrent archive/disable/demotion paths.

## 3. Five-Level RBAC And User Management UI

- [x] 3.1 Enforce `can_assign_role()` in every create, update, restore, and lifecycle service/repository path; retain only the explicit bootstrap-super-admin exception.
- [x] 3.2 Update administrator user-management UI to filter unauthorized target roles, use archive/disable rather than hard-delete affordances, and recover safely when its own session is revoked.
- [x] 3.3 Remove or gate registration routes and links so an unauthenticated user cannot discover a normal account-creation flow when public registration is closed.
- [x] 3.4 Add focused component/unit tests for role controls, lifecycle state, and closed-registration UI behavior.

## 4. Five-Role Security Regression

- [x] 4.1 Add API/repository tests for public-registration denial, role escalation denial, archive/disable/demotion of the last `super_admin`, audit metadata, and immediate access/refresh-token rejection.
- [x] 4.2 Add a five-role HTTP matrix covering user management, knowledge-base, agent, and conversation authorization plus cross-user isolation.
- [x] 4.3 Add SSE/WebSocket tests that reject missing, revoked, disabled, archived, and generation-stale credentials before acceptance or protected event delivery.
- [x] 4.4 Add controlled-media tests that reject revoked/disabled/archive-stale credentials and retain existing KB visibility checks.
- [x] 4.5 Run focused Python and frontend suites, static compilation, diff checks, and an authenticated runtime matrix when PostgreSQL/provider prerequisites are available; record environment gaps precisely.

## 5. Handoff And Release Evidence

- [x] 5.1 Produce migration-owner handoff: additive schema contract, deployment ordering, rollback limits, and any unresolved data-retention decision.
- [x] 5.2 Produce security handoff: exact validation results, secret-leak inspection, residual long-lived-stream risk, and a `PROJECT_SUMMARY.md` increment for the coordinator to merge.
