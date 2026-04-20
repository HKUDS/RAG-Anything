import argparse
import asyncio
import logging
from pathlib import Path

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


async def main():
    parser = argparse.ArgumentParser(description="Graph pruning benchmark runner")
    parser.add_argument("--exp", type=str, help="Pruning experiment ID. If empty, run all pruning experiments.")
    parser.add_argument(
        "--base-exp",
        type=str,
        help="Run all pruning experiments whose base pipeline experiment matches this ID.",
    )
    parser.add_argument(
        "--fresh-report",
        action="store_true",
        help="Delete pruning summary/detail reports before running.",
    )
    args = parser.parse_args()

    from src.workbench.experiments.pruning.definitions import PRUNING_EXPERIMENTS
    from src.workbench.experiments.pruning.runner import PruningExperimentRunner

    reports_dir = Path("benchmark_outputs/reports")
    if args.fresh_report:
        _remove_if_exists(reports_dir / "pruning_benchmark_summary.csv")
        _remove_if_exists(reports_dir / "pruning_benchmark_details.jsonl")

    runner = PruningExperimentRunner()
    if args.exp:
        if args.exp not in PRUNING_EXPERIMENTS:
            raise SystemExit(f"Unknown pruning experiment '{args.exp}'. Available: {list(PRUNING_EXPERIMENTS.keys())}")
        result = await runner.run(PRUNING_EXPERIMENTS[args.exp])
        logging.info("Completed pruning benchmark: %s", result)
        return

    if args.base_exp:
        selected = [
            exp_def
            for exp_def in PRUNING_EXPERIMENTS.values()
            if exp_def.base_experiment_id == args.base_exp
        ]
        if not selected:
            available = sorted({exp_def.base_experiment_id for exp_def in PRUNING_EXPERIMENTS.values()})
            raise SystemExit(
                f"Unknown base pipeline experiment '{args.base_exp}'. Available base experiments: {available}"
            )
        await runner.run_many(selected)
        logging.info(
            "Completed pruning benchmark for %d experiments with base pipeline %s",
            len(selected),
            args.base_exp,
        )
        return

    await runner.run_many(list(PRUNING_EXPERIMENTS.values()))
    logging.info("Completed pruning benchmark for %d experiments", len(PRUNING_EXPERIMENTS))


if __name__ == "__main__":
    asyncio.run(main())
