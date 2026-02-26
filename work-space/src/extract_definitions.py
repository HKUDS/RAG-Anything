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
    "ext1_mineru_balanced": ExtractExperimentDef(
        id="ext1_mineru_balanced",
        description="MinerU balanced (auto + default settings)",
        parser="mineru",
        parse_method="auto",
    ),
    "ext2_mineru_fast_no_table_formula": ExtractExperimentDef(
        id="ext2_mineru_fast_no_table_formula",
        description="MinerU fast: disable table + formula",
        parser="mineru",
        parse_method="auto",
        parser_kwargs={"table": False, "formula": False},
    ),
    "ext3_mineru_txt_only": ExtractExperimentDef(
        id="ext3_mineru_txt_only",
        description="MinerU txt-only (fast for digital PDFs)",
        parser="mineru",
        parse_method="txt",
    ),
    "ext4_mineru_ocr": ExtractExperimentDef(
        id="ext4_mineru_ocr",
        description="MinerU OCR-only (scanned PDFs/images)",
        parser="mineru",
        parse_method="ocr",
    ),
    "ext5_docling_default": ExtractExperimentDef(
        id="ext5_docling_default",
        description="Docling default (PDF/Office/HTML)",
        parser="docling",
        parse_method="auto",
    ),
    "ext6_kreuzberg_default": ExtractExperimentDef(
        id="ext6_kreuzberg_default",
        description="Kreuzberg default (multilingual OCR, structured output)",
        parser="kreuzberg",
        parse_method="auto",
    ),
    "ext7_marker_default": ExtractExperimentDef(
        id="ext7_marker_default",
        description="Marker default (VLM-based PDF conversion)",
        parser="marker",
        parse_method="auto",
    ),
    "ext8_marker_ocr": ExtractExperimentDef(
        id="ext8_marker_ocr",
        description="Marker OCR mode",
        parser="marker",
        parse_method="ocr",
    ),
}
