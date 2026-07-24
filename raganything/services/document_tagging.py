"""Durable automatic-tag generation and reconciliation for persisted chunks."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import uuid
from pathlib import Path
from typing import Any

from raganything.services.pg_state_repo import get_pg_pool

logger = logging.getLogger("rag_server.document_tagging")

TAGGER_VERSION = "7"
TAG_LEASE_SECONDS = 15 * 60
TAG_MAX_ATTEMPTS = 5
TAG_RECONCILE_SECONDS = 5 * 60


class AutomaticTaggingDisabledError(RuntimeError):
    """Raised when a claimed job must wait for automatic tagging to be enabled."""


class AutomaticTaggingIntegrityError(RuntimeError):
    """A deterministic status/chunk mismatch that cannot heal by retrying.

    The document must be repaired or its explicitly marked residual rows
    cleaned before automatic tagging can run again.
    """


async def ensure_document_tag_jobs_table() -> None:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_tag_jobs (
                id BIGSERIAL PRIMARY KEY,
                kb_name TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                filename TEXT NOT NULL DEFAULT '',
                user_id INTEGER NOT NULL DEFAULT 0,
                upload_task_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                lease_until TIMESTAMPTZ,
                lease_token TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 100,
                last_error TEXT NOT NULL DEFAULT '',
                assigned_count INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                eligible_chunk_count INTEGER NOT NULL DEFAULT 0,
                tagged_chunk_count INTEGER NOT NULL DEFAULT 0,
                not_applicable_count INTEGER NOT NULL DEFAULT 0,
                content_fingerprint TEXT NOT NULL DEFAULT '',
                rerun_requested BOOLEAN NOT NULL DEFAULT FALSE,
                tagger_version TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (kb_name, doc_id)
            )
            """
        )
        await conn.execute(
            """
            ALTER TABLE document_tag_jobs
                ADD COLUMN IF NOT EXISTS eligible_chunk_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS tagged_chunk_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS not_applicable_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS content_fingerprint TEXT NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS rerun_requested BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS lease_token TEXT NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100,
                ADD COLUMN IF NOT EXISTS upload_task_id TEXT NOT NULL DEFAULT ''
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_tag_jobs_priority_due
            ON document_tag_jobs (status, priority DESC, next_attempt_at, updated_at)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_tag_jobs_upload_task
            ON document_tag_jobs (upload_task_id)
            WHERE upload_task_id <> ''
            """
        )


async def enqueue_document_tagging(
    kb_name: str,
    doc_id: str,
    *,
    filename: str = "",
    user_id: int = 0,
    task_id: str = "",
    max_attempts: int = TAG_MAX_ATTEMPTS,
    priority: int = 100,
) -> dict[str, Any]:
    """Idempotently make a document eligible for automatic tag generation."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO document_tag_jobs
                (kb_name, doc_id, filename, user_id, upload_task_id, status, attempt_count,
                 max_attempts, next_attempt_at, lease_until, lease_token,
                 priority, tagger_version, updated_at)
            VALUES ($1, $2, $3, $4, $5, 'queued', 0, $6, NOW(), NULL, '', $7, $8, NOW())
            ON CONFLICT (kb_name, doc_id) DO UPDATE SET
                filename = CASE WHEN EXCLUDED.filename <> ''
                    THEN EXCLUDED.filename ELSE document_tag_jobs.filename END,
                user_id = CASE WHEN EXCLUDED.user_id <> 0
                    THEN EXCLUDED.user_id ELSE document_tag_jobs.user_id END,
                upload_task_id = CASE
                    WHEN document_tag_jobs.status = 'running'
                      AND document_tag_jobs.upload_task_id <> ''
                    THEN document_tag_jobs.upload_task_id
                    WHEN EXCLUDED.upload_task_id <> ''
                    THEN EXCLUDED.upload_task_id
                    ELSE document_tag_jobs.upload_task_id END,
                status = CASE WHEN document_tag_jobs.status = 'running'
                    THEN 'running' ELSE 'queued' END,
                attempt_count = CASE
                    WHEN document_tag_jobs.status IN ('completed', 'terminal_failed')
                      OR document_tag_jobs.tagger_version <> EXCLUDED.tagger_version
                    THEN 0 ELSE document_tag_jobs.attempt_count END,
                max_attempts = EXCLUDED.max_attempts,
                next_attempt_at = CASE WHEN document_tag_jobs.status = 'running'
                    THEN document_tag_jobs.next_attempt_at ELSE NOW() END,
                lease_until = CASE WHEN document_tag_jobs.status = 'running'
                    THEN document_tag_jobs.lease_until ELSE NULL END,
                priority = CASE WHEN document_tag_jobs.status = 'running'
                    THEN GREATEST(document_tag_jobs.priority, EXCLUDED.priority)
                    ELSE EXCLUDED.priority END,
                rerun_requested = document_tag_jobs.status = 'running',
                tagger_version = EXCLUDED.tagger_version,
                updated_at = NOW()
            RETURNING *
            """,
            kb_name,
            doc_id,
            filename,
            int(user_id or 0),
            str(task_id or ""),
            max(1, int(max_attempts)),
            int(priority),
            TAGGER_VERSION,
        )
    return dict(row)


