import argparse
import asyncio
import logging
from pathlib import Path

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.config import ENV
from src.workbench.experiments.parser.definitions import PARSER_EXPERIMENTS
from src.workbench.experiments.parser.runner import ParserBenchmarkRunner
import raganything
from src.workbench.logging_utils import configure_workbench_logging


async def main():
    parser = argparse.ArgumentParser(description="Extract-only benchmark for parser comparisons")
    parser.add_argument("--exp", type=str, help="Parser experiment ID. If empty, run all parser experiments.")
    parser.add_argument(
        "--fresh-run",
        action="store_true",
        help="Clear benchmark_outputs/extract_benchmark/<exp_id> before each run.",
    )
    parser.add_argument(
        "--fresh-parser-cache",
        action="store_true",
        help="Clear known parser caches before run (currently relevant to Kreuzberg).",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=ENV.parser_benchmark_input_dir,
        help="Input directory containing parser benchmark documents",
    )
    parser.add_argument(
        "--detail-report",
        type=str,
        default=str(Path(ENV.output_base_dir) / "reports" / "parser_benchmark_details.csv"),
        help="Per-file parser benchmark CSV path",
    )
    parser.add_argument(
        "--summary-report",
        type=str,
        default=str(Path(ENV.output_base_dir) / "reports" / "parser_benchmark_summary.csv"),
        help="Per-experiment parser benchmark CSV path",
    )
    args = parser.parse_args()
    configure_workbench_logging("run_extract_bench", args.exp or "all")
    logging.getLogger(__name__).info("Using raganything from: %s", getattr(raganything, "__file__", "unknown"))

    input_dir = Path(args.input)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    runner = ParserBenchmarkRunner(
        detail_report_file=Path(args.detail_report),
        summary_report_file=Path(args.summary_report),
    )
    if args.exp:
        if args.exp not in PARSER_EXPERIMENTS:
            raise SystemExit(f"Unknown parser experiment '{args.exp}'. Available: {list(PARSER_EXPERIMENTS.keys())}")
        await runner.run(
            PARSER_EXPERIMENTS[args.exp],
            input_dir,
            fresh_run=args.fresh_run,
            fresh_parser_cache=args.fresh_parser_cache,
        )
        return

    for exp_def in PARSER_EXPERIMENTS.values():
        await runner.run(
            exp_def,
            input_dir,
            fresh_run=args.fresh_run,
            fresh_parser_cache=args.fresh_parser_cache,
        )


if __name__ == "__main__":
    asyncio.run(main())
