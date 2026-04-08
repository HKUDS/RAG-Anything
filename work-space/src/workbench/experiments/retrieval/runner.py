from __future__ import annotations

from pathlib import Path

from src.config import ENV
from src.workbench.evaluation import RetrievalEvaluator
from src.workbench.experiments.base import RetrievalExperimentDefinition


class RetrievalExperimentRunner:
    def __init__(
        self,
        summary_report_file: Path | None = None,
        detail_report_file: Path | None = None,
    ):
        reports_dir = Path(ENV.output_base_dir) / "reports"
        self.evaluator = RetrievalEvaluator(
            summary_report_file=summary_report_file or reports_dir / "retrieval_benchmark_summary.csv",
            detail_report_file=detail_report_file or reports_dir / "retrieval_benchmark_details.jsonl",
        )

    async def run(self, exp_def: RetrievalExperimentDefinition) -> dict:
        return await self.evaluator.evaluate_experiment(exp_def.id)

    async def run_many(self, exp_defs: list[RetrievalExperimentDefinition]) -> list[dict]:
        return await self.evaluator.evaluate_many([exp.id for exp in exp_defs])
