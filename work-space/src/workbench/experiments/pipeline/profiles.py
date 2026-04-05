from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from src.prompts import (
    MEDICAL_ENTITY_TYPES,
    MEDICAL_TABLE_PROMPT,
    MEDICAL_VISION_PROMPT,
)


@dataclass(frozen=True)
class PipelineProfile:
    key: str
    title: str
    description: str
    lightrag_kwargs: Dict[str, Any] = field(default_factory=dict)
    raganything_kwargs: Dict[str, Any] = field(default_factory=dict)
    custom_prompts: Dict[str, str] = field(default_factory=dict)
    use_gliner: bool = False
    gliner_labels: list = field(default_factory=list)
    notes: str = ""


PIPELINE_PROFILES = {
    "default": PipelineProfile(
        key="default",
        title="Default",
        description="Core RAGAnything / LightRAG defaults with no prompt intervention.",
        notes="Reference baseline for parser and end-to-end comparisons.",
    ),
    "medical": PipelineProfile(
        key="medical",
        title="Medical Domain",
        description="Domain-scoped pipeline using medical prompt shaping and entity types.",
        lightrag_kwargs={
            "chunk_token_size": 2400,
            "entity_extract_max_gleaning": 0,
            "addon_params": {"entity_types": MEDICAL_ENTITY_TYPES},
        },
        custom_prompts={
            "vision_prompt_with_context": MEDICAL_VISION_PROMPT,
            "table_prompt_with_context": MEDICAL_TABLE_PROMPT,
            "generic_prompt_with_context": "Act as a Medical Expert. Analyze this content for clinical relevance...",
        },
        notes="Biases extraction toward medically meaningful concepts and evidence.",
    ),
    "hybrid_gliner": PipelineProfile(
        key="hybrid_gliner",
        title="Hybrid GLiNER",
        description="GLiNER-assisted entity extraction with LLM relation extraction.",
        use_gliner=True,
        gliner_labels=list(MEDICAL_ENTITY_TYPES),
        lightrag_kwargs={
            "chunk_token_size": 2400,
            "entity_extract_max_gleaning": 0,
        },
        custom_prompts={
            "vision_prompt_with_context": "Act as Medical Researcher. Return JSON: {detailed_description: 'Summary (max 20 words)', entity_info: {entity_name: 'Image', summary: 'N/A'}}",
        },
        notes="Experimental pipeline for replacing part of text extraction with a lighter entity model.",
    ),
}
