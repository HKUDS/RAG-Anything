from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str
    mode: str = "hybrid"
    use_multimodal: bool = True
    top_k: int | None = None


class SourceItem(BaseModel):
    document_id: str | None = None
    filename: str | None = None
    page_idx: int | None = None
    type: str | None = None
    score: float | None = None
    preview: str | None = None
    raw: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    raw: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None

