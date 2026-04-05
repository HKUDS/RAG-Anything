import argparse
import asyncio
import logging

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.experiments.pipeline.runner import PipelineBenchmarkRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


async def main():
    parser = argparse.ArgumentParser(description="RAG-Anything pipeline benchmark runner")
    parser.add_argument("--exp", type=str, help="Pipeline experiment ID. If empty, run all pipeline experiments.")
    parser.add_argument(
        "--fresh-run",
        action="store_true",
        help="Clear benchmark_outputs/<exp>/rag_storage and parser_output before the run.",
    )
    args = parser.parse_args()

    runner = PipelineBenchmarkRunner()
    if args.exp:
        if args.exp not in PIPELINE_EXPERIMENTS:
            raise SystemExit(f"Unknown pipeline experiment '{args.exp}'. Available: {list(PIPELINE_EXPERIMENTS.keys())}")
        await runner.run(PIPELINE_EXPERIMENTS[args.exp], fresh_run=args.fresh_run)
        return

    for exp_id, exp_def in PIPELINE_EXPERIMENTS.items():
        if getattr(exp_def, "legacy_alias", False):
            continue
        await runner.run(exp_def, fresh_run=args.fresh_run)


if __name__ == "__main__":
    asyncio.run(main())
