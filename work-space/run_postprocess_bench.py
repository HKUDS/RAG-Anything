import argparse
import json
import logging

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.workbench.experiments.postprocessing.definitions import POSTPROCESSING_EXPERIMENTS
from src.workbench.experiments.postprocessing.runner import PostprocessingExperimentRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Postprocessing benchmark scaffold runner")
    parser.add_argument("--exp", type=str, help="Postprocessing experiment ID. If empty, run all scaffold entries.")
    args = parser.parse_args()

    runner = PostprocessingExperimentRunner()
    if args.exp:
        if args.exp not in POSTPROCESSING_EXPERIMENTS:
            raise SystemExit(f"Unknown postprocessing experiment '{args.exp}'. Available: {list(POSTPROCESSING_EXPERIMENTS.keys())}")
        print(json.dumps(runner.run(POSTPROCESSING_EXPERIMENTS[args.exp]), ensure_ascii=False, indent=2))
        return

    for exp_def in POSTPROCESSING_EXPERIMENTS.values():
        print(json.dumps(runner.run(exp_def), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
