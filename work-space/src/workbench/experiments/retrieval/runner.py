from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from src.config import ENV
from src.workbench.experiments.base import RetrievalExperimentDefinition
from src.workbench.observability import JSONLReportWriter


class RetrievalExperimentRunner:
    def __init__(self, report_file: Path | None = None):
        self.report_writer = JSONLReportWriter(
            Path(report_file or Path(ENV.output_base_dir) / "reports" / "retrieval_benchmark.jsonl")
        )

    def run(self, exp_def: RetrievalExperimentDefinition) -> dict:
        result = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "scaffold",
            "message": (
                "Retrieval benchmarking module scaffold created. "
                "Implement labeled or LLM-judged evidence evaluation next."
            ),
            **asdict(exp_def),
        }
        self.report_writer.append(result)
        return result
