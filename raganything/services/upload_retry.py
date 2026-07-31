"""Durable upload retry queue for transient external-model failures."""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from raganything.services.pg_state_repo import get_pg_pool

RETRY_DELAYS_SECONDS = (30, 120, 600, 1800, 7200)
DEFAULT_MAX_RETRIES = 5
_runner_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def retry_delay_seconds(attempt_count: int, *, jitter: float | None = None) -> float:
    index = max(0, min(int(attempt_count) - 1, len(RETRY_DELAYS_SECONDS) - 1))
    base = float(RETRY_DELAYS_SECONDS[index])
    factor = random.uniform(0.9, 1.1) if jitter is None else float(jitter)
    return max(1.0, base * factor)


async def ensure_upload_retry_jobs_table() -> None:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            ALTER TABLE processing_tasks
                ADD COLUMN IF NOT EXISTS retryable BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS failure_stage VARCHAR(64) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 5,
                ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_retry_jobs (
                id BIGSERIAL PRIMARY KEY,
                upload_id BIGINT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
                task_id VARCHAR(64) NOT NULL,
                kb_name VARCHAR(255) NOT NULL,
                file_path VARCHAR(1000) NOT NULL,
                filename VARCHAR(500) NOT NULL,
                file_hash VARCHAR(64) NOT NULL,
                user_id INTEGER NOT NULL DEFAULT 0,
                stage VARCHAR(64) NOT NULL DEFAULT 'model_preflight',
                chunking_strategy VARCHAR(50) NOT NULL DEFAULT '',
                enable_image BOOLEAN, enable_table BOOLEAN,
                enable_equation BOOLEAN, enable_video BOOLEAN,
                status VARCHAR(24) NOT NULL DEFAULT 'retry_wait',
                attempt_count INTEGER NOT NULL DEFAULT 1,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                lease_token UUID, lease_until TIMESTAMPTZ,
                root_type VARCHAR(255) NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                UNIQUE (upload_id, stage)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_upload_retry_due ON upload_retry_jobs(next_attempt_at, id) "
            "WHERE status IN ('queued','retry_wait','running')"
        )


