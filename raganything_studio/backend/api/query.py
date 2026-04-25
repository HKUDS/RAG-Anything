from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.dependencies import get_rag_service
from raganything_studio.backend.schemas.query import QueryRequest, QueryResponse
from raganything_studio.backend.services.raganything_service import RAGAnythingService

router = APIRouter()


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