async def _validate_document_tagging_readiness(
    kb_name: str, doc_id: str,
) -> dict[str, Any]:
    """Validate one durable document without relying on paginated status data."""
    from raganything.services.document_quality import evaluate_content_readiness
    from raganything.services.kb_chunk_repo import query_chunks_by_document_id
    from raganything.services.kb_service import get_kb, _load_doc_status_by_id

    instance = await get_kb(kb_name)
    if instance is None or not getattr(instance, "lightrag", None):
        raise RuntimeError(f"knowledge base is unavailable for automatic tagging: {kb_name}")

    status = await _load_doc_status_by_id(kb_name, doc_id)
    if not isinstance(status, dict):
        raise RuntimeError(f"document status is not visible for automatic tagging: {doc_id}")

    metadata = status.get("metadata") or {}
    if isinstance(metadata, dict):
        failure_stage = str(metadata.get("failure_stage") or "").lower()
        marker_required = bool(
            str(status.get("status") or "").lower() == "failed"
            or
            metadata.get("multimodal_chunks")
            or metadata.get("residual_multimodal_chunk_ids")
            or failure_stage in {"multimodal", "worker_timeout", "finalize"}
        )
        if (
            metadata.get("content_ready") is False
            or metadata.get("multimodal_processed") is False
            or metadata.get("cleanup_pending") is True
            or (marker_required and metadata.get("multimodal_processed") is not True)
        ):
            raise AutomaticTaggingIntegrityError(
                "document is not ready for automatic tagging: "
                f"failure_stage={metadata.get('failure_stage', 'unknown')}"
            )

    persisted_chunks = await query_chunks_by_document_id(instance.lightrag, doc_id)
    persisted_by_id = {
        str(chunk.get("id")): dict(chunk)
        for chunk in persisted_chunks
        if isinstance(chunk, dict) and chunk.get("id")
    }
    declared_ids = [
        str(value) for value in status.get("chunks_list") or [] if value
    ]
    try:
        declared_count = int(status.get("chunks_count") or len(declared_ids))
    except (TypeError, ValueError):
        declared_count = len(declared_ids)

    if declared_count <= 0:
        raise AutomaticTaggingIntegrityError(
            f"document has no persisted chunks for automatic tagging: {doc_id}"
        )
    if not declared_ids or len(declared_ids) != declared_count:
        raise AutomaticTaggingIntegrityError(
            "document status does not declare the complete chunk ID set for automatic tagging"
        )
    if len(persisted_by_id) != declared_count:
        raise AutomaticTaggingIntegrityError(
            "document chunks are not fully visible for automatic tagging: "
            f"declared={declared_count}, persisted={len(persisted_by_id)}"
        )
    if declared_ids and (
        len(declared_ids) != declared_count
        or set(declared_ids) != set(persisted_by_id)
    ):
        raise AutomaticTaggingIntegrityError(
            "document status chunk IDs do not match persisted chunks for automatic tagging"
        )

    chunk_ids = declared_ids or list(persisted_by_id)
    quality = await evaluate_content_readiness(
        kb_name, chunk_ids, persisted_by_id,
    )
    if not quality["ready"]:
        raise AutomaticTaggingIntegrityError(
            f"document is not eligible for automatic tagging: {quality}"
        )
    return {
        "status": status,
        "chunk_ids": chunk_ids,
        "text_chunks": persisted_by_id,
        "quality": quality,
    }


