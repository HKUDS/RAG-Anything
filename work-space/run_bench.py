import argparse
import asyncio
import logging

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.experiments.pipeline.runner import PipelineBenchmarkRunner
from src.workbench.logging_utils import configure_workbench_logging


async def main():
    parser = argparse.ArgumentParser(description="RAG-Anything pipeline benchmark runner")
    parser.add_argument("--exp", type=str, help="Pipeline experiment ID. If empty, run all pipeline experiments.")
    parser.add_argument(
        "--fresh-run",
        action="store_true",
        help="Clear benchmark_outputs/<exp>/rag_storage and parser_output before the run.",
    )
    parser.add_argument(
        "--fresh-report-exp",
        action="store_true",
        help="Remove existing pipeline report rows for --exp before appending new rows.",
    )
    args = parser.parse_args()
    configure_workbench_logging("run_bench", args.exp or "all")

    runner = PipelineBenchmarkRunner()
    if args.fresh_report_exp and not args.exp:
        raise SystemExit("--fresh-report-exp requires --exp so completed experiments are not touched accidentally.")

    if args.exp:
        if args.exp not in PIPELINE_EXPERIMENTS:
            raise SystemExit(f"Unknown pipeline experiment '{args.exp}'. Available: {list(PIPELINE_EXPERIMENTS.keys())}")
        if args.fresh_report_exp:
            runner.clear_report_rows(args.exp)
        await runner.run(PIPELINE_EXPERIMENTS[args.exp], fresh_run=args.fresh_run)
        return

    for exp_id, exp_def in PIPELINE_EXPERIMENTS.items():
        if getattr(exp_def, "legacy_alias", False):
            continue
        await runner.run(exp_def, fresh_run=args.fresh_run)


if __name__ == "__main__":
    asyncio.run(main())
