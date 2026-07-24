"""Durable, document-scoped graph enrichment repair queue."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

from raganything.services.pg_state_repo import get_pg_pool

logger = logging.getLogger("rag_server.document_repair")

REPAIR_STAGE = "entity_extraction"
REPAIR_LEASE_SECONDS = 15 * 60
REPAIR_MAX_ATTEMPTS = 3

_repair_lock = asyncio.Lock()


async def ensure_document_repair_jobs_table() -> None:
    """Create the repair queue for installations that do not run migrations."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            ALTER TABLE processing_tasks
                ADD COLUMN IF NOT EXISTS outcome VARCHAR(32) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS warning_message TEXT NOT NULL DEFAULT ''
            """
        )
        await conn.execute(
            """
            ALTER TABLE uploaded_files
                ADD COLUMN IF NOT EXISTS outcome VARCHAR(32) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS warning_message TEXT NOT NULL DEFAULT ''
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_repair_jobs (
                id BIGSERIAL PRIMARY KEY,
                kb_name VARCHAR(255) NOT NULL,
                doc_id VARCHAR(255) NOT NULL,
                stage VARCHAR(64) NOT NULL DEFAULT 'entity_extraction',
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                lease_until TIMESTAMPTZ,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (kb_name, doc_id, stage)
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_document_repair_jobs_due
            ON document_repair_jobs (status, next_attempt_at, updated_at)
            """
        )


async def enqueue_repair(
    kb_name: str,
    doc_id: str,
    *,
    stage: str = REPAIR_STAGE,
    error: str = "",
    max_attempts: int = REPAIR_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Insert or reset one idempotent repair job."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO document_repair_jobs
                (kb_name, doc_id, stage, status, attempt_count, max_attempts,
                 next_attempt_at, lease_until, last_error, updated_at)
            VALUES ($1, $2, $3, 'queued', 0, $4, NOW(), NULL, $5, NOW())
            ON CONFLICT (kb_name, doc_id, stage) DO UPDATE SET
                status = CASE
                    WHEN document_repair_jobs.status = 'running'
                        THEN document_repair_jobs.status
                    ELSE 'queued'
                END,
                attempt_count = CASE
                    WHEN document_repair_jobs.status IN ('completed', 'terminal_failed')
                        THEN 0
                    ELSE document_repair_jobs.attempt_count
                END,
                max_attempts = EXCLUDED.max_attempts,
                next_attempt_at = CASE
                    WHEN document_repair_jobs.status = 'running'
                        THEN document_repair_jobs.next_attempt_at
                    ELSE NOW()
                END,
                lease_until = CASE
                    WHEN document_repair_jobs.status = 'running'
                        THEN document_repair_jobs.lease_until
                    ELSE NULL
                END,
                last_error = EXCLUDED.last_error,
                updated_at = NOW()
            RETURNING id, kb_name, doc_id, stage, status, attempt_count,
                      max_attempts, next_attempt_at, lease_until, last_error,
                      created_at, updated_at
            """,
            kb_name,
            doc_id,
            stage,
            max(1, int(max_attempts)),
            str(error or "")[:4000],
        )
    return dict(row)


async def prepare_document_repair(
    kb_name: str,
    requested_doc_id: str,
    *,
    error: str = "",
) -> dict[str, Any]:
    """Validate a partial document, mark it degraded, and enqueue repair."""
    from raganything.services.kb_service import _load_doc_status_json, get_kb

    statuses = await _load_doc_status_json(kb_name)
    full_id = next((doc_id for doc_id in statuses if doc_id.startswith(requested_doc_id)), None)
    if not full_id:
        raise KeyError(requested_doc_id)
    info = dict(statuses[full_id] or {})
    chunks_count = int(info.get("chunks_count") or 0)
    if chunks_count <= 0:
        raise ValueError("document has no persisted text chunks")

    instance = await get_kb(kb_name)
    from raganything.services.kb_chunk_repo import query_chunks_by_document_id

    persisted_chunks = await query_chunks_by_document_id(instance.lightrag, full_id)
    persisted_by_id = {
        str(chunk.get("id")): chunk
        for chunk in persisted_chunks
        if isinstance(chunk, dict) and chunk.get("id")
    }
    chunk_ids = [str(chunk_id) for chunk_id in info.get("chunks_list") or []]
    if len(persisted_by_id) != chunks_count:
        raise ValueError("document text chunks are incomplete")
    if chunk_ids and set(chunk_ids) != set(persisted_by_id):
        raise ValueError("doc_status chunk IDs do not match persisted text chunks")
    if not chunk_ids:
        chunk_ids = list(persisted_by_id)
    from raganything.services.document_quality import evaluate_content_readiness
    quality = await evaluate_content_readiness(kb_name, chunk_ids, persisted_by_id)
    if not quality["ready"]:
        raise ValueError(f"document content is not ready for graph repair: {quality}")

    metadata = dict(info.get("metadata") or {})
    metadata.update({
        "content_ready": True,
        "graph_status": "pending",
        "failure_stage": metadata.get("failure_stage") or REPAIR_STAGE,
        "retryable": True,
        "failed_chunk_ids": metadata.get("failed_chunk_ids") or [
            chunk_id
            for chunk_id in chunk_ids
            if not persisted_by_id[chunk_id].get("llm_cache_list")
        ],
        "retry_count": int(metadata.get("retry_count") or 0),
        "last_error": error or info.get("error_msg") or "",
    })
    info["metadata"] = metadata
    await instance.lightrag.doc_status.upsert({full_id: info})
    await instance.lightrag.doc_status.index_done_callback()
    job = await enqueue_repair(kb_name, full_id, error=error or info.get("error_msg") or "")
    return {"doc_id": full_id, "status": "degraded", "job": job}


