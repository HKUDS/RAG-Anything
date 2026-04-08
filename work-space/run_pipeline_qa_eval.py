import argparse
import asyncio
import logging
from pathlib import Path

from _bootstrap import bootstrap_project_root

bootstrap_project_root()

from src.config import ENV
from src.workbench.evaluation import PipelineQAEvaluator
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


async def main():
    parser = argparse.ArgumentParser(description="Pipeline QA phase-2 evaluator")
    parser.add_argument("--exp", type=str, help="Pipeline experiment ID. If empty, evaluate all pipeline experiments.")
    parser.add_argument("--query-mode", type=str, default="mix", help="Query mode passed to RAGAnything. Default: mix")
    parser.add_argument("--questions-per-doc", type=int, default=10, help="Number of generated gold questions per document. Default: 10")
    parser.add_argument("--regenerate-gold", action="store_true", help="Regenerate gold QA question sets with OpenAI even if cached.")
    parser.add_argument("--rejudge", action="store_true", help="Re-run OpenAI judging even if cached judge outputs exist.")
    parser.add_argument(
        "--fresh-report",
        action="store_true",
        help="Delete pipeline QA summary/detail report files before evaluation.",
    )
    args = parser.parse_args()

    reports_dir = Path(ENV.output_base_dir) / "reports"
    if args.fresh_report:
        _remove_if_exists(reports_dir / "pipeline_qa_summary.csv")
        _remove_if_exists(reports_dir / "pipeline_qa_details.jsonl")

    evaluator = PipelineQAEvaluator()
    if args.exp:
        if args.exp not in PIPELINE_EXPERIMENTS:
            raise SystemExit(
                f"Unknown pipeline experiment '{args.exp}'. Available: {list(PIPELINE_EXPERIMENTS.keys())}"
            )
        summary = await evaluator.evaluate_experiment(
            args.exp,
            questions_per_doc=args.questions_per_doc,
            regenerate_gold=args.regenerate_gold,
            rejudge=args.rejudge,
            query_mode=args.query_mode,
        )
        logging.info("Completed QA evaluation: %s", summary)
        return

    experiment_ids = [
        exp_id
        for exp_id, exp_def in PIPELINE_EXPERIMENTS.items()
        if not getattr(exp_def, "legacy_alias", False)
    ]
    results = await evaluator.evaluate_many(
        experiment_ids,
        questions_per_doc=args.questions_per_doc,
        regenerate_gold=args.regenerate_gold,
        rejudge=args.rejudge,
        query_mode=args.query_mode,
    )
    logging.info("Completed QA evaluation for %d experiments", len(results))


if __name__ == "__main__":
    asyncio.run(main())
