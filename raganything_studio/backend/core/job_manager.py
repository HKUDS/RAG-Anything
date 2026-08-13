from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import status

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.job import JobRecord, JobStage, JobStatus


class JobManager:
    """Process-local job manager for Studio MVP."""

    def __init__(self, jobs_file: Path | None = None) -> None:
        self._jobs_file = jobs_file
        self._jobs: dict[str, JobRecord] = {}
        self._lock = RLock()
        self._load()

    def create_job(self, document_id: str | None = None) -> JobRecord:
        job_id = f"job_{uuid4().hex}"
        now = _utc_now()
        job = JobRecord(
            id=job_id,
            document_id=document_id,
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            progress=0.0,
            message="Queued",
            logs=[],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job_id] = job
            self.append_log(job_id, f"Created job {job_id}")
            return self._jobs[job_id]

    def latest_job_id_for_document(self, document_id: str) -> str | None:
        """Return the most recently created job ID for the given document, or None."""
        job = self.latest_job_for_document(document_id)
        return job.id if job is not None else None

    def latest_job_for_document(self, document_id: str) -> JobRecord | None:
        """Return the most recently created job for the given document, or None."""
        with self._lock:
            matching = [
                job for job in self._jobs.values()
                if job.document_id == document_id
            ]
        if not matching:
            return None
        return max(matching, key=lambda j: j.created_at)

    def get_job(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise api_error(
                    "JOB_NOT_FOUND",
                    f"Job {job_id} was not found",
                    status.HTTP_404_NOT_FOUND,
                )
            return job

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self.get_job(job_id)
            logs = [*job.logs, f"[{_clock_time()}] {message}"]
            self._jobs[job_id] = _copy_model(
                job, {"logs": logs, "updated_at": _utc_now()}
            )
            self._save()

    def update_progress(
        self,
        job_id: str,
        stage: JobStage,
        progress: float,
        message: str,
    ) -> None:
        with self._lock:
            job = self.get_job(job_id)
            self._jobs[job_id] = _copy_model(
                job,
                {
                    "status": JobStatus.RUNNING,
                    "stage": stage,
                    "progress": max(0.0, min(1.0, progress)),
                    "message": message,
                    "updated_at": _utc_now(),
                }
            )
            self.append_log(job_id, message)

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self.get_job(job_id)
            self._jobs[job_id] = _copy_model(
                job,
                {
                    "status": JobStatus.FAILED,
                    "stage": JobStage.FAILED,
                    "progress": job.progress,
                    "message": "Failed",
                    "error": error,
                    "updated_at": _utc_now(),
                }
            )
            self.append_log(job_id, "Failed")

    def update_metrics(
        self,
        job_id: str,
        *,
        stage_durations: dict[str, float] | None = None,
        api_call_counts: dict[str, int] | None = None,
        cache_hits: dict[str, int] | None = None,
        cache_misses: dict[str, int] | None = None,
    ) -> None:
        with self._lock:
            job = self.get_job(job_id)
            self._jobs[job_id] = _copy_model(
                job,
                {
                    "stage_durations": _merge_numeric_dicts(
                        job.stage_durations, stage_durations
                    ),
                    "api_call_counts": _merge_int_dicts(
                        job.api_call_counts, api_call_counts
                    ),
                    "cache_hits": _merge_int_dicts(job.cache_hits, cache_hits),
                    "cache_misses": _merge_int_dicts(job.cache_misses, cache_misses),
                    "updated_at": _utc_now(),
                },
            )
            self._save()

    def mark_succeeded(self, job_id: str) -> None:
        with self._lock:
            job = self.get_job(job_id)
            self._jobs[job_id] = _copy_model(
                job,
                {
                    "status": JobStatus.SUCCEEDED,
                    "stage": JobStage.DONE,
                    "progress": 1.0,
                    "message": "Document processing completed",
                    "updated_at": _utc_now(),
                }
            )
            self.append_log(job_id, "Document processing completed")

    def _load(self) -> None:
        if self._jobs_file is None or not self._jobs_file.exists():
            return
        try:
            raw = json.loads(self._jobs_file.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, list):
            return

        changed = False
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                job = (
                    JobRecord.model_validate(item)
                    if hasattr(JobRecord, "model_validate")
                    else JobRecord.parse_obj(item)
                )
            except Exception:
                continue
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                job = _copy_model(
                    job,
                    {
                        "status": JobStatus.FAILED,
                        "stage": JobStage.FAILED,
                        "message": "Interrupted by server restart",
                        "error": "Interrupted by server restart",
                        "updated_at": _utc_now(),
                    },
                )
                changed = True
            self._jobs[job.id] = job

        if changed:
            self._save()

    def _save(self) -> None:
        if self._jobs_file is None:
            return
        self._jobs_file.parent.mkdir(parents=True, exist_ok=True)
        data = [
            job.model_dump(mode="json") if hasattr(job, "model_dump")
            else json.loads(job.json())
            for job in self._jobs.values()
        ]
        tmp = self._jobs_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        tmp.replace(self._jobs_file)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clock_time() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _copy_model(job: JobRecord, update: dict) -> JobRecord:
    if hasattr(job, "model_copy"):
        return job.model_copy(update=update)
    return job.copy(update=update)


def _merge_numeric_dicts(
    current: dict[str, float], update: dict[str, float] | None
) -> dict[str, float]:
    merged = dict(current)
    for key, value in (update or {}).items():
        merged[key] = round(float(value), 3)
    return merged


def _merge_int_dicts(
    current: dict[str, int], update: dict[str, int] | None
) -> dict[str, int]:
    merged = dict(current)
    for key, value in (update or {}).items():
        merged[key] = int(value)
    return merged
