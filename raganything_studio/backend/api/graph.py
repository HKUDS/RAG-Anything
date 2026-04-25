from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.dependencies import get_rag_service, get_settings_store
from raganything_studio.backend.schemas.graph import GraphLabelsResponse, KnowledgeGraphResponse
from raganything_studio.backend.services.raganything_service import RAGAnythingService

router = APIRouter()


@router.get("/labels", response_model=GraphLabelsResponse)
async def get_graph_labels(
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> GraphLabelsResponse:
    settings = settings_store.get()
    try:
        rag = await rag_service.get_rag(profile_id=profile_id or settings.active_profile_id)
        initializer = getattr(rag, "_ensure_lightrag_initialized", None)
        if callable(initializer):
            await initializer()
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None:
            return GraphLabelsResponse(labels=[])
        labels = await lightrag.get_graph_labels()
        return GraphLabelsResponse(labels=list(labels) if labels else [])
    except Exception as exc:
        raise api_error(
            "GRAPH_FETCH_FAILED",
            f"Failed to fetch graph labels: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


@router.get("/subgraph", response_model=KnowledgeGraphResponse)
async def get_subgraph(
    node_label: str = Query(...),
    max_depth: int = Query(default=3, ge=1, le=6),
    max_nodes: int = Query(default=200, ge=1, le=1000),
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraphResponse:
    settings = settings_store.get()
    try:
        rag = await rag_service.get_rag(profile_id=profile_id or settings.active_profile_id)
        initializer = getattr(rag, "_ensure_lightrag_initialized", None)
        if callable(initializer):
            await initializer()
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None:
            return KnowledgeGraphResponse(nodes=[], edges=[], is_truncated=False)
        kg = await lightrag.get_knowledge_graph(
            node_label=node_label,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        return KnowledgeGraphResponse(
            nodes=[
                {"id": n.id, "labels": n.labels, "properties": n.properties}
                for n in kg.nodes
            ],
            edges=[
                {
                    "id": e.id,
                    "type": e.type,
                    "source": e.source,
                    "target": e.target,
                    "properties": e.properties,
                }
                for e in kg.edges
            ],
            is_truncated=kg.is_truncated,
        )
    except Exception as exc:
        raise api_error(
            "GRAPH_FETCH_FAILED",
            f"Failed to fetch knowledge graph: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc
