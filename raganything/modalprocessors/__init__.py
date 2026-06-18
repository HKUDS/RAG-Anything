# -*- coding: utf-8 -*-
"""
RAG-Anything Modal Processors Sub-Package.

Layer: Core
Primary Responsibility: Multimodal content processors — image, table, equation,
    generic, plus context extraction infrastructure.
Key Dependencies: lightrag (LightRAG, storage), raganything.prompt, raganything.utils

Call chain: RAGAnything._initialize_processors() → ImageModalProcessor/TableModalProcessor/
    EquationModalProcessor/GenericModalProcessor → BaseModalProcessor._create_entity_and_chunk()
    → _process_chunk_for_extraction() → extract_entities() → merge_nodes_and_edges()

Sub-modules:
    context.py   — ContextConfig, ContextExtractor
    base.py      — BaseModalProcessor (JSON parsing, entity/chunk creation)
    image.py     — ImageModalProcessor (VLM image analysis)
    table.py     — TableModalProcessor (LLM table analysis)
    equation.py  — EquationModalProcessor (LLM equation analysis)
    generic.py   — GenericModalProcessor (fallback for any content type)
"""

from raganything.modalprocessors.context import ContextConfig, ContextExtractor
from raganything.modalprocessors.base import BaseModalProcessor
from raganything.modalprocessors.image import ImageModalProcessor
from raganything.modalprocessors.table import TableModalProcessor
from raganything.modalprocessors.equation import EquationModalProcessor
from raganything.modalprocessors.generic import GenericModalProcessor

__all__ = [
    "ContextConfig",
    "ContextExtractor",
    "BaseModalProcessor",
    "ImageModalProcessor",
    "TableModalProcessor",
    "EquationModalProcessor",
    "GenericModalProcessor",
]
