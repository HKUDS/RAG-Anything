# Release Security RBAC Lifecycle Handoff

## Migration Contract

Migration `028_account_lifecycle_session_generation.sql` is additive and is
listed as sequence 31 in `migrations/migration_manifest.json`. It adds:

- `users.session_generation BIGINT NOT NULL DEFAULT 0` for account-wide JWT
  invalidation;
- `archived_at`, `archived_by`, and `archive_reason` for retained lifecycle
  history; and
- a partial active-super-admin index for quorum checks.

Deploy the migration through the manifest runner after the normal backup
acknowledgement, then deploy the application with externally managed
production configuration. The default backfills existing accounts to generation
zero. Access and refresh tokens without the `sg` claim are intentionally
rejected after cutover, requiring reauthentication.

The migration does not delete data. Application rollback may leave the
additive columns and index in place; do not roll back by restoring generated
credentials or automatically unarchiving accounts. A physical purge policy for
archived accounts remains intentionally undecided and requires data-retention
approval.

## Security Evidence

- Production validation requires nonblank `JWT_SECRET`, `JWT_REFRESH_SECRET`,
  `DEFAULT_ADMIN_PASSWORD`, PostgreSQL configuration, and enabled model-profile
  credential variable names. Diagnostics contain names only.
- Public registration is closed unless explicitly enabled outside production;
  production rejects the opt-in.
- Archive-first lifecycle operations retain identity/audit references and
  increment account session generation. Repository transactions protect the
  final active `super_admin` against archive, disable, and demotion.
- HTTP, controlled media, refresh, SSE, and WebSocket authentication validate
  account state and session generation. Established SSE and WebSocket event
  delivery also rechecks the session before each event.

Validated on 2026-08-04:

```text
132 passed: auth, lifecycle, RBAC, migration-runner, role-assignment, user,
            knowledge-base regression suites
22 passed: controlled-media suite
127 passed: frontend unit suite
py_compile: passed
git diff --check: passed
```

The frontend production build is not verified because this workspace has no
`vite` executable. No authenticated PostgreSQL deployment, enabled-provider
runtime probe, browser E2E, or live SSE/WebSocket smoke was run because the
required production database/provider credentials are not available in this
workspace. These are release-environment acceptance gates, not source-test
passes.

## PROJECT_SUMMARY.md Increment For Coordinator

Add a short in-progress entry for `release-security-rbac-lifecycle`: production
auth configuration now fails closed without required externally managed JWT,
bootstrap-admin, PostgreSQL, or enabled-model credentials; public registration
is closed by default; migration 028 adds account session generation and
archive metadata; lifecycle changes invalidate sessions and protect the final
active `super_admin`; HTTP/SSE/WebSocket/media source regressions pass. State
that PostgreSQL/provider/browser runtime acceptance and the frontend production
build remain pending, and do not include values of any credentials.
