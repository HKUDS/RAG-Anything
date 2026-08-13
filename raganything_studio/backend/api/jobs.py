from __future__ import annotations

from fastapi import APIRouter, Depends

from raganything_studio.backend.core.job_manager import JobManager
from raganything_studio.backend.dependencies import get_job_manager
from raganything_studio.backend.schemas.job import JobRecord

router = APIRouter()


@router.get("/{job_id}", response_model=JobRecord)
async def get_job(
    job_id: str,
    job_manager: JobManager = Depends(get_job_manager),
) -> JobRecord:
    return job_manager.get_job(job_id)

