from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from fastapi import status

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.job import JobRecord, JobStage, JobStatus


class JobManager:
    """Process-local job manager for Studio MVP."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = RLock()

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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clock_time() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _copy_model(job: JobRecord, update: dict) -> JobRecord:
    if hasattr(job, "model_copy"):
        return job.model_copy(update=update)
    return job.copy(update=update)
