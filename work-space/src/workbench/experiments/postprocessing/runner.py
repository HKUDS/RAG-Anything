from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from src.config import ENV
from src.workbench.experiments.base import PostprocessingExperimentDefinition
from src.workbench.observability import JSONLReportWriter


class PostprocessingExperimentRunner:
    def __init__(self, report_file: Path | None = None):
        self.report_writer = JSONLReportWriter(
            Path(report_file or Path(ENV.output_base_dir) / "reports" / "postprocessing_benchmark.jsonl")
        )

    def run(self, exp_def: PostprocessingExperimentDefinition) -> dict:
        result = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "scaffold",
            "message": (
                "Postprocessing benchmarking module scaffold created. "
                "Implement answer cleanup / compression evaluation next."
            ),
            **asdict(exp_def),
        }
        self.report_writer.append(result)
        return result
