# Release CI Gates

The default PR/main and package-release workflow is `Default release checks`.
GitHub branch protection must require these stable job names after the first
green `main` run:

- `backend-quality` (5-20 minutes): locked Python install and backend tests.
- `frontend-unit-build` (3-10 minutes): locked Node install, unit tests, build.
- `lint-and-static` (2-8 minutes): read-only Ruff checks.
- `postgres-migrations-api` (5-20 minutes): service readiness, isolated
  fresh/repeat/upgrade/failure migration fixtures, canonical fresh migration,
  repeat/no-op verification, schema/index facts, PostgreSQL CRUD, and an
  authenticated HTTP permission contract.
- `default-container-smoke` (5-25 minutes): default image build and health API.
- `supply-chain-security` (5-25 minutes): lock, secret, dependency, image, and
  SBOM checks.
- `project-summary-quality` (under 5 minutes): mandatory summary quality.

Failure classes are source/lock drift, unit/build, static format, PostgreSQL
service, fresh migration, migration history/repeat, CRUD, container startup,
secret finding, SCA/image vulnerability, SBOM collection, and summary quality.
Only transient GitHub runner, registry, or service outages may be retried; all
other failures require a source or configuration change. HIGH and CRITICAL
production dependency/image findings, scanner errors, timeouts, secret findings,
and missing SBOM artifacts block release. Exceptions require a version-controlled
review record, issue reference, and expiry. The default policy is
`.github/security/ci-exceptions.json` and is fail-closed by
`scripts/check_security_exceptions.py`.

`OpenDataLoader Release Gate` is `workflow_dispatch` only. It remains
fail-closed for its Java, parser, redistribution, legal, and specialized SBOM
evidence, but it is not a default required check.

The default Docker build still resolves `requirements.txt` and frontend npm
dependencies internally, so it is not proven lockfile-reproducible while the
current Dockerfile remains outside this change's scope. The default CI install
paths are locked and verified independently.

The blocking backend job also verifies the deployment/recovery command
contracts: the migration runner CLI, backup/verify/restore/validate operation
tests, explicit isolated-restore production-target protection, and sanitized
failure behavior. CI uses disposable targets only; it never applies migrations
or restores backups to a production database.

Branch protection is an external administrator action. Recommendation: bind all
seven names above immediately after the first green `main` run, including
`project-summary-quality`. This repository change does not claim that binding
has been configured.

Rollback: revert the workflow/docs/lock change as one reviewed commit; do not
disable an individual required check to bypass a failing release condition.

## Current evidence (2026-08-04)

The canonical migration runner was exercised against the configured local
PostgreSQL service: `15 passed` covering fresh install, repeat no-op, checkpoint
upgrade, checksum/history behavior, and stop-on-failure. OpenSpec strict
validation, workflow YAML parsing, Ruff, Python compilation, and the empty
security-exception policy check also pass. The authenticated API fixture is
wired into CI but was not claimed as locally passed because this Windows
session lacks the locked asyncpg/pytest runtime and Docker/GitHub Actions.
