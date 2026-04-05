import argparse
import json
import logging

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.workbench.experiments.retrieval.definitions import RETRIEVAL_EXPERIMENTS
from src.workbench.experiments.retrieval.runner import RetrievalExperimentRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Retrieval / reranker benchmark scaffold runner")
    parser.add_argument("--exp", type=str, help="Retrieval experiment ID. If empty, run all retrieval scaffold entries.")
    args = parser.parse_args()

    runner = RetrievalExperimentRunner()
    if args.exp:
        if args.exp not in RETRIEVAL_EXPERIMENTS:
            raise SystemExit(f"Unknown retrieval experiment '{args.exp}'. Available: {list(RETRIEVAL_EXPERIMENTS.keys())}")
        print(json.dumps(runner.run(RETRIEVAL_EXPERIMENTS[args.exp]), ensure_ascii=False, indent=2))
        return

    for exp_def in RETRIEVAL_EXPERIMENTS.values():
        print(json.dumps(runner.run(exp_def), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
