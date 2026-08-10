## 1. Persistent Scope

- [x] 1.1 Add the additive `kb_access_grants` migration and append it to the reviewed manifest.
- [x] 1.2 Add transactional PostgreSQL grant read/replace helpers with target and KB validation.

## 2. Authorization Projection

- [x] 2.1 Project grants in sanitized authenticated users and invalidate the target session after a grant change.
- [x] 2.2 Apply owner-or-grant scope consistently to KB access and KB listing without bypassing role permissions.

## 3. Administrator Experience

- [x] 3.1 Extend the authorized user editor with accessible KB grant selection and save/reset states.
- [x] 3.2 Preserve five-role navigation and KB-page write gates after a scope grant or revocation.

## 4. Verification

- [ ] 4.1 Add backend coverage for persistence, atomic validation, session invalidation, five-role owner/granted/ungranted access, and direct API denial.
- [ ] 4.2 Add frontend coverage for administrator-only grant controls and role-aware KB behavior.
- [x] 4.3 Repair the migration-runner applied-status display for empty failure diagnostics and cover it with a regression test.
- [ ] 4.4 Run targeted tests, OpenSpec strict validation, diff checks, migration status, and authenticated PostgreSQL/browser acceptance.

## 5. Project Record

- [ ] 5.1 Update `PROJECT_SUMMARY.md` with persisted-grant behavior, migration evidence, validation results, and any remaining runtime limitation.