async def enqueue_document_tagging_best_effort(
    kb_name: str,
    doc_id: str,
    *,
    filename: str = "",
    user_id: int = 0,
) -> dict[str, Any] | None:
    """Schedule tagging without making the owning content mutation fail."""
    try:
        return await enqueue_document_tagging(
            kb_name, doc_id, filename=filename, user_id=user_id,
        )
    except Exception:
        logger.warning(
            "Unable to queue automatic tagging: kb=%s doc=%s",
            kb_name, doc_id, exc_info=True,
        )
        return None


async def claim_due_tag_job() -> dict[str, Any] | None:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id
                FROM document_tag_jobs
                WHERE (
                    status IN ('queued', 'retry_wait')
                    AND next_attempt_at <= NOW()
                ) OR (
                    status = 'running' AND lease_until < NOW()
                )
                ORDER BY priority DESC, next_attempt_at, updated_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            if row is None:
                return None
            lease_token = str(uuid.uuid4())
            claimed = await conn.fetchrow(
                """
                UPDATE document_tag_jobs
                SET status = 'running', attempt_count = attempt_count + 1,
                    lease_until = NOW() + ($2 * INTERVAL '1 second'),
                    lease_token = $3,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                row["id"],
                TAG_LEASE_SECONDS,
                lease_token,
            )
    return dict(claimed) if claimed else None


async def complete_tag_job(
    job_id: int, result: dict[str, Any], lease_token: str
) -> None:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_tag_jobs
            SET status = CASE WHEN rerun_requested THEN 'queued' ELSE 'completed' END,
                next_attempt_at = CASE WHEN rerun_requested THEN NOW() ELSE next_attempt_at END,
                attempt_count = CASE WHEN rerun_requested THEN 0 ELSE attempt_count END,
                lease_until = NULL, lease_token = '', last_error = '',
                assigned_count = $2, chunk_count = $3,
                eligible_chunk_count = $4, tagged_chunk_count = $5,
                not_applicable_count = $6, content_fingerprint = $7,
                rerun_requested = FALSE, tagger_version = $8,
                updated_at = NOW()
            WHERE id = $1 AND status = 'running' AND lease_token = $9
            """,
            job_id,
            int(result.get("assigned") or 0),
            int(result.get("chunk_count") or 0),
            int(result.get("eligible_chunk_count") or 0),
            int(result.get("tagged_chunk_count") or 0),
            int(result.get("not_applicable_count") or 0),
            str(result.get("content_fingerprint") or ""),
            TAGGER_VERSION,
            lease_token,
        )