async def claim_due_repair() -> dict[str, Any] | None:
    """Claim one due job using row locking so workers do not duplicate work."""
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id
                FROM document_repair_jobs
                WHERE (
                    status IN ('queued', 'retry_wait')
                    AND next_attempt_at <= NOW()
                ) OR (
                    status = 'running'
                    AND lease_until < NOW()
                )
                ORDER BY next_attempt_at, updated_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            if row is None:
                return None
            claimed = await conn.fetchrow(
                """
                UPDATE document_repair_jobs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    lease_until = NOW() + ($2 * INTERVAL '1 second'),
                    updated_at = NOW()
                WHERE id = $1
                RETURNING id, kb_name, doc_id, stage, status, attempt_count,
                          max_attempts, next_attempt_at, lease_until, last_error
                """,
                row["id"],
                REPAIR_LEASE_SECONDS,
            )
    return dict(claimed) if claimed else None


async def complete_repair(job_id: int) -> None:
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_repair_jobs
            SET status = 'completed', lease_until = NULL, updated_at = NOW()
            WHERE id = $1 AND status = 'running'
            """,
            job_id,
        )


async def cancel_repair_jobs(
    kb_name: str, doc_ids: list[str], *, reason: str = "document deleted",
) -> None:
    """Stop queued/running repairs when their source document is deleted."""
    ids = [str(doc_id) for doc_id in doc_ids if doc_id]
    if not ids:
        return
    try:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE document_repair_jobs
                SET status = 'terminal_failed', lease_until = NULL,
                    last_error = $3, updated_at = NOW()
                WHERE kb_name = $1 AND doc_id = ANY($2::text[])
                  AND status <> 'completed'
                """,
                kb_name,
                ids,
                str(reason)[:4000],
            )
    except Exception:
        logger.warning(
            "Unable to cancel document repair jobs: kb=%s docs=%s",
            kb_name,
            ids,
            exc_info=True,
        )


async def _repair_job_was_cancelled(job_id: int) -> bool:
    try:
        pool = get_pg_pool()
        async with pool.acquire() as conn:
            status = await conn.fetchval(
                "SELECT status FROM document_repair_jobs WHERE id = $1", job_id
            )
        return status in {"terminal_failed", "completed"}
    except Exception:
        logger.warning("Unable to check repair cancellation: job=%s", job_id)
        return False


async def fail_repair(job: dict[str, Any], error: str, *, retryable: bool) -> None:
    """Record a failure and schedule bounded exponential retry when allowed."""
    attempt = int(job.get("attempt_count") or 0)
    max_attempts = int(job.get("max_attempts") or REPAIR_MAX_ATTEMPTS)
    should_retry = retryable and attempt < max_attempts
    base_delay = min(15 * 60, 30 * (2 ** max(0, attempt - 1)))
    delay_seconds = max(1, int(base_delay * random.uniform(0.8, 1.2)))
    status = "retry_wait" if should_retry else "terminal_failed"
    pool = get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE document_repair_jobs
            SET status = $2,
                next_attempt_at = CASE WHEN $3 THEN NOW() + ($4 * INTERVAL '1 second') ELSE next_attempt_at END,
                lease_until = NULL,
                last_error = $5,
                updated_at = NOW()
            WHERE id = $1
            """,
            job["id"],
            status,
            should_retry,
            delay_seconds,
            str(error or "")[:4000],
        )


class _DocStatusAllowList:
    """Proxy that limits LightRAG's native recovery pipeline to one document."""

    def __init__(self, backend: Any, doc_id: str):
        self._backend = backend
        self._doc_id = doc_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    async def get_docs_by_statuses(self, statuses):
        docs = await self._backend.get_docs_by_statuses(statuses)
        return {doc_id: doc for doc_id, doc in docs.items() if doc_id == self._doc_id}

    async def get_docs_by_status(self, status):
        docs = await self._backend.get_docs_by_status(status)
        return {doc_id: doc for doc_id, doc in docs.items() if doc_id == self._doc_id}


