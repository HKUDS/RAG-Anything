from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str
    profile_id: str | None = None
    mode: str = "hybrid"
    use_multimodal: bool = False
    top_k: int | None = None
    chunk_top_k: int | None = None
    max_entity_tokens: int | None = None
    max_relation_tokens: int | None = None
    max_total_tokens: int | None = None
    enable_rerank: bool = True
    only_need_context: bool = False
    only_need_prompt: bool = False
    stream: bool = False


class SourceItem(BaseModel):
    document_id: str | None = None
    filename: str | None = None
    page_idx: int | None = None
    type: str | None = None
    score: float | None = None
    preview: str | None = None
    raw: dict[str, Any] | None = None


class AnswerBlock(BaseModel):
    type: str
    title: str | None = None
    content: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class MediaItem(BaseModel):
    id: str
    type: str
    title: str | None = None
    url: str | None = None
    path: str | None = None
    page_idx: int | None = None
    caption: str | None = None
    source_id: str | None = None
    raw: dict[str, Any] | None = None


class RelationStep(BaseModel):
    id: str
    type: str
    label: str
    description: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    answer_blocks: list[AnswerBlock] = Field(default_factory=list)
    media: list[MediaItem] = Field(default_factory=list)
    relation_trace: list[RelationStep] = Field(default_factory=list)
    raw: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
