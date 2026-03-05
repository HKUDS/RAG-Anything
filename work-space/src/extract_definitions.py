from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class ExtractExperimentDef:
    id: str
    description: str
    parser: str = "mineru"
    parse_method: str = "auto"
    parser_kwargs: Dict[str, Any] = field(default_factory=dict)


EXTRACT_EXPERIMENTS = {
    # Keep ONLY one MinerU default multimodal setting for fair parser comparison.
    "ext1_mineru_default_multimodal": ExtractExperimentDef(
        id="ext1_mineru_default_multimodal",
        description="MinerU default multimodal (auto + default settings)",
        parser="mineru",
        parse_method="auto",
    ),
    "ext2_docling_default": ExtractExperimentDef(
        id="ext2_docling_default",
        description="Docling default (PDF/Office/HTML)",
        parser="docling",
        parse_method="auto",
    ),
    "ext3_kreuzberg_default": ExtractExperimentDef(
        id="ext3_kreuzberg_default",
        description="Kreuzberg multimodal preset (pages + images + tables + element-based output)",
        parser="kreuzberg",
        parse_method="auto",
        parser_kwargs={
            "extract_pages": True,
            "extract_images": True,
            "extract_tables": True,
            "result_format": "element_based",
            "ocr_tesseract_enable_table_detection": True,
            "use_cache": False,
        },
    ),
    "ext4_marker_default": ExtractExperimentDef(
        id="ext4_marker_default",
        description="Marker default (VLM-based PDF conversion)",
        parser="marker",
        parse_method="auto",
    ),
    "ext5_marker_ocr": ExtractExperimentDef(
        id="ext5_marker_ocr",
        description="Marker OCR mode",
        parser="marker",
        parse_method="ocr",
    ),
}