def _is_retryable_error(error: BaseException) -> bool:
    text = str(error).lower()
    terminal_markers = (
        "authentication", "unauthorized", "invalid api key", "invalid_api_key",
        "insufficient_quota", "quota", "billing", "permission denied",
        "invalid request", "bad request", "invalid parameter", "model not found",
        "invalid model", "unsupported model", "400", "401", "403", "404",
    )
    if any(marker in text for marker in terminal_markers):
        return False
    transient_markers = (
        "timeout", "timed out", "rate limit", "429",
        "connection", "temporarily unavailable", "server error",
    )
    return any(marker in text for marker in transient_markers) or bool(
        re.search(r"\b5\d\d\b", text)
    )


async def run_repair_job(job: dict[str, Any]) -> None:
    """Run LightRAG's native recovery pipeline for the claimed document only."""
    from raganything.services.kb_service import get_kb, _load_doc_status_json

    async with _repair_lock:
        instance = await get_kb(job["kb_name"])
        if not instance or not instance.lightrag:
            raise RuntimeError(f"KB unavailable: {job['kb_name']}")

        lightrag = instance.lightrag
        original_doc_status = lightrag.doc_status
        original_info = await original_doc_status.get_by_id(job["doc_id"]) or {}
        original_metadata = dict(original_info.get("metadata") or {})
        lightrag.doc_status = _DocStatusAllowList(original_doc_status, job["doc_id"])
        try:
            await lightrag.apipeline_process_enqueue_documents()
        finally:
            lightrag.doc_status = original_doc_status

        if await _repair_job_was_cancelled(job["id"]):
            return

        statuses = await _load_doc_status_json(job["kb_name"])
        status = statuses.get(job["doc_id"], {})
        metadata = dict(status.get("metadata") or {})
        from raganything.services.kb_chunk_repo import query_chunks_by_document_id
        from raganything.services.document_quality import evaluate_content_readiness

        persisted_chunks = await query_chunks_by_document_id(lightrag, job["doc_id"])
        persisted_by_id = {
            str(chunk.get("id")): chunk
            for chunk in persisted_chunks
            if isinstance(chunk, dict) and chunk.get("id")
        }
        quality = await evaluate_content_readiness(
            job["kb_name"],
            [str(value) for value in status.get("chunks_list") or persisted_by_id],
            persisted_by_id,
        )
        if status.get("status") == "processed":
            if not quality["ready"]:
                raise RuntimeError(f"document vector quality gate failed after repair: {quality}")
            metadata.update({
                "content_ready": True,
                "graph_status": "completed",
                "failure_stage": "",
                "retryable": False,
                "failed_chunk_ids": [],
                "last_error": "",
                "retry_count": int(job.get("attempt_count") or 0),
            })
            await original_doc_status.upsert({
                job["doc_id"]: {**status, "metadata": metadata}
            })
            await original_doc_status.index_done_callback()
            try:
                from raganything.services.document_tagging import (
                    enqueue_document_tagging,
                )

                await enqueue_document_tagging(
                    job["kb_name"],
                    job["doc_id"],
                    filename=str(status.get("file_path") or ""),
                )
            except Exception:
                logger.warning(
                    "Unable to queue automatic tags after graph repair: kb=%s doc=%s",
                    job["kb_name"], job["doc_id"], exc_info=True,
                )
            return

        error = status.get("error_msg") or "图谱补偿未完成"
        metadata.update({
            "content_ready": bool(quality["ready"]),
            "graph_status": "failed",
            "failure_stage": "entity_extraction",
            "retryable": _is_retryable_error(RuntimeError(error)),
            "last_error": str(error)[:4000],
            "failed_chunk_ids": original_metadata.get("failed_chunk_ids")
            or list(status.get("chunks_list") or []),
            "retry_count": int(job.get("attempt_count") or 0),
        })
        await original_doc_status.upsert({
            job["doc_id"]: {**status, "metadata": metadata}
        })
        await original_doc_status.index_done_callback()
        raise RuntimeError(error)


async def repair_loop(interval_seconds: int = 15) -> None:
    """Background repair worker; safe to cancel during application shutdown."""
    await ensure_document_repair_jobs_table()
    while True:
        job = await claim_due_repair()
        if job is None:
            await asyncio.sleep(interval_seconds)
            continue
        try:
            await run_repair_job(job)
        except Exception as exc:
            logger.warning("Document repair failed job=%s doc=%s: %s", job["id"], job["doc_id"], exc)
            await fail_repair(job, str(exc), retryable=_is_retryable_error(exc))
        else:
            await complete_repair(job["id"])
