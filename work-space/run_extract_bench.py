import argparse
import asyncio
import csv
import json
import logging
import shutil
import time
from pathlib import Path
from typing import List

from raganything import RAGAnything, RAGAnythingConfig
from raganything.parser import MineruParser, DoclingParser
from src.config import ENV
from src.extract_definitions import EXTRACT_EXPERIMENTS, ExtractExperimentDef
from src.extract_metrics import compute_extract_metrics
from src.extract_normalizer import normalize_content_list_for_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ExtractBench")


def _get_files(input_dir: Path) -> List[Path]:
    return [p for p in input_dir.glob("*.*") if p.is_file()]


def _filter_files_for_parser(files: List[Path], parser: str) -> List[Path]:
    if parser == "mineru":
        supported = set([".pdf"]) | MineruParser.IMAGE_FORMATS | MineruParser.OFFICE_FORMATS | MineruParser.TEXT_FORMATS
    elif parser == "docling":
        supported = set([".pdf"]) | DoclingParser.OFFICE_FORMATS | DoclingParser.HTML_FORMATS
    elif parser in ["kreuzberg", "marker"]:
        supported = set([".pdf"]) | MineruParser.IMAGE_FORMATS
    else:
        return files
    return [f for f in files if f.suffix.lower() in supported]


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        logger.info(f"🧹 Cleared: {path}")


def _clear_known_parser_cache(parser_name: str) -> None:
    parser_name = (parser_name or "").lower()
    if parser_name != "kreuzberg":
        return
    candidates = [
        Path(__file__).resolve().parent / ".kreuzberg",
        Path.home() / ".kreuzberg",
    ]
    for cache_dir in candidates:
        if cache_dir.exists():
            _clear_dir(cache_dir)


def _append_csv_row(path: Path, row: dict, header: List[str]) -> None:
    _ensure_parent_dir(path)
    file_exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


async def run_experiment(
    exp_def: ExtractExperimentDef,
    input_dir: Path,
    report_path: Path,
    fresh_run: bool = False,
    fresh_parser_cache: bool = False,
):
    logger.info(f"\n🚀 EXTRACT START: {exp_def.id} | {exp_def.description}")

    exp_dir = Path(ENV.output_base_dir) / "extract_benchmark" / exp_def.id
    if fresh_run:
        _clear_dir(exp_dir)
    if fresh_parser_cache:
        _clear_known_parser_cache(exp_def.parser)

    parser_output = exp_dir / "parser_output"
    content_output = exp_dir / "content_list"
    content_output.mkdir(parents=True, exist_ok=True)

    rag = RAGAnything(
        config=RAGAnythingConfig(
            working_dir=str(exp_dir / "rag_storage"),
            parser_output_dir=str(parser_output),
            parser=exp_def.parser,
            parse_method=exp_def.parse_method,
        )
    )
    # Inject parser kwargs from experiment definition
    effective_parser_kwargs = dict(exp_def.parser_kwargs or {})
    if fresh_parser_cache and exp_def.parser == "kreuzberg":
        # Enforce no-cache mode for fair timing when parser cache is reset.
        effective_parser_kwargs["use_cache"] = False
    rag.config.parser_kwargs = effective_parser_kwargs

    files = _get_files(input_dir)
    files = _filter_files_for_parser(files, exp_def.parser)
    if not files:
        logger.warning("No supported files found for this parser.")
        return

    for file_path in files:
        t0 = time.time()
        status = "Success"
        error_msg = ""
        content_list = []
        doc_id = ""

        try:
            content_list, doc_id = await rag.parse_document(
                str(file_path), output_dir=str(parser_output), display_stats=False
            )
            content_list, normalize_report = normalize_content_list_for_pipeline(content_list)
            logger.info(
                "Normalized content_list for pipeline compatibility: "
                f"{normalize_report['input_blocks']} -> {normalize_report['output_blocks']} blocks, "
                f"dropped={normalize_report['dropped_blocks']}, "
                f"types={normalize_report['normalized_type_counts']}"
            )
        except Exception as e:
            status = "Failed"
            error_msg = str(e)

        t1 = time.time()
        parse_time = t1 - t0

        # Save content_list for downstream compatibility (even if empty)
        out_json = content_output / f"{file_path.stem}_content_list.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(content_list, f, ensure_ascii=False)

        metrics = compute_extract_metrics(content_list)

        row = {
            "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Experiment_ID": exp_def.id,
            "Parser": exp_def.parser,
            "Parse_Method": exp_def.parse_method,
            "Parser_Kwargs": json.dumps(effective_parser_kwargs, ensure_ascii=False),
            "File_Name": file_path.name,
            "Parse_Time(s)": f"{parse_time:.2f}",
            "Total_Blocks": metrics["total_blocks"],
            "Text_Blocks": metrics["text_blocks"],
            "Empty_Text_Blocks": metrics["empty_text_blocks"],
            "Text_Chars": metrics["text_chars"],
            "Text_Tokens": metrics["text_tokens"],
            "Avg_Text_Block_Len": f"{metrics['avg_text_block_len']:.2f}",
            "Image_Blocks": metrics["image_blocks"],
            "Image_Files_Exist": metrics["image_files_exist"],
            "Image_Files_Missing": metrics["image_files_missing"],
            "Table_Blocks": metrics["table_blocks"],
            "Table_Rows": metrics["table_rows"],
            "Table_Cells": metrics["table_cells"],
            "Equation_Blocks": metrics["equation_blocks"],
            "Text_MD5": metrics["text_md5"],
            "Doc_ID": doc_id,
            "Status": status,
            "Error": error_msg,
        }

        header = list(row.keys())
        _append_csv_row(report_path, row, header)

        logger.info(
            f"✅ {file_path.name} | {exp_def.parser}/{exp_def.parse_method} | "
            f"{metrics['total_blocks']} blocks | {parse_time:.2f}s | {status}"
        )


async def main():
    parser = argparse.ArgumentParser(description="Extract-only benchmark for RAGAnything")
    parser.add_argument("--exp", type=str, help="Experiment ID to run. If empty, run all.")
    parser.add_argument(
        "--fresh-run",
        action="store_true",
        help="Clear benchmark_outputs/extract_benchmark/<exp_id> before each run.",
    )
    parser.add_argument(
        "--fresh-parser-cache",
        action="store_true",
        help="Clear known parser caches (currently Kreuzberg cache dirs) before run.",
    )
    parser.add_argument(
        "--input", type=str, default=ENV.input_dir, help="Input directory containing documents"
    )
    parser.add_argument(
        "--report", type=str, default=str(Path(ENV.output_base_dir) / "extract_benchmark.csv")
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    report_path = Path(args.report)

    if args.exp:
        if args.exp in EXTRACT_EXPERIMENTS:
            await run_experiment(
                EXTRACT_EXPERIMENTS[args.exp],
                input_dir,
                report_path,
                fresh_run=args.fresh_run,
                fresh_parser_cache=args.fresh_parser_cache,
            )
        else:
            print(f"❌ Experiment '{args.exp}' not found. Available: {list(EXTRACT_EXPERIMENTS.keys())}")
    else:
        print("🚀 Running ALL extract experiments...")
        for exp_id, exp_def in EXTRACT_EXPERIMENTS.items():
            await run_experiment(
                exp_def,
                input_dir,
                report_path,
                fresh_run=args.fresh_run,
                fresh_parser_cache=args.fresh_parser_cache,
            )


if __name__ == "__main__":
    asyncio.run(main())
