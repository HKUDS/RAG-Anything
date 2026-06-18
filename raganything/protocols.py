# -*- coding: utf-8 -*-
"""
RAG-Anything Mixin Protocols — Explicit Attribute Contracts.

Layer: Core
Primary Responsibility: Define static-type-checkable contracts (Protocol classes)
    that document what attributes each Mixin expects from the RAGAnything dataclass.
    Zero runtime overhead — used by mypy/pyright and AI tools for context.
Key Dependencies: raganything.config (RAGAnythingConfig), lightrag (LightRAG)

Why: Mixins like QueryMixin, ProcessorMixin, BatchMixin rely on implicit
    attributes (self.config, self.lightrag, self.logger). Without explicit
    contracts, AI tools cannot infer the dependency graph from code alone.
    These Protocol classes solve that without runtime changes.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Protocol


class RAGCoreProtocol(Protocol):
    """Core attributes every RAGAnything mixin depends on.

    These are defined on the RAGAnything dataclass in raganything.raganything.
    """

    config: Any  # RAGAnythingConfig — avoids import cycle
    lightrag: Any  # LightRAG — avoids import cycle
    logger: logging.Logger
    working_dir: str
    llm_model_func: Optional[Callable]
    vision_model_func: Optional[Callable]
    embedding_func: Optional[Callable]
    lightrag_kwargs: Dict[str, Any]


class QueryCapable(RAGCoreProtocol, Protocol):
    """Attributes required by QueryMixin (raganything.query).

    QueryMixin expects the full RAG core plus hybrid_search_engine and
    conversation-related state.
    """

    hybrid_search_engine: Optional[Any]
    parse_cache: Optional[Any]
    multimodal_status_cache: Optional[Any]
    modal_processors: Dict[str, Any]
    context_extractor: Optional[Any]
    config: Any  # RAGAnythingConfig with query defaults

    def _initialize_processors(self) -> None: ...
    async def _ensure_lightrag_initialized(self) -> dict: ...


class ProcessorCapable(RAGCoreProtocol, Protocol):
    """Attributes required by ProcessorMixin and its sub-mixins.

    ProcessorMixin = DocProcessor + ChunkProcessor + EmbedProcessor
                    + BatchProcessor + MultimodalProcessor
    """

    doc_parser: Any
    parse_cache: Optional[Any]
    multimodal_status_cache: Optional[Any]
    modal_processors: Dict[str, Any]
    context_extractor: Optional[Any]
    hybrid_search_engine: Optional[Any]
    callback_manager: Any
    _parser_installation_checked: bool
    config: Any  # RAGAnythingConfig

    def _create_context_config(self) -> Any: ...
    def _create_context_extractor(self) -> Any: ...
    def _initialize_processors(self) -> None: ...
    async def _ensure_lightrag_initialized(self) -> dict: ...
    async def finalize_storages(self) -> None: ...


class BatchCapable(RAGCoreProtocol, Protocol):
    """Attributes required by BatchMixin (raganything.batch)."""

    doc_parser: Any
    callback_manager: Any
    config: Any  # RAGAnythingConfig

    def _create_context_config(self) -> Any: ...
    async def _ensure_lightrag_initialized(self) -> dict: ...
