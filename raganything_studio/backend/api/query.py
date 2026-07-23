from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.dependencies import get_rag_service, settings as studio_settings
from raganything_studio.backend.schemas.query import QueryRequest, QueryResponse
from raganything_studio.backend.services.raganything_service import RAGAnythingService

router = APIRouter()
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    rag_service: RAGAnythingService = Depends(get_rag_service),
) -> QueryResponse:
    if not request.question.strip():
        raise api_error(
            "QUERY_FAILED",
            "Question must not be empty",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return await rag_service.query(request)


@router.get("/media")
async def get_query_media(path: str = Query(...)) -> FileResponse:
    media_path = Path(path).expanduser()
    if media_path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=404, detail="Unsupported media type")

    try:
        resolved = media_path.resolve()
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid media path") from None

    allowed_roots = [
        studio_settings.data_dir.resolve(),
        studio_settings.output_dir.resolve(),
        studio_settings.working_dir.resolve(),
        studio_settings.upload_dir.resolve(),
    ]
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise HTTPException(status_code=404, detail="Media path is outside Studio storage")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Media not found")

    return FileResponse(
        resolved,
        media_type=f"image/{resolved.suffix.lstrip('.').lower()}",
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