async def schedule_upload_retry(
    *, task_id: str, kb_name: str, file_path: str, filename: str,
    file_hash: str, user_id: int, stage: str, root_type: str, error: str,
    chunking_strategy: str = "", enable_image: bool | None = None,
    enable_table: bool | None = None, enable_equation: bool | None = None,
    enable_video: bool | None = None, retry_job_id: int | None = None,
    lease_token: str | None = None,
    claim_owner: str | None = None, claim_generation: int | None = None,
) -> dict[str, Any] | None:
    """Create or reschedule a retry and atomically expose retry_wait state."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            upload = await conn.fetchrow(
                "SELECT id, status FROM uploaded_files WHERE task_id=$1 AND kb_name=$2 FOR UPDATE",
                task_id, kb_name,
            )
            if not upload or upload["status"] != "processing":
                return None
            if claim_owner is not None:
                if claim_generation is None:
                    return None
                owned = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM uploaded_files WHERE id=$1 "
                    "AND processing_owner=$2 AND processing_generation=$3)",
                    upload["id"], claim_owner, int(claim_generation),
                )
                if not owned:
                    return None
            existing = None
            if retry_job_id is not None:
                existing = await conn.fetchrow(
                    "SELECT * FROM upload_retry_jobs WHERE id=$1 FOR UPDATE", retry_job_id
                )
                if not existing or existing["status"] != "running" or str(existing["lease_token"]) != str(lease_token):
                    return None
            else:
                existing = await conn.fetchrow(
                    "SELECT * FROM upload_retry_jobs WHERE upload_id=$1 AND stage=$2 FOR UPDATE",
                    upload["id"], stage,
                )
            attempt = (int(existing["attempt_count"]) + 1) if existing else 1
            max_attempts = int(existing["max_attempts"]) if existing else DEFAULT_MAX_RETRIES
            terminal = attempt > max_attempts
            effective_attempt = min(attempt, max_attempts)
            next_at = datetime.now(timezone.utc) + timedelta(
                seconds=retry_delay_seconds(effective_attempt)
            )
            if existing:
                row = await conn.fetchrow(
                    """
                    UPDATE upload_retry_jobs SET
                        status=$2::varchar, attempt_count=$3, next_attempt_at=$4,
                        lease_token=NULL, lease_until=NULL, root_type=$5,
                        last_error=$6, updated_at=NOW(),
                        completed_at=CASE WHEN $2::text='terminal_failed' THEN NOW() ELSE NULL END
                    WHERE id=$1 RETURNING *
                    """,
                    existing["id"], "terminal_failed" if terminal else "retry_wait",
                    effective_attempt, next_at, root_type, error,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO upload_retry_jobs
                    (upload_id,task_id,kb_name,file_path,filename,file_hash,user_id,stage,
                     chunking_strategy,enable_image,enable_table,enable_equation,enable_video,
                     status,attempt_count,max_attempts,next_attempt_at,root_type,last_error)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'retry_wait',1,$14,$15,$16,$17)
                    RETURNING *
                    """,
                    upload["id"], task_id, kb_name, file_path, filename, file_hash,
                    user_id, stage, chunking_strategy, enable_image, enable_table,
                    enable_equation, enable_video, DEFAULT_MAX_RETRIES, next_at,
                    root_type, error,
                )
            public_status = "failed" if terminal else "retry_wait"
            await conn.execute(
                "UPDATE uploaded_files SET status=$2,error_message=$3,updated_at=NOW() WHERE id=$1 AND status<>'deleted'",
                upload["id"], public_status, error,
            )
            await conn.execute(
                """
                UPDATE processing_tasks SET status=$2::varchar,retryable=$3,failure_stage=$4::varchar,
                    retry_count=$5,max_retries=$6,next_retry_at=$7,error_message=$8,
                    message=$9,completed_at=CASE WHEN $2::text='failed' THEN NOW() ELSE NULL END,
                    updated_at=NOW() WHERE task_id=$1
                """,
                task_id, public_status, not terminal, stage, effective_attempt,
                max_attempts, None if terminal else next_at, error,
                "Automatic retry limit reached" if terminal else "Waiting for automatic retry",
            )
            return dict(row)


