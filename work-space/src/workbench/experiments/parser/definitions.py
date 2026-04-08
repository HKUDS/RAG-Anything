from __future__ import annotations

from src.workbench.experiments.base import ParserBenchmarkExperimentDefinition
from src.workbench.experiments.shared import PARSER_PRESETS
from src.workbench.metrics import PARSER_METRIC_PLAN

PARSER_EXPERIMENTS: dict[str, ParserBenchmarkExperimentDefinition] = {}

for index, parser_key in enumerate(["mineru", "docling", "kreuzberg"], start=1):
    preset = PARSER_PRESETS[parser_key]
    exp_id = f"ext{index}_{parser_key}_default"
    if parser_key == "mineru":
        exp_id = "ext1_mineru_default_multimodal"
    elif parser_key == "docling":
        exp_id = "ext2_docling_default"
    elif parser_key == "kreuzberg":
        exp_id = "ext3_kreuzberg_paddleocr"

    PARSER_EXPERIMENTS[exp_id] = ParserBenchmarkExperimentDefinition(
        id=exp_id,
        description=f"{preset.title} parser benchmark ({preset.parse_method})",
        category="parser",
        metric_plan=PARSER_METRIC_PLAN,
        parser=preset.parser,
        parse_method=preset.parse_method,
        parser_kwargs=dict(preset.parser_kwargs),
        notes=preset.notes,
        tags=["parser", parser_key],
    )

cloud_preset = PARSER_PRESETS["mineru_cloud_vlm"]
# PARSER_EXPERIMENTS["ext4_mineru_cloud_vlm"] = ParserBenchmarkExperimentDefinition(
#     id="ext4_mineru_cloud_vlm",
#     description="MinerU official cloud API parser benchmark (vlm)",
#     category="parser",
#     metric_plan=PARSER_METRIC_PLAN,
#     parser=cloud_preset.parser,
#     parse_method=cloud_preset.parse_method,
#     parser_kwargs=dict(cloud_preset.parser_kwargs),
#     notes=cloud_preset.notes,
#     tags=["parser", "mineru", "cloud", "api", "vlm"],
# )
