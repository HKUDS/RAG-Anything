from __future__ import annotations

from pathlib import Path

from src.config import ENV
from src.workbench.evaluation import PruningBenchmarkEvaluator
from src.workbench.experiments.base import PruningExperimentDefinition


class PruningExperimentRunner:
    def __init__(
        self,
        summary_report_file: Path | None = None,
        detail_report_file: Path | None = None,
        artifact_root: Path | None = None,
    ):
        reports_dir = Path(ENV.output_base_dir) / "reports"
        self.evaluator = PruningBenchmarkEvaluator(
            summary_report_file=summary_report_file or reports_dir / "pruning_benchmark_summary.csv",
            detail_report_file=detail_report_file or reports_dir / "pruning_benchmark_details.jsonl",
            artifact_root=artifact_root or Path(ENV.output_base_dir) / "pruning_benchmark",
        )

    async def run(self, exp_def: PruningExperimentDefinition) -> dict:
        return await self.evaluator.evaluate_experiment(exp_def.id)

    async def run_many(self, exp_defs: list[PruningExperimentDefinition]) -> list[dict]:
        return await self.evaluator.evaluate_many([exp.id for exp in exp_defs])
