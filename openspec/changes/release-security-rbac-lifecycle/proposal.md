## Why

The current authentication path can generate and print administrator credentials, generate or persist JWT signing keys when production configuration is incomplete, and exposes public registration.  Account deletion is hard-delete, role/lifecycle changes do not invalidate every existing session, and the last active `super_admin` is not protected transactionally.  These are release blockers because they allow unrecoverable lockout, credential disclosure, or privilege persistence outside the intended five-level RBAC model.

## What Changes

- Make production startup fail closed when required JWT, default bootstrap administrator, PostgreSQL, or enabled model-provider credentials are absent or blank.  Remove random secret/password generation, database secret persistence, and all secret-bearing startup output.
- **BREAKING** Disable public registration by default.  Retain it only behind an explicit non-production configuration switch; production cannot enable it.  The client registration route and calls are removed from the normal product flow.
- Introduce an auditable account lifecycle: administrator-created accounts, disable/archive as the default destructive action, protected restore rules, and token/session invalidation on disable, archive, password reset, or security-sensitive role change.
- Protect the final active `super_admin` against deletion, disable/archive, or demotion.  Enforce this atomically in the repository transaction, rather than only in HTTP handlers.
- Enforce five-level role hierarchy for every user create/update operation.  No actor may assign, restore, or retain a target role more privileged than their own; the only bootstrap exception is an explicitly configured initial super administrator.
- Regress HTTP, SSE, WebSocket, controlled-media, knowledge-base, agent, and conversation access across all five roles, including revoked/disabled sessions and cross-user resource isolation.

## Capabilities

### New Capabilities

- `production-secret-configuration`: production configuration validation that is fail-closed and never exposes secret values.
- `account-lifecycle-protection`: archival lifecycle, active-super-admin quorum protection, audit trail, and account-wide session invalidation.
- `five-role-transport-regression`: five-role authorization regression coverage for HTTP, SSE, WebSocket, controlled media, and user-owned resources.

### Modified Capabilities

- `auth-hardening`: authentication startup and public-registration requirements become production-safe and fail-closed.
- `admin-user-crud`: user management changes from hard deletion to lifecycle operations with super-admin quorum constraints.
- `rbac-authorization`: five-level role assignment restrictions are enforced across service, repository, and API boundaries.
- `jwt-secret-persistence`: environment-managed JWT credentials replace generated or database-persisted signing secrets.
- `server-session-invalidation`: account lifecycle and privilege changes invalidate access and refresh sessions immediately.

## Impact

Primary code owners are `raganything/permissions.py`, `raganything/dependencies.py`, `raganything/routers/auth.py`, `raganything/services/auth.py`, and `raganything/services/pg_auth_repo.py`, plus the administrator user-management/authentication UI and focused backend/frontend tests.  The expected implementation requires a separately owned PostgreSQL migration to add durable account session-generation and lifecycle metadata; this change will not edit `migrations/` without that owner being explicitly assigned.

The work intentionally excludes deployment files, server assembly, CI, and knowledge/upload/query business logic.  Any discovered authorization defect outside the owner scope will be reported for coordination before it is changed.