async def record_document_tagging_complete(
    kb_name: str, doc_id: str, result: dict[str, Any]
) -> None:
    """Record success for synchronous/manual regeneration paths."""
    try:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE document_tag_jobs
                SET status = 'completed', lease_until = NULL, last_error = '',
                assigned_count = $3, chunk_count = $4,
                eligible_chunk_count = $5, tagged_chunk_count = $6,
                not_applicable_count = $7, content_fingerprint = $8,
                rerun_requested = FALSE, tagger_version = $9,
                updated_at = NOW()
                WHERE kb_name = $1 AND doc_id = $2 AND status <> 'running'
                """,
                kb_name,
                doc_id,
                int(result.get("assigned") or 0),
                int(result.get("chunk_count") or 0),
                int(result.get("eligible_chunk_count") or 0),
                int(result.get("tagged_chunk_count") or 0),
                int(result.get("not_applicable_count") or 0),
                str(result.get("content_fingerprint") or ""),
                TAGGER_VERSION,
            )
    except Exception:
        logger.warning(
            "Unable to record automatic tag completion: kb=%s doc=%s",
            kb_name, doc_id, exc_info=True,
        )


async def fail_tag_job(job: dict[str, Any], error: BaseException) -> None:
    attempt = int(job.get("attempt_count") or 0)
    max_attempts = int(job.get("max_attempts") or TAG_MAX_ATTEMPTS)
    # A status/chunk integrity mismatch is deterministic until a repair or
    # explicit residue cleanup changes the document. Retrying it only repeats
    # the same failure and leaves the owning upload in retry_wait.
    should_retry = (
        attempt < max_attempts
        and not isinstance(error, AutomaticTaggingIntegrityError)
    )
    base_delay = min(30 * 60, 15 * (2 ** max(0, attempt - 1)))
    delay_seconds = max(1, int(base_delay * random.uniform(0.8, 1.2)))
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_tag_jobs
            SET status = CASE WHEN rerun_requested THEN 'queued' ELSE $2 END,
                attempt_count = CASE WHEN rerun_requested THEN 0 ELSE attempt_count END,
                next_attempt_at = CASE
                    WHEN rerun_requested THEN NOW()
                    WHEN $3 THEN NOW() + ($4 * INTERVAL '1 second')
                    ELSE next_attempt_at END,
                lease_until = NULL, lease_token = '',
                last_error = CASE WHEN rerun_requested THEN '' ELSE $5 END,
                rerun_requested = FALSE, updated_at = NOW()
            WHERE id = $1 AND status = 'running' AND lease_token = $6
            """,
            job["id"],
            "retry_wait" if should_retry else "terminal_failed",
            should_retry,
            delay_seconds,
            str(error)[:4000],
            str(job.get("lease_token") or ""),
        )


async def defer_disabled_tag_job(job: dict[str, Any]) -> None:
    """Return a claim to the queue without consuming its retry budget."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_tag_jobs
            SET status = 'queued', attempt_count = GREATEST(0, attempt_count - 1),
                next_attempt_at = NOW(), lease_until = NULL, lease_token = '',
                updated_at = NOW()
            WHERE id = $1 AND status = 'running' AND lease_token = $2
            """,
            job["id"],
            str(job.get("lease_token") or ""),
        )


async def release_cancelled_tag_job(job: dict[str, Any]) -> None:
    """Release a graceful-shutdown claim so the next process can resume it."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_tag_jobs
            SET status = 'queued', attempt_count = GREATEST(0, attempt_count - 1),
                next_attempt_at = NOW(), lease_until = NULL, lease_token = '',
                updated_at = NOW()
            WHERE id = $1 AND status = 'running' AND lease_token = $2
            """,
            job["id"],
            str(job.get("lease_token") or ""),
        )


