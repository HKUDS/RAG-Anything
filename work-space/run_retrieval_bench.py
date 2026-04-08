import argparse
import asyncio
import logging
from pathlib import Path

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.workbench.experiments.retrieval.definitions import RETRIEVAL_EXPERIMENTS
from src.workbench.experiments.retrieval.runner import RetrievalExperimentRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


async def main():
    parser = argparse.ArgumentParser(description="Retrieval benchmark runner")
    parser.add_argument("--exp", type=str, help="Retrieval experiment ID. If empty, run all retrieval experiments.")
    parser.add_argument(
        "--fresh-report",
        action="store_true",
        help="Delete retrieval summary/detail reports before running.",
    )
    args = parser.parse_args()

    reports_dir = Path("benchmark_outputs/reports")
    if args.fresh_report:
        _remove_if_exists(reports_dir / "retrieval_benchmark_summary.csv")
        _remove_if_exists(reports_dir / "retrieval_benchmark_details.jsonl")

    runner = RetrievalExperimentRunner()
    if args.exp:
        if args.exp not in RETRIEVAL_EXPERIMENTS:
            raise SystemExit(f"Unknown retrieval experiment '{args.exp}'. Available: {list(RETRIEVAL_EXPERIMENTS.keys())}")
        result = await runner.run(RETRIEVAL_EXPERIMENTS[args.exp])
        logging.info("Completed retrieval benchmark: %s", result)
        return

    await runner.run_many(list(RETRIEVAL_EXPERIMENTS.values()))
    logging.info("Completed retrieval benchmark for %d experiments", len(RETRIEVAL_EXPERIMENTS))


if __name__ == "__main__":
    asyncio.run(main())