async def claim_due_retry() -> dict[str, Any] | None:
    lease_seconds = max(300, int(os.getenv("PROCESS_TIMEOUT", "3600")) + 300)
    token = uuid.uuid4()
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                WITH candidate AS (
                    SELECT id FROM upload_retry_jobs
                    WHERE ((status IN ('queued','retry_wait') AND next_attempt_at <= NOW())
                        OR (status='running' AND lease_until < NOW()))
                    ORDER BY next_attempt_at,id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE upload_retry_jobs j SET status='running',lease_token=$1,
                    lease_until=NOW()+($2 * INTERVAL '1 second'),updated_at=NOW()
                FROM candidate c WHERE j.id=c.id RETURNING j.*
                """,
                token, lease_seconds,
            )
            if not row:
                return None
            alive = await conn.fetchval(
                "SELECT status NOT IN ('deleted', 'cancelling') FROM uploaded_files WHERE id=$1", row["upload_id"]
            )
            if not alive:
                await conn.execute(
                    "UPDATE upload_retry_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE id=$1",
                    row["id"],
                )
                return None
            await conn.execute(
                "UPDATE uploaded_files SET status='queued',processing_owner=NULL,"
                "processing_heartbeat_at=NULL,updated_at=NOW() WHERE id=$1 AND status<>'deleted'",
                row["upload_id"],
            )
            await conn.execute(
                "UPDATE processing_tasks SET status='processing',phase='retrying',phase_status='start',"
                "message='Automatic retry in progress',next_retry_at=NULL,updated_at=NOW() WHERE task_id=$1",
                row["task_id"],
            )
            result = dict(row)
            result["lease_token"] = str(token)
            return result


async def complete_upload_retry(job_id: int, lease_token: str) -> bool:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE upload_retry_jobs SET status='completed',completed_at=NOW(),"
                "lease_token=NULL,lease_until=NULL,updated_at=NOW() "
                "WHERE id=$1 AND status='running' AND lease_token=$2::uuid "
                "AND EXISTS (SELECT 1 FROM uploaded_files u WHERE u.id=upload_retry_jobs.upload_id "
                "AND u.status<>'deleted') RETURNING upload_id,task_id",
                job_id, lease_token,
            )
            if not row:
                return False
            return True


async def retry_now(task_id: str, *, reset_budget: bool = False) -> bool:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE upload_retry_jobs SET status='queued',next_attempt_at=NOW(),"
                "attempt_count=CASE WHEN $2 THEN 1 ELSE attempt_count END,"
                "lease_token=NULL,lease_until=NULL,completed_at=NULL,updated_at=NOW() "
                "WHERE task_id=$1 AND status IN ('retry_wait','terminal_failed') RETURNING upload_id",
                task_id, reset_budget,
            )
            if not row:
                return False
            await conn.execute(
                "UPDATE uploaded_files SET status='retry_wait',updated_at=NOW() WHERE id=$1 AND status NOT IN ('deleted', 'cancelling')",
                row["upload_id"],
            )
            await conn.execute(
                "UPDATE processing_tasks SET status='retry_wait',retryable=TRUE,"
                "phase='retry_wait',phase_status='queued',message='Waiting for automatic retry',"
                "completed_at=NULL,updated_at=NOW() WHERE task_id=$1",
                task_id,
            )
            return True


async def cancel_retry(task_id: str) -> bool:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE upload_retry_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,updated_at=NOW() "
                "WHERE task_id=$1 AND status IN ('queued','retry_wait') RETURNING upload_id,last_error",
                task_id,
            )
            if not row:
                return False
            await conn.execute(
                "UPDATE uploaded_files SET status='failed',updated_at=NOW() "
                "WHERE id=$1 AND status='retry_wait'", row["upload_id"],
            )
            await conn.execute(
                "UPDATE processing_tasks SET status='failed',retryable=FALSE,next_retry_at=NULL,"
                "message='Automatic retry cancelled',completed_at=NOW(),updated_at=NOW() WHERE task_id=$1",
                task_id,
            )
            return True


async def get_retry_metadata(task_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not task_ids:
        return {}
    try:
        rows = await get_pg_pool().fetch(
            "SELECT DISTINCT ON (task_id) task_id,status,stage,attempt_count,max_attempts,"
            "next_attempt_at,last_error,root_type FROM upload_retry_jobs "
            "WHERE task_id=ANY($1::text[]) ORDER BY task_id,updated_at DESC", task_ids,
        )
    except RuntimeError:
        return {}
    return {str(row["task_id"]): dict(row) for row in rows}


async def _retry_loop() -> None:
    assert _stop_event is not None
    while not _stop_event.is_set():
        try:
            job = await claim_due_retry()
            if job:
                from raganything.services.kb_service import _ensure_queue_draining
                queue, _ = await _ensure_queue_draining(job["kb_name"])
                queue.put_nowait({
                    "task_id": job["task_id"], "file_path": job["file_path"],
                    "filename": job["filename"], "kb_name": job["kb_name"],
                    "chunking_strategy": job["chunking_strategy"], "user_id": job["user_id"],
                    "enable_image": job["enable_image"], "enable_table": job["enable_table"],
                    "enable_equation": job["enable_equation"], "enable_video": job["enable_video"],
                    "retry_job_id": job["id"], "retry_lease_token": job["lease_token"],
                })
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.getLogger("rag_server.upload_retry").exception("Upload retry loop failed")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass


async def start_upload_retry_runner() -> None:
    global _runner_task, _stop_event
    if _runner_task and not _runner_task.done():
        return
    _stop_event = asyncio.Event()
    _runner_task = asyncio.create_task(_retry_loop(), name="upload-retry-runner")


async def stop_upload_retry_runner() -> None:
    global _runner_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _runner_task:
        await _runner_task
    _runner_task = None
    _stop_event = None
