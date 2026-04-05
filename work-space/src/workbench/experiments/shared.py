from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from src.config import ENV


@dataclass(frozen=True)
class ParserPreset:
    key: str
    parser: str
    parse_method: str = "auto"
    parser_kwargs: Dict[str, Any] = field(default_factory=dict)
    title: str = ""
    notes: str = ""


PARSER_PRESETS: dict[str, ParserPreset] = {
    "mineru": ParserPreset(
        key="mineru",
        parser="mineru",
        parse_method="auto",
        parser_kwargs={
            "backend": ENV.mineru_backend,
            "device": ENV.mineru_device,
            "lang": ENV.mineru_lang,
            "source": ENV.mineru_source,
        },
        title="MinerU",
        notes="Reference multimodal parser baseline pinned to explicit MinerU GPU settings for fair parser throughput comparisons.",
    ),
    "docling": ParserPreset(
        key="docling",
        parser="docling",
        parse_method="auto",
        parser_kwargs={
            "device": ENV.docling_device,
            "ocr_lang": ENV.docling_ocr_lang,
        },
        title="Docling",
        notes="Balanced parser candidate pinned to explicit Docling GPU settings for fair parser throughput comparisons.",
    ),
    "kreuzberg": ParserPreset(
        key="kreuzberg",
        parser="kreuzberg",
        parse_method="auto",
        parser_kwargs={
            "extract_pages": True,
            "extract_images": True,
            "extract_tables": True,
            "result_format": "element_based",
            "output_format": "markdown",
            "include_document_structure": True,
            "ocr_backend": ENV.kreuzberg_ocr_backend,
            "ocr_languages": [ENV.kreuzberg_ocr_language],
            "ocr_use_gpu": ENV.kreuzberg_ocr_use_gpu,
            "ocr_model_tier": ENV.kreuzberg_ocr_model_tier,
            "use_cache": False,
        },
        title="Kreuzberg",
        notes="Fast parser preset using Kreuzberg with PaddleOCR for OCR-dependent parsing on the same benchmark dataset.",
    ),
}


__all__ = ["ParserPreset", "PARSER_PRESETS"]