async def cancel_document_tagging(kb_name: str, doc_ids: list[str]) -> None:
    ids = [str(doc_id) for doc_id in doc_ids if doc_id]
    if not ids:
        return
    try:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE document_tag_jobs
                SET status = 'terminal_failed', lease_until = NULL,
                    lease_token = '', last_error = 'document deleted', updated_at = NOW()
                WHERE kb_name = $1 AND doc_id = ANY($2::text[])
                  AND status <> 'completed'
                """,
                kb_name,
                ids,
            )
    except Exception:
        logger.warning(
            "Unable to cancel automatic tag jobs: kb=%s docs=%s",
            kb_name, ids, exc_info=True,
        )


async def terminate_document_tagging(
    kb_name: str, doc_id: str, error: str,
) -> None:
    """Make an upload-owned tag job terminal without changing document status."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_tag_jobs
            SET status = 'terminal_failed', lease_until = NULL,
                lease_token = '', rerun_requested = FALSE,
                last_error = $3, updated_at = NOW()
            WHERE kb_name = $1 AND doc_id = $2
              AND status <> 'completed'
            """,
            kb_name,
            doc_id,
            str(error or "automatic tagging failed")[:4000],
        )


async def delete_kb_tag_jobs(kb_name: str) -> None:
    try:
        await get_pg_pool().execute(
            "DELETE FROM document_tag_jobs WHERE kb_name = $1", kb_name
        )
    except Exception:
        logger.warning("Unable to delete automatic tag jobs: kb=%s", kb_name)


def derive_document_tag_health(
    row: dict[str, Any] | None,
    *,
    enabled: bool = True,
    managed: bool = True,
) -> dict[str, Any]:
    """Map durable queue state and verified assignment coverage to API fields."""
    if row is None:
        status = "pending" if enabled and managed else (
            "disabled" if not enabled else "unmanaged"
        )
        return {
            "tag_status": status,
            "tag_raw_status": "missing",
            "tagged_chunks": 0,
            "eligible_tag_chunks": 0,
            "tag_not_applicable_chunks": 0,
            "unique_auto_tag_count": 0,
            "auto_tag_assignment_count": 0,
            "avg_auto_tags_per_tagged_chunk": 0.0,
            "tag_error_message": "",
            "tag_retryable": enabled and managed,
        }

    raw_status = str(row.get("status") or "queued")
    chunk_count = int(row.get("chunk_count") or 0)
    eligible = int(row.get("eligible_chunk_count") or 0)
    tagged = min(
        int(row.get("tagged_chunk_count") or 0),
        int(row.get("actual_tagged_chunk_count") or 0),
    )
    not_applicable = int(row.get("not_applicable_count") or 0)
    unique_auto_tags = int(row.get("unique_auto_tag_count") or 0)
    auto_assignments = int(row.get("auto_tag_assignment_count") or 0)
    average_tags = round(auto_assignments / tagged, 1) if tagged > 0 else 0.0
    current_version = str(row.get("tagger_version") or "") == TAGGER_VERSION
    partition_valid = chunk_count == eligible + not_applicable
    coverage_complete = partition_valid and tagged >= eligible

    if not enabled:
        status = "disabled"
    elif not current_version:
        status = "pending"
    elif raw_status == "completed" and coverage_complete:
        status = "not_applicable" if chunk_count > 0 and eligible == 0 else "ready"
    elif raw_status == "running":
        status = "running"
    elif raw_status == "retry_wait":
        status = "retry_wait"
    elif raw_status == "terminal_failed":
        status = "failed"
    else:
        status = "pending"

    return {
        "tag_status": status,
        "tag_raw_status": raw_status,
        "tagged_chunks": tagged,
        "eligible_tag_chunks": eligible,
        "tag_not_applicable_chunks": not_applicable,
        "unique_auto_tag_count": unique_auto_tags,
        "auto_tag_assignment_count": auto_assignments,
        "avg_auto_tags_per_tagged_chunk": average_tags,
        "tag_error_message": str(row.get("last_error") or ""),
        "tag_retryable": status in {"pending", "retry_wait", "failed"},
    }


async def get_document_tag_health(
    kb_name: str, doc_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Return assignment-verified tag state for the requested documents."""
    from raganything.services.auto_tagging import automatic_tagging_enabled

    ids = [str(value) for value in doc_ids if value]
    if not ids:
        return {}
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT j.*,
                   COALESCE(coverage.actual_tagged_chunk_count, 0)::int
                       AS actual_tagged_chunk_count,
                   COALESCE(coverage.unique_auto_tag_count, 0)::int
                       AS unique_auto_tag_count,
                   COALESCE(coverage.auto_tag_assignment_count, 0)::int
                       AS auto_tag_assignment_count
            FROM document_tag_jobs j
            LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT a.chunk_id) AS actual_tagged_chunk_count,
                       COUNT(DISTINCT a.tag_id) AS unique_auto_tag_count,
                       COUNT(*) AS auto_tag_assignment_count
                FROM chunk_tag_assignments a
                WHERE a.kb_name = j.kb_name AND a.document_id = j.doc_id
                  AND a.assignment_kind IN ('auto_document', 'auto_chunk')
            ) coverage ON TRUE
            WHERE j.kb_name = $1 AND j.doc_id = ANY($2::text[])
            """,
            kb_name,
            ids,
        )
        workspace = "./rag_storage" if kb_name == "default" else f"./rag_storage_{kb_name}"
        active_rows = await conn.fetch(
            """
            SELECT d.id
            FROM LIGHTRAG_DOC_STATUS d
            WHERE d.workspace = $1 AND d.id = ANY($2::text[])
              AND EXISTS (
                  SELECT 1
                  FROM uploaded_files u
                  WHERE u.kb_name = $3
                    AND u.status IN ('queued', 'processing', 'retry_wait')
                    AND d.created_at >= (u.created_at AT TIME ZONE 'UTC')
                        - INTERVAL '5 seconds'
                    AND (
                        regexp_replace(replace(d.file_path, E'\\\\', '/'), '^.*/', '') = u.filename
                        OR (
                            length(regexp_replace(replace(d.file_path, E'\\\\', '/'), '^.*/', ''))
                                = length(u.filename) + 9
                            AND right(
                                regexp_replace(replace(d.file_path, E'\\\\', '/'), '^.*/', ''),
                                length(u.filename) + 1
                            ) = '_' || u.filename
                        )
                    )
              )
            """,
            workspace,
            ids,
            kb_name,
        )
    enabled = automatic_tagging_enabled()
    by_id = {str(row["doc_id"]): dict(row) for row in rows}
    active_doc_ids = {str(row["id"]) for row in active_rows}
    return {
        doc_id: derive_document_tag_health(
            by_id.get(doc_id),
            enabled=enabled,
            managed=doc_id in by_id or doc_id in active_doc_ids,
        )
        for doc_id in ids
    }


async def wait_for_document_tagging(
    kb_name: str,
    doc_id: str,
    *,
    timeout: float | None = None,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    """Wait until automatic tagging completes or reaches a terminal state."""
    from raganything.services.auto_tagging import automatic_tagging_enabled

    limit = timeout
    if limit is None:
        limit = float(os.getenv("UPLOAD_TAG_WAIT_TIMEOUT", "3600"))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(limit))
    while True:
        try:
            health = (await get_document_tag_health(kb_name, [doc_id])).get(doc_id, {})
        except Exception:
            logger.warning(
                "Automatic tag health is temporarily unavailable: kb=%s doc=%s",
                kb_name,
                doc_id,
                exc_info=True,
            )
            health = {}
        raw_status = str(health.get("tag_raw_status") or "")
        tag_status = str(health.get("tag_status") or "")
        if tag_status in {"ready", "not_applicable", "disabled"}:
            return health
        if raw_status == "terminal_failed":
            return health
        if not automatic_tagging_enabled():
            return {**health, "tag_status": "disabled", "tag_raw_status": raw_status}
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(
                f"automatic tagging did not finish for document {doc_id}"
            )
        await asyncio.sleep(min(max(0.1, poll_interval), remaining))


async def run_tag_job(job: dict[str, Any]) -> dict[str, Any]:
    from raganything.services.auto_tagging import automatic_tagging_enabled
    from raganything.services.kb_service import _generate_uploaded_document_tags

    if not automatic_tagging_enabled():
        raise AutomaticTaggingDisabledError("automatic tagging is disabled")
    await _validate_document_tagging_readiness(job["kb_name"], job["doc_id"])
    result = await _generate_uploaded_document_tags(
        job["kb_name"],
        job["doc_id"],
        filename=job.get("filename") or "",
        user_id=int(job.get("user_id") or 0),
    )
    if int(result.get("chunk_count") or 0) <= 0:
        raise RuntimeError("persisted chunks are not visible for automatic tagging")
    eligible = int(result.get("eligible_chunk_count") or 0)
    tagged = int(result.get("tagged_chunk_count") or 0)
    if eligible > tagged:
        raise RuntimeError(
            f"automatic tag quality coverage incomplete: {tagged}/{eligible} eligible chunks"
        )
    return result


async def cleanup_deleted_document_tag_assignments() -> int:
    """Remove assignments left behind if deletion crashed before tag cleanup."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM chunk_tag_assignments a
            WHERE NOT EXISTS (
                SELECT 1
                FROM LIGHTRAG_DOC_STATUS d
                WHERE d.id = a.document_id
                  AND d.workspace = CASE WHEN a.kb_name = 'default'
                      THEN './rag_storage' ELSE './rag_storage_' || a.kb_name END
            )
            """
        )
        await conn.execute(
            """
            DELETE FROM kb_tags t
            WHERE NOT EXISTS (
                SELECT 1 FROM chunk_tag_assignments a
                WHERE a.tag_id = t.id AND a.kb_name = t.kb_name
            )
            """
        )
    try:
        return int(str(result).split()[-1])
    except (TypeError, ValueError, IndexError):
        return 0


async def reconcile_missing_document_tags(limit: int = 200) -> int:
    """Queue durable documents missed by upload-time tag scheduling."""
    from raganything.services.auto_tagging import automatic_tagging_enabled

    if not automatic_tagging_enabled():
        return 0
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.name AS kb_name, d.id AS doc_id, d.file_path,
                   active_upload.task_id AS upload_task_id
            FROM kb_metadata m
            JOIN LIGHTRAG_DOC_STATUS d
              ON d.workspace = CASE WHEN m.name = 'default'
                   THEN './rag_storage' ELSE './rag_storage_' || m.name END
            JOIN LATERAL (
                SELECT u.task_id
                FROM uploaded_files u
                WHERE u.kb_name = m.name
                  AND u.status IN ('queued', 'processing', 'retry_wait')
                  AND d.created_at >= (u.created_at AT TIME ZONE 'UTC') - INTERVAL '5 seconds'
                  AND (
                      regexp_replace(replace(d.file_path, E'\\\\', '/'), '^.*/', '') = u.filename
                      OR (
                          length(regexp_replace(replace(d.file_path, E'\\\\', '/'), '^.*/', ''))
                              = length(u.filename) + 9
                          AND right(
                              regexp_replace(replace(d.file_path, E'\\\\', '/'), '^.*/', ''),
                              length(u.filename) + 1
                          ) = '_' || u.filename
                      )
                  )
                ORDER BY u.created_at DESC
                LIMIT 1
            ) active_upload ON TRUE
            LEFT JOIN document_tag_jobs j
              ON j.kb_name = m.name AND j.doc_id = d.id
            WHERE d.chunks_count > 0
              AND d.status IN ('processed', 'failed')
              AND j.id IS NULL
            ORDER BY d.updated_at
            LIMIT $1
            """,
            max(1, min(int(limit), 1000)),
        )
    queued = 0
    for row in rows:
        try:
            await enqueue_document_tagging(
                str(row["kb_name"]),
                str(row["doc_id"]),
                filename=Path(str(row["file_path"] or "")).name,
                task_id=str(row["upload_task_id"] or ""),
                priority=0,
            )
        except Exception:
            logger.warning(
                "Unable to reconcile automatic tags: kb=%s doc=%s",
                row["kb_name"], row["doc_id"], exc_info=True,
            )
            continue
        queued += 1
    return queued


