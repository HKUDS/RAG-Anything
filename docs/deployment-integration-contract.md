# Deployment Integration Contract

## Startup Order

1. Inject explicit production secrets. `POSTGRES_PASSWORD` is required; the
   Compose fallback must never be used for a release deployment.
2. Verify the backup bundle before setting
   `MIGRATION_BACKUP_ACKNOWLEDGED=true` for the one-shot `migrate` service.
3. Start PostgreSQL and Redis, then run the canonical migration runner once.
4. Start the application only after `migrate` exits successfully.
5. Require `GET /api/ready` to return HTTP 200 before exposing Nginx.

The Compose migration service is intentionally fail-closed when the backup
acknowledgement is absent. It uses the checked-in manifest and does not perform
automatic rollback or skip a failed migration.

## Health Contract

- `GET /api/live` is dependency-free and returns HTTP 200 while the process is
  running.
- `GET /api/ready` returns HTTP 200 only when required KB and PostgreSQL
  dependencies are available; otherwise it returns HTTP 503.
- `GET /api/health` remains the compatibility endpoint and uses the same
  required-dependency status, without returning exception text, DSNs, or
  credentials.

## Recovery Contract

CI and staging use `release_ops.py backup`, `verify`, `restore`, and `validate`
only against isolated roots and isolated PostgreSQL databases. Restore requires
an explicit production database name guard even when the target is non-
production; omitting the guard is rejected.

TLS is deployment-owned at the approved edge. The bundled HTTP Nginx listener
does not advertise HSTS or expose a false 443 listener without certificates.
