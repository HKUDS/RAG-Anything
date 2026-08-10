## 1. Reproducible default gate

- [x] 1.1 Inventory direct Python imports and current package metadata; add only CI-required declarations to `pyproject.toml` and regenerate `uv.lock` when the locked install cannot run without them. (2026-08-04: `asyncpg` and locked Ruff declarations added; `uv lock --locked` passes.)
- [x] 1.2 Add a reusable default release-gate workflow and PR/main caller with stable job names, least-privilege permissions, bounded timeouts, cancellation policy, and no advisory release conditions. (2026-08-04: reusable gate and caller are wired with seven stable jobs and no inherited PR secrets.)
- [x] 1.3 Implement `backend-quality` with a pinned uv runtime, `uv lock --locked`, `uv sync --frozen`, and the scoped backend pytest command from a clean checkout. (2026-08-04: workflow steps are present; clean GitHub-runner execution remains external evidence.)
- [x] 1.4 Implement `frontend-unit-build` with pinned Node 20, `npm ci --ignore-scripts`, `npm run test:unit`, and `npm run build` as independently diagnosable steps. (2026-08-04: workflow steps are present; local production install was blocked by Windows esbuild file locking.)

## 2. Read-only static validation

- [x] 2.1 Replace the lint workflow's branch-writing auto-commit action with a failure-only workflow using current action versions and stable check names. (2026-08-04: linting workflow is manual read-only diagnostics; reusable gate is blocking.)
- [x] 2.2 Change the CI static-check entrypoint so Ruff and formatting checks never receive fix flags or modify the checkout; preserve local autofix ergonomics only where it cannot be invoked by CI. (2026-08-04: CI uses `ruff check`, `ruff format --check`, and `git diff --exit-code`; pre-commit no longer passes `--fix`.)
- [ ] 2.3 Add any necessary locked frontend lint/format tooling and scripts, without floating `npx` installs, and include them in the static gate.

## 3. PostgreSQL migration and API evidence

- [x] 3.1 Establish a CI-only, explicit complete migration manifest/order after inspecting the committed migration dependencies; do not reuse `scripts/pg_setup.py`, write `.env`, or silently accept SQL errors. (2026-08-04: workflow invokes the canonical `scripts/pg_migration_runner.py` and its checked-in manifest.)
- [x] 3.2 Add a PostgreSQL 16 service-backed runner that creates isolated CI state, runs every committed migration with `ON_ERROR_STOP=1` on a fresh database, then repeats the same chain against it and asserts selected schema/index facts. (2026-08-04: PostgreSQL 16 service, dynamic manifest count, no-op verification, and schema/index assertions wired.)
- [x] 3.3 Add a self-cleaning real-PostgreSQL integration fixture that exercises `test_pg_crud_e2e.py` equivalence and a self-contained authenticated/permission API contract without mocks, SQLite fallback, external models, or silent skips. (2026-08-04: migration fixture plus `tests/test_pg_authenticated_api_integration.py` added; CI supplies `DATABASE_URL` explicitly.)
- [x] 3.4 Wire the migration and API fixture into `postgres-migrations-api` with sanitized failed-job diagnostics and phase-specific failures for service readiness, fresh migration, repeat migration, API integration, and cleanup. (2026-08-04: named workflow phases and sanitized status-on-failure step wired.)

## 4. Default container and supply chain

- [ ] 4.1 Add `default-container-smoke` to build only Docker target `default`, run it with isolated non-secret runtime inputs, poll `/api/health` to a bounded deadline, and collect sanitized logs on failure.
- [x] 4.2 Add a fail-closed secret scan with redacted output and a version-controlled, expiring reviewed exception policy. (2026-08-04: added `.github/security/ci-exceptions.json` and fail-closed expiry/shape validation.)
- [x] 4.3 Add lock-resolved Python and Node SCA plus a default-image vulnerability scan; fail on every production HIGH or CRITICAL finding, scanner error, or timeout. (2026-08-04: production Python export is scanned by Trivy, frontend uses `npm audit --omit=dev`, and the exact default image is scanned at HIGH/CRITICAL.)
- [x] 4.4 Generate and upload a CycloneDX SBOM for the exact default image; fail the gate when generation or artifact collection fails. (2026-08-04: Syft generates CycloneDX JSON for the tagged default image and upload requires the artifact.)
- [ ] 4.5 Pin new third-party actions and security tools to immutable revisions or explicitly approved fixed releases with minimal workflow permissions.

## 5. Gate separation and release governance

- [x] 5.1 Remove default lock, install, and default-image validation from the OpenDataLoader workflow; retain Java/OpenDataLoader/Marker and redistribution/legal evidence as an explicitly dispatched, fail-closed opt-in workflow. (2026-08-04: manual workflow retains only opt-in parser/Java/Marker and opt-in image/legal evidence.)
- [x] 5.2 Convert `project-summary-quality` from advisory to blocking and make it a package-release prerequisite with no `continue-on-error` path. (2026-08-04: blocking job is in the reusable gate and release build needs the gate; manual diagnostics are separate.)
- [x] 5.3 Document required check names, expected runtime ranges, failure taxonomy, retry boundaries, security thresholds, exception process, OpenDataLoader opt-in trigger, and the residual Docker dependency-lock limitation. (2026-08-04: documented in `docs/release-ci-gates.md`.)
- [ ] 5.4 Submit the coordinator recommendation to bind `project-summary-quality` and the other stable default checks in GitHub branch protection after the first green `main` run; record the external administrator result without claiming it is configured before verification.

## 6. Verification and handoff

- [ ] 6.1 Validate workflow syntax and run every feasible gate from a clean checkout or equivalent CI runner; record exact passing commands and environment-only blockers separately from source failures. (2026-08-04: YAML parsing, OpenSpec, Ruff, py_compile, security-policy and migration tests pass locally; actionlint/GitHub Actions and clean uv install remain unavailable.)
- [ ] 6.2 Verify repeated PostgreSQL migration execution, default-container health behavior, and that OpenDataLoader is not invoked by the default workflow.
- [ ] 6.3 Produce the required-check list, observed job durations, categorized failure evidence, rollback steps, and a PROJECT_SUMMARY increment for the summary owner; do not edit `PROJECT_SUMMARY.md` under this change's owner restriction.
