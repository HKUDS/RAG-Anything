## Why

The repository currently has separate advisory or incomplete checks: backend CI installs an unlocked dependency set, frontend unit/build commands are absent from CI, lint can rewrite and commit a pull request, and the project-summary check is explicitly non-blocking. Release confidence therefore depends on local tooling and does not prove that PostgreSQL migrations, the default container, or the supply chain work from a clean checkout.

This change establishes one reproducible, fail-closed default delivery gate for pull requests, the main branch, and package release preparation while keeping the OpenDataLoader legal/runtime gate explicitly opt-in.

## What Changes

- Add a blocking default CI gate for pull requests targeting `main` and pushes to `main`.
- Run locked backend installation and pytest, frontend `npm ci` plus `test:unit`, frontend production build, and read-only formatting/static checks.
- Add a PostgreSQL service-backed CI fixture that runs the committed migration chain on a fresh database and repeats it, then executes self-contained API/CRUD integration coverage.
- Build and smoke-test only the default Docker target, including the `/api/health` startup contract; generate an image SBOM and fail on the defined image vulnerability threshold.
- Enforce lockfile freshness, secret scanning, dependency SCA, SBOM generation, and image scanning with documented blocking thresholds and sanitized artifacts.
- Remove lint auto-commit behavior and prevent CI hooks from applying fixes or modifying pull-request branches.
- Convert the project-summary quality workflow to a strict blocking check and document the exact branch-protection required-check configuration.
- Keep OpenDataLoader redistribution, Java, opt-in image, and legal evidence checks in a separate manually invoked workflow that is not a default required check.
- Add CI documentation covering required checks, expected durations, failure classes, retry boundaries, and the coordinator's summary increment.

## Capabilities

### New Capabilities

- `release-ci-gates`: Reproducible, fail-closed CI and release validation for code quality, tests, PostgreSQL migrations/API integration, the default container, and software supply-chain evidence.

### Modified Capabilities

- None.

## Impact

Affected owners are `.github/workflows/**`, `.pre-commit-config.yaml`, CI-only scripts and fixtures, CI/release documentation, and only the dependency manifests/lockfiles that are proven necessary for stable CI. Existing application code, migrations, Dockerfile, compose, nginx, authentication/RBAC, and business behavior remain out of scope. The current Dockerfile and release requirements retain two dependency sources; the gate will document that residual limitation rather than silently claiming full image dependency reproducibility.
