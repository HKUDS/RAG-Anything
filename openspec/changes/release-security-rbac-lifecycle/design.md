## Context

Authentication is PostgreSQL-backed, but both `auth.py` and `pg_auth_repo.py` independently create fallback JWT secrets and a random default-administrator password at import time.  `init_db()` additionally stores fallback JWT secrets in `settings`, then prints bootstrap account state.  The public registration endpoint creates student accounts without authentication.  `get_current_user()` re-reads account activity and token revocation, but it has no durable account-wide session epoch; a role change, disable, or deletion therefore cannot atomically invalidate every unexpired access and refresh token.  The repository currently hard-deletes users and the final active `super_admin` can be removed or demoted.

This change is limited to authentication/RBAC owners and relevant UI/tests.  `migrations/` is a serial resource owned outside this task; the data contract below is a handoff requirement, not authorization to edit a migration.  Existing unrelated worktree changes, deployment files, `server.py`, and business logic remain out of scope.

## Goals / Non-Goals

**Goals:**

- Reject incomplete production configuration before serving requests without ever logging a supplied or generated secret.
- Make public registration closed by default and impossible to enable in production.
- Preserve user/audit history through archive-first lifecycle operations and invalidate all account sessions immediately after security-sensitive changes.
- Enforce five-level role hierarchy and the final-active-super-admin invariant in the repository transaction.
- Verify authorization behavior across HTTP, streaming, WebSocket, controlled media, and user-owned resources for every role.

**Non-Goals:**

- Rotating deployed secrets or automatically migrating legacy database rows without an approved migration owner.
- Editing container, proxy, CI, startup assembly, or model/query business logic.
- Replacing existing resource-specific ownership checks.  This change verifies and repairs authorization only when an actual defect is found and coordinated.

## Decisions

### Explicit environment validation is the source of production secrets

Define one pure configuration-validation path in the auth service/repository boundary.  In production it MUST require nonblank `JWT_SECRET`, `JWT_REFRESH_SECRET`, `DEFAULT_ADMIN_PASSWORD`, PostgreSQL connectivity configuration, and credentials for each enabled model provider; it returns a redacted list of variable *names* and fails before authentication initialization completes.  Development/test fallback is permitted only behind an explicit non-production mode and never writes or prints a generated value.

Environment-managed secrets replace the database-persistence fallback.  Persisting generated keys offered cross-worker consistency but makes an incomplete deployment silently boot and turns a configuration mistake into durable credential state.  Explicitly supplied shared secrets are operationally clearer, auditable, and fail closed.

### Public registration is an opt-in non-production capability

`ALLOW_PUBLIC_REGISTRATION` defaults to false.  The router returns a non-enumerating 404/403 when closed and must reject an attempt to enable it while production mode is active.  The normal client removes the register route/link/call; any retained developer-only page must surface the closure state rather than imply account creation is available.

Making registration a standard feature would preserve an internet-facing account-creation surface with no verified tenant/admission workflow.  Administrator creation already applies RBAC, password policy, and audit controls.

### Session generation provides immediate account-wide revocation

Add a monotonic `session_generation` to each user.  Access and refresh JWTs carry this generation.  `get_current_user`, refresh, and WebSocket authentication load the current user and reject tokens whose generation differs; SSE and controlled-media paths reuse these dependencies.  Disable/archive, password replacement, and role changes each increment the generation in the same repository transaction as the state change.  Existing per-token and refresh-family revocations remain for logout and replay handling.

An account-wide generation avoids storing one database revocation row for every issued access token.  It works for all current transports because they authenticate before accepting or serving data.  Existing already-issued tokens lacking the claim are rejected after the migration cutover.

### Lifecycle is archive-first, preserving identity and audit references

`DELETE /admin/users/{id}` becomes a non-destructive archive operation (or an explicit archive endpoint if compatibility needs it); archived accounts retain immutable identity, role-at-event data, lifecycle timestamps/reason, audit linkage, and inaccessible sessions.  List/detail responses expose lifecycle state only to authorized administrators.  Physical purge is deliberately not included: it needs data-retention policy and referential-integrity review.

### Super-admin quorum and hierarchy are repository invariants

Repository mutations lock the target user and calculate the count of active, non-archived `super_admin` accounts inside the same transaction.  Any operation that archives, disables, or changes the role of the last such account fails.  The same mutation validates `can_assign_role(actor, target)` for create, role update, restore, and status changes.  HTTP handlers and UI preflight provide clearer feedback, but cannot be the enforcement layer.

The current self-demotion check only protects one route and does not prevent another super administrator, concurrent requests, or direct service calls from breaking the invariant.

### UI mirrors but does not replace server authority

The admin UI filters role options using live actor-role capability, replaces destructive delete copy/actions with archive/disable controls, hides closed registration, and reloads authentication state after a 401 caused by session invalidation.  It never infers authorization solely from role labels; direct API calls are covered by backend tests.

## Risks / Trade-offs

- [Strict production configuration can block an existing deployment] → report only missing variable names, document required configuration, and validate in preflight before rollout.
- [Session-generation schema change requires a migration] → do not edit migrations in this owner scope; hand off an idempotent migration contract and gate release on its deployment.
- [Archive changes DELETE semantics] → return a documented archive outcome and preserve a compatibility route only if its behavior is explicitly tested.
- [Concurrent super-admin lifecycle changes] → use row/role locking and a single transaction; add concurrency-oriented repository tests.
- [Long-lived streaming connections may remain open after a later lifecycle change] → authentication is guaranteed before connection/stream creation; revalidation at safe SSE/WS boundaries is tested and any inability to interrupt an already-blocked upstream stream remains an explicit residual risk.

## Migration Plan

1. Assign a separate migration owner for an idempotent PostgreSQL migration that adds `session_generation NOT NULL DEFAULT 0`, lifecycle fields such as `archived_at`, `archived_by`, and optional archive reason, plus indexes for active-role quorum queries.  The migration MUST not remove users or audit rows.
2. Deploy schema first, then fail-closed application configuration with all required secrets supplied through the production secret manager.
3. Deploy application code.  On the first version that enforces `session_generation`, legacy tokens without the claim are rejected and users authenticate again.
4. Verify bootstrap admin presence, five-role matrix, lifecycle/archive, token rejection, SSE/WS/media authorization, and sanitized logs.
5. Roll back application code only while the schema remains additive.  Do not roll back by restoring generated secrets or unarchiving accounts automatically; perform explicit administrator recovery with audit evidence.

## Open Questions

- Which environment configuration positively identifies production (`APP_ENV`, `ENVIRONMENT`, or an established deployment setting)?  The implementation must reuse the existing authoritative setting rather than create an ambiguous second flag.
- Which model credentials are mandatory for a given enabled provider profile, and where is the provider-enablement registry defined?  The startup validator must use that registry without printing values.
- Does the deployment contract permit an explicit archive endpoint alongside compatible `DELETE`, or must `DELETE` become archive-only?
- What retention/approval policy will govern eventual physical purge of archived accounts?
