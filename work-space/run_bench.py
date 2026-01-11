import asyncio
import logging
import argparse
from src.definitions import EXPERIMENTS
from src.engine import ExperimentEngine

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

async def main():
    parser = argparse.ArgumentParser(description="RAG-Anything Auto Benchmark")
    parser.add_argument("--exp", type=str, help="Experiment ID to run (e.g., exp1_baseline). If empty, run all.")
    args = parser.parse_args()

    engine = ExperimentEngine()

    if args.exp:
        # Run specific experiment
        if args.exp in EXPERIMENTS:
            await engine.run_experiment(EXPERIMENTS[args.exp])
        else:
            print(f"❌ Experiment '{args.exp}' not found. Available: {list(EXPERIMENTS.keys())}")
    else:
        # Run ALL experiments sequentially
        print("🚀 Running ALL experiments...")
        for exp_id, exp_def in EXPERIMENTS.items():
            await engine.run_experiment(exp_def)

if __name__ == "__main__":
    asyncio.run(main())