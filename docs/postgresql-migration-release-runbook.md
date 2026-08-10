# PostgreSQL Migration Release Runbook

Use this runbook for every PostgreSQL schema deployment. The release gate reads
`migrations/migration_manifest.json`; the complete SQL filename is the migration
identity. Numeric prefixes are not unique and must not be used as status keys.

## Preconditions

1. Stop here if the target is not identified as the intended release database.
2. Take a PostgreSQL backup with the deployment-approved pg_dump procedure.
3. Verify that the backup completed and can be restored according to the
   deployment recovery procedure. Retain its location and verification evidence
   outside this repository.
4. Provide database connection details through the normal PostgreSQL environment
   variables, a pgpass file, or another approved secret mechanism. Do not pass
   a DSN, password, or token on this command line or paste one into a release log.

## Preflight

Run status and plan first. Replace the placeholder database and role names with
deployment values; neither command writes application schema migrations.

```powershell
.venv\Scripts\python.exe scripts\pg_migration_runner.py status
.venv\Scripts\python.exe scripts\pg_migration_runner.py plan
```

Status reports manifest sequence, complete migration ID, state, SHA-256, and
sanitized failure classification/detail. The release must stop if status or plan reports a
checksum conflict, an unresolved failed migration, an unknown history row, or a
gap in the recorded manifest prefix.

## Existing Database With No History

Do not let the runner infer applied migrations from table names. A baseline is
allowed only when an operator has independently verified a reviewed checkpoint,
the target has existing schema objects, the history table is empty, and a backup
has been acknowledged. It records the exact manifest prefix and does not execute
skipped historical SQL:

```powershell
.venv\Scripts\python.exe scripts\pg_migration_runner.py baseline `
  --through <exact-migration-filename> `
  --backup-acknowledged
```

An unknown or partially understood database must be restored, assessed, or
migrated through a separately reviewed recovery plan before it enters this
workflow.

## Apply and Verify

Only after backup verification and a clean preflight, apply the pending chain:

```powershell
.venv\Scripts\python.exe scripts\pg_migration_runner.py apply --backup-acknowledged
.venv\Scripts\python.exe scripts\pg_migration_runner.py status
```

The runner invokes one SQL file at a time with ON_ERROR_STOP=1, records the
SHA-256 only after that file succeeds, and stops before any later file if a
migration fails. Several historical files manage their own transactions, so the
runner intentionally does not add a global transaction wrapper around them.

## Fresh Provisioning

For a newly created database and application role, use the setup wrapper. It
prompts securely for the PostgreSQL administrator password (or reads
`PGPASSWORD` from an approved secret mechanism), does not accept a password or
DSN on the command line, does not create a `DATABASE_URL`, and delegates the
complete manifest to the same migration runner. The initial application-role
password is the administrator password supplied to this invocation; rotate it
through the approved secret-management process when required.

```powershell
.venv\Scripts\python.exe scripts\pg_setup.py `
  --db-name <database> --db-user <role> --backup-acknowledged
```

Configure the application's connection secret separately through the approved
deployment secret store or local environment configuration.

## Failure Handling and Rollback

1. Do not retry by deleting migration history, modifying a historical SQL file,
   or skipping the failed migration.
2. Stop the service deployment and preserve only sanitized runner output plus
   the migration ID, checksum, timestamp, and backup reference in the incident
   record.
3. Determine whether the failed SQL file could have left partial state. Historical
   files that manage their own transactions require especially careful review.
4. Restore the verified backup when recovery requires reverting database state,
   or create a separately reviewed forward corrective migration when preservation
   of the applied state is required.
5. Re-run status and plan after recovery. Resume deployment only when their
   result is clean and the corresponding operational approval is recorded.

The runner does not claim automatic rollback for arbitrary SQL migrations.
