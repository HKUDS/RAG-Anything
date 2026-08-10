## Context

The repository has a Python backend, a Vite frontend, PostgreSQL migrations, a multi-stage default Docker image, and a separate OpenDataLoader image target. Existing workflows are fragmented: backend tests install editable extras without `uv.lock`, frontend validation is absent, the lint job commits fixes back to PRs, and project-summary quality is advisory. The existing OpenDataLoader workflow mixes default validation with optional Java/OpenDataLoader work. The CI owner is limited to workflows, pre-commit configuration, CI fixtures/scripts, necessary manifests/locks, and CI/release documentation; Dockerfile, compose, migrations, server, RBAC, and business code are prohibited.

## Goals / Non-Goals

**Goals:**

- Make stable named checks fail closed on PRs to `main`, pushes to `main`, and package-release preparation.
- Prove clean-checkout reproducibility for the locked Python and Node validation paths.
- Validate the actual committed PostgreSQL migration chain on fresh and repeated execution, then exercise a self-contained authenticated API/CRUD path against PostgreSQL.
- Build and start only the default image, validate `/api/health`, and capture default-image supply-chain evidence.
- Keep all CI checks read-only with respect to the source branch and make failure thresholds explicit.
- Keep OpenDataLoader separate, explicit, and fail-closed within its own release/legal workflow.

**Non-Goals:**

- Changing application behavior, migrations, Dockerfile, compose, nginx, or release credentials.
- Claiming the existing Dockerfile's `requirements.txt`/`npm install` path is fully lockfile-reproducible while those prohibited files remain unchanged.
- Enabling GitHub branch protection from repository YAML or scanning private release secrets from pull-request contexts.
- Making the OpenDataLoader workflow a prerequisite for the default delivery chain.

## Decisions

### Stable reusable release gate

Create a reusable gate workflow called by PR/main CI and by package-release preparation. It will expose stable required job names: `backend-quality`, `frontend-unit-build`, `lint-and-static`, `postgres-migrations-api`, `default-container-smoke`, `supply-chain-security`, and `project-summary-quality`. Each has `contents: read`, a bounded timeout, concurrency that cancels obsolete runs for the same PR/ref, and no `continue-on-error` for a release condition.

This avoids separate drift between PR and publishing checks. Compatibility matrices, if retained, are informational jobs with distinct names; they do not rename the required checks. A single monolithic job was rejected because failures and expected runtimes need to remain diagnosable.

### Locked, read-only code quality and frontend validation

Python validation will use a pinned uv runtime, `uv lock --locked`, and `uv sync --frozen`; an import audit will decide whether minimal CI-only declarations must be added to `pyproject.toml` and regenerated into `uv.lock`. Node 20 will use `npm ci --ignore-scripts`, then separate unit-test and production-build commands. Static checks will run `ruff check` and `ruff format --check` without `--fix`; any required frontend formatter/linter will be a locked project dependency and script, not an unpinned `npx` download.

The lint workflow will remove the auto-commit action and no CI command may write changes. Reusing the current pre-commit invocation was rejected because its Ruff hooks contain fix flags and can mutate the checkout even after the commit action is removed.

### PostgreSQL migration and API harness

The gate will use `postgres:16-alpine` as a service with a health check and an isolated CI-only migration runner. The runner receives an explicit ephemeral `DATABASE_URL`, runs the committed migration order using `psql -v ON_ERROR_STOP=1` on a fresh database, repeats the same chain against that database, and asserts selected schema/index facts. It must not call `scripts/pg_setup.py`, write `.env`, or treat an "already exists" message as success.

An integration fixture then uses the real PostgreSQL service and a unique test prefix/schema to exercise a self-contained API contract plus database CRUD, and cleans up in `finally`. Missing service readiness, fresh migration failure, repeat failure, API failure, and cleanup failure are separately reported. Existing local/mock-only tests remain part of backend coverage but cannot substitute for this gate.

### Default container smoke and supply chain

The container job builds `Dockerfile` target `default`, starts it using isolated non-secret CI configuration, polls `/api/health` until a bounded startup deadline, and emits sanitized container logs only on failure. It must not build or run the OpenDataLoader target. It will generate a CycloneDX SBOM for the default image, upload it as an artifact, and scan that same image.

Supply-chain validation checks the committed Python and Node locks, scans the repository for secrets with redaction, scans production dependency graphs, and scans the default image. Any secret finding, lock mismatch, missing SBOM, tool error, or HIGH/CRITICAL production dependency or image vulnerability blocks the gate. Suppressions are prohibited unless documented in version control with an issue reference and expiry; unfixable findings are reported, not silently hidden. Third-party actions and tools are version-pinned and run with minimal permissions.

### OpenDataLoader remains opt-in

Move default lock/container checks out of `opendataloader-release-gate.yml`. Its Java/OpenDataLoader install, opt-in image, redistribution evidence, legal approval, and specialized SBOM behavior remain fail-closed when explicitly dispatched, but it does not run as a default PR required check. This preserves evidence rigor without making Java or an optional parser dependency block ordinary delivery.

### Summary check and required-check policy

`project-summary-quality` becomes a blocking gate and package-release prerequisite. The coordinator recommends setting the stable `project-summary-quality` check as a PR required status check immediately after the workflow lands and is green on `main`; the CI/release document will list the exact required checks and record that GitHub branch-protection binding is a separate administrator action. The change must not claim that repository setting is complete until it is externally verified.

## Risks / Trade-offs

- [Two dependency sources in Docker] -> Lock checks prove CI install paths, not the Dockerfile's current `requirements.txt`/`npm install` resolution; document this as residual release risk and do not modify prohibited Docker inputs.
- [Historic migrations are non-idempotent] -> Fresh/repeat runs fail closed and surface the exact migration; migrations are out of scope, so the outcome is a real release blocker, not an ignored exception.
- [External audit databases or registries are unavailable] -> Classify as CI infrastructure failure and fail closed; never convert to a warning or blind retry.
- [App startup has external provider dependencies] -> Use the smallest non-secret isolated config/fixture that can prove the health and API contract; report an unmet self-contained requirement rather than masking it with mocks.
- [Branch protection is external state] -> Document the required admin action and keep workflow-level failures blocking until that binding is verified.
- [Security tools create noisy findings] -> Restrict blocking scope to production dependency graphs and HIGH/CRITICAL severities, with expiring reviewed suppressions only.
