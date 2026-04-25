from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GraphLabelsResponse(BaseModel):
    labels: list[str]


class GraphNode(BaseModel):
    id: str
    labels: list[str]
    properties: dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    type: str | None
    source: str
    target: str
    properties: dict[str, Any]


class KnowledgeGraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    is_truncated: bool