async def reconcile_terminal_tag_uploads(limit: int = 200) -> int:
    """Finish upload tasks whose durable tag jobs reached a terminal state."""
    from raganything.services.kb_service import pg_update_upload_status_by_task_id
    from raganything.services.state_service import complete_task, fail_task

    pool = get_pg_pool()
    rows = await pool.fetch(
        """
        SELECT j.upload_task_id AS task_id, j.kb_name, j.doc_id,
               j.status, j.last_error
        FROM document_tag_jobs j
        JOIN uploaded_files u
          ON u.task_id = j.upload_task_id AND u.kb_name = j.kb_name
        WHERE j.upload_task_id <> ''
          AND j.status IN ('completed', 'terminal_failed')
          AND u.status IN ('queued', 'processing', 'retry_wait')
        ORDER BY j.updated_at
        LIMIT $1
        """,
        max(1, min(int(limit), 1000)),
    )
    reconciled = 0
    for row in rows:
        task_id = str(row["task_id"])
        try:
            if row["status"] == "completed":
                await complete_task(task_id)
                await pg_update_upload_status_by_task_id(
                    task_id,
                    "completed",
                    kb_name=str(row["kb_name"]),
                    error_message="",
                    outcome="",
                    warning_message="",
                )
            else:
                error = str(row["last_error"] or "automatic tagging did not complete")
                await fail_task(
                    task_id,
                    error,
                    outcome="terminal_failed",
                    failure_stage="tagging",
                    retryable=False,
                )
                await pg_update_upload_status_by_task_id(
                    task_id,
                    "failed",
                    kb_name=str(row["kb_name"]),
                    error_message=error,
                    outcome="terminal_failed",
                )
        except Exception:
            logger.warning(
                "Unable to reconcile terminal tag upload: task=%s doc=%s",
                task_id, row["doc_id"], exc_info=True,
            )
            continue
        reconciled += 1
    return reconciled


async def document_tagging_loop(interval_seconds: int = 3) -> None:
    from raganything.services.auto_tagging import automatic_tagging_enabled

    while True:
        try:
            await ensure_document_tag_jobs_table()
        except Exception:
            logger.warning(
                "Unable to initialize automatic tag queue; retrying",
                exc_info=True,
            )
            await asyncio.sleep(interval_seconds)
            continue
        break

    next_reconcile = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            await reconcile_terminal_tag_uploads()
        except Exception:
            logger.warning("Terminal tag upload reconciliation failed", exc_info=True)
        if not automatic_tagging_enabled():
            await asyncio.sleep(interval_seconds)
            continue
        now = loop.time()
        if now >= next_reconcile:
            try:
                removed = await cleanup_deleted_document_tag_assignments()
                if removed:
                    logger.info("Removed %s orphaned tag assignments", removed)
                queued = await reconcile_missing_document_tags()
                if queued:
                    logger.info("Queued %s documents missing automatic tags", queued)
            except Exception:
                logger.warning("Automatic tag reconciliation failed", exc_info=True)
            next_reconcile = now + TAG_RECONCILE_SECONDS

        try:
            job = await claim_due_tag_job()
        except Exception:
            logger.warning("Unable to claim automatic tag job", exc_info=True)
            await asyncio.sleep(interval_seconds)
            continue
        if job is None:
            await asyncio.sleep(interval_seconds)
            continue
        try:
            result = await run_tag_job(job)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(release_cancelled_tag_job(job))
            except Exception:
                logger.warning(
                    "Unable to release cancelled automatic tag claim: job=%s",
                    job.get("id"),
                    exc_info=True,
                )
            raise
        except AutomaticTaggingDisabledError:
            try:
                await defer_disabled_tag_job(job)
            except Exception:
                logger.warning(
                    "Unable to defer disabled automatic tag job: job=%s",
                    job.get("id"),
                    exc_info=True,
                )
            await asyncio.sleep(interval_seconds)
        except Exception as exc:
            logger.warning(
                "Automatic tagging failed: job=%s kb=%s doc=%s",
                job["id"], job["kb_name"], job["doc_id"], exc_info=True,
            )
            try:
                await fail_tag_job(job, exc)
            except Exception:
                logger.warning(
                    "Unable to persist automatic tag failure: job=%s",
                    job.get("id"),
                    exc_info=True,
                )
        else:
            try:
                await complete_tag_job(
                    job["id"], result, str(job.get("lease_token") or "")
                )
            except Exception:
                logger.warning(
                    "Unable to persist automatic tag completion: job=%s",
                    job.get("id"),
                    exc_info=True,
                )
            else:
                logger.info(
                    "Automatic tagging completed: kb=%s doc=%s chunks=%s assigned=%s",
                    job["kb_name"], job["doc_id"], result.get("chunk_count"),
                    result.get("assigned"),
                )
