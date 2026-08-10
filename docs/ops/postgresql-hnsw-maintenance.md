# PostgreSQL HNSW Maintenance

This runbook is for an approved write-pause window. It does not authorize a
live rebuild while API or Worker writers are active. Historical completed
documents are not rebuilt.

## Scope and topology

1. Identify the PostgreSQL owner. `docker-compose.yml` controls only the
   Compose `postgres` service. For external or managed PostgreSQL, obtain DBA
   approval and apply equivalent settings there.
2. Capture a baseline with `python scripts/check_pgvector_hnsw.py --json`.
   Save the report outside the repository. It contains no credentials.
3. Confirm `SHOW shared_buffers`, `SHOW work_mem`, and
   `SHOW maintenance_work_mem` reflect the intended 1GB, 16MB, and 512MB.
   Confirm the Compose cgroup limit is 4 GiB and shared memory is at least 1
   GiB when Compose owns PostgreSQL.
4. Treat 4 GiB as a hard limit, not reserved free memory. Review active
   connections, `max_connections`, cgroup memory events, host free memory,
   and disk headroom for old plus replacement indexes.

## Drain and backup

1. Pause upload admission and wait until no `queued`, `processing`, or
   `retry_wait` upload tasks remain. Do not cancel or requeue work as part of
   this runbook.
2. Stop every API and Worker process that can write LightRAG tables.
3. Create and verify a logical backup using the deployment-approved command.
   Record the backup location and an integrity check before proceeding.
4. Capture `pg_get_indexdef`, validity, readiness, and size for each HNSW
   index discovered by the health check. Never assume LightRAG index names.

## Rebuild

1. Apply the PostgreSQL recovery settings and restart PostgreSQL. Compose
   settings do not affect an external database.
2. With all writers still stopped, open one maintenance session and run an
   ordinary transaction. For each discovered HNSW index, drop and recreate it
   from its captured definition using `m=16, ef_construction=64`.
3. Do not use `CONCURRENTLY` in this transaction. If any DDL fails, roll back
   the entire transaction; the old indexes remain. Do not resume uploads.
4. A rebuild is not proof that incremental HNSW memory exhaustion is fixed;
   retain the baseline memory evidence and compare it after acceptance.

## Validate and rollback

1. Restart PostgreSQL, then API and Worker. Run the health check again and
   verify every discovered HNSW index is valid and ready with the expected DDL.
2. Upload one real MP4 and confirm timestamped Chinese segments, graph writes,
   and retrieval. Check logs for no HNSW memory failures.
3. If validation fails, pause admission again, restore the prior runtime
   settings, restart PostgreSQL, and use transactional rollback or the
   verified backup under the normal incident procedure before resuming writes.
