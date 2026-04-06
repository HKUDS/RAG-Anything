from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List

from raganything import RAGAnything, RAGAnythingConfig
from raganything.parser import DoclingParser, MineruParser
from raganything.mineru_cloud import MineruCloudParser

from src.config import ENV
from src.extraction import (
    compute_extract_metrics,
    get_source_page_count,
    normalize_content_list_for_pipeline,
    summarize_extract_metrics,
)
from src.workbench.experiments.base import ParserBenchmarkExperimentDefinition
from src.workbench.observability import CSVReportWriter
from src.workbench.runtime import MinerUCloudConfig, MinerUPrecisionCloudClient

logger = logging.getLogger("ParserRunner")


class ParserBenchmarkRunner:
    detail_header = [
        "Timestamp",
        "Experiment_ID",
        "Parser",
        "Parse_Method",
        "File_Name",
        "Source_Pages",
        "Parse_Time(s)",
        "Sec_Per_Page",
        "Noise_Ratio",
        "Tokens_Per_Page",
        "Modality_Coverage_Profile",
        "Text_Blocks",
        "Image_Blocks",
        "Table_Blocks",
        "Equation_Blocks",
        "Status",
        "Text_MD5",
        "Doc_ID",
        "Error",
    ]
    summary_header = [
        "Timestamp",
        "Experiment_ID",
        "Parser",
        "Parse_Method",
        "Files_Total",
        "Files_Succeeded",
        "Parse_Success_Rate",
        "Median_Sec_Per_Page",
        "Median_Noise_Ratio",
        "Median_Tokens_Per_Page",
        "Modality_Coverage_Profile",
        "Mean_Text_Blocks_Per_Page",
        "Mean_Tables_Per_100_Pages",
        "Mean_Figures_Per_100_Pages",
        "Mean_Equations_Per_100_Pages",
        "Parser_Kwargs",
        "Notes",
    ]

    def __init__(self, detail_report_file: Path, summary_report_file: Path):
        self.detail_writer = CSVReportWriter(Path(detail_report_file), self.detail_header)
        self.summary_writer = CSVReportWriter(Path(summary_report_file), self.summary_header)

    @staticmethod
    def _clear_dir(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            logger.info("Cleared: %s", path)

    @staticmethod
    def _clear_known_parser_cache(parser_name: str) -> None:
        parser_name = (parser_name or "").lower()
        if parser_name != "kreuzberg":
            return
        for cache_dir in [Path.cwd() / ".kreuzberg", Path.home() / ".kreuzberg"]:
            if cache_dir.exists():
                ParserBenchmarkRunner._clear_dir(cache_dir)

    @staticmethod
    def _filter_files_for_parser(files: List[Path], parser: str) -> List[Path]:
        if parser == "mineru":
            supported = set([".pdf"]) | MineruParser.IMAGE_FORMATS | MineruParser.OFFICE_FORMATS | MineruParser.TEXT_FORMATS
        elif parser == "mineru_cloud":
            supported = {".pdf"} | MineruCloudParser.IMAGE_FORMATS | MineruCloudParser.OFFICE_FORMATS | MineruCloudParser.HTML_FORMATS
        elif parser == "docling":
            supported = set([".pdf"]) | DoclingParser.OFFICE_FORMATS | DoclingParser.HTML_FORMATS
        elif parser == "kreuzberg":
            supported = set([".pdf"]) | MineruParser.IMAGE_FORMATS
        else:
            return files
        return [f for f in files if f.suffix.lower() in supported]

    async def run(
        self,
        exp_def: ParserBenchmarkExperimentDefinition,
        input_dir: Path,
        fresh_run: bool = False,
        fresh_parser_cache: bool = False,
    ) -> None:
        exp_dir = Path(ENV.output_base_dir) / "extract_benchmark" / exp_def.id
        if fresh_run:
            self._clear_dir(exp_dir)
        if fresh_parser_cache:
            self._clear_known_parser_cache(exp_def.parser)

        parser_output = exp_dir / "parser_output"
        content_output = exp_dir / "content_list"
        content_output.mkdir(parents=True, exist_ok=True)

        rag = None
        effective_parser_kwargs = dict(exp_def.parser_kwargs or {})
        if fresh_parser_cache and exp_def.parser == "kreuzberg":
            effective_parser_kwargs["use_cache"] = False
        logger.info("[%s] Effective parser kwargs: %s", exp_def.id, effective_parser_kwargs)

        if exp_def.parser != "mineru_cloud":
            rag = RAGAnything(
                config=RAGAnythingConfig(
                    working_dir=str(exp_dir / "rag_storage"),
                    parser_output_dir=str(parser_output),
                    parser=exp_def.parser,
                    parse_method=exp_def.parse_method,
                )
            )
            rag.config.parser_kwargs = effective_parser_kwargs

        files = [p for p in Path(input_dir).glob("*.*") if p.is_file()]
        files = self._filter_files_for_parser(files, exp_def.parser)
        if not files:
            logger.warning("No supported files found for parser %s under %s", exp_def.parser, input_dir)
            return

        experiment_rows: List[Dict[str, object]] = []
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        for file_path in files:
            t0 = time.time()
            status = "Success"
            error_msg = ""
            content_list = []
            doc_id = ""
            try:
                if exp_def.parser == "mineru_cloud":
                    if not ENV.mineru_api_key:
                        raise RuntimeError(
                            "MINERU_API_KEY is missing. Set it in work-space/.env before running ext4_mineru_cloud_vlm."
                        )
                    cloud_client = MinerUPrecisionCloudClient(
                        MinerUCloudConfig(
                            api_key=ENV.mineru_api_key,
                            base_url=str(effective_parser_kwargs.get("api_base_url", ENV.mineru_api_base_url)),
                            model_version=str(effective_parser_kwargs.get("model_version", ENV.mineru_cloud_model_version)),
                            language=str(effective_parser_kwargs.get("language", ENV.mineru_cloud_language)),
                            enable_formula=bool(effective_parser_kwargs.get("enable_formula", True)),
                            enable_table=bool(effective_parser_kwargs.get("enable_table", True)),
                            poll_interval_sec=int(effective_parser_kwargs.get("poll_interval_sec", ENV.mineru_cloud_poll_interval_sec)),
                            timeout_sec=int(effective_parser_kwargs.get("timeout_sec", ENV.mineru_cloud_timeout_sec)),
                        )
                    )
                    content_list, doc_id = await asyncio.to_thread(
                        cloud_client.parse_file,
                        file_path=file_path,
                        parser_output_dir=parser_output,
                    )
                else:
                    assert rag is not None
                    content_list, doc_id = await rag.parse_document(
                        str(file_path),
                        output_dir=str(parser_output),
                        display_stats=False,
                    )
                content_list, normalize_report = normalize_content_list_for_pipeline(content_list)
                logger.info(
                    "[%s] Normalized content_list: %s -> %s blocks",
                    file_path.name,
                    normalize_report["input_blocks"],
                    normalize_report["output_blocks"],
                )
            except Exception as exc:
                status = "Failed"
                error_msg = str(exc)

            parse_time = time.time() - t0
            out_json = content_output / f"{file_path.stem}_content_list.json"
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(content_list, f, ensure_ascii=False, indent=2)

            actual_source_pages = get_source_page_count(file_path)
            metrics = compute_extract_metrics(
                content_list,
                source_pages_override=actual_source_pages if actual_source_pages > 0 else None,
            )
            source_pages = int(metrics["source_pages"] or 0)
            seconds_per_page = (parse_time / source_pages) if source_pages > 0 else 0.0
            row = {
                "timestamp": timestamp,
                "experiment_id": exp_def.id,
                "parser": exp_def.parser,
                "parse_method": exp_def.parse_method,
                "file_name": file_path.name,
                "source_pages": source_pages,
                "parse_time_seconds": parse_time,
                "seconds_per_page": seconds_per_page,
                "noise_ratio": float(metrics["noise_ratio"]),
                "tokens_per_page": float(metrics["tokens_per_page"]),
                "modality_coverage_profile": metrics["modality_coverage_profile"],
                "text_blocks": int(metrics["text_blocks"]),
                "image_blocks": int(metrics["image_blocks"]),
                "table_blocks": int(metrics["table_blocks"]),
                "equation_blocks": int(metrics["equation_blocks"]),
                "status": status,
                "text_md5": metrics["text_md5"],
                "doc_id": doc_id,
                "error": error_msg,
                "text_blocks_per_page": float(metrics["text_blocks_per_page"]),
                "tables_per_100_pages": float(metrics["tables_per_100_pages"]),
                "figures_per_100_pages": float(metrics["figures_per_100_pages"]),
                "equations_per_100_pages": float(metrics["equations_per_100_pages"]),
            }
            experiment_rows.append(row)
            self.detail_writer.append(
                {
                    "Timestamp": row["timestamp"],
                    "Experiment_ID": row["experiment_id"],
                    "Parser": row["parser"],
                    "Parse_Method": row["parse_method"],
                    "File_Name": row["file_name"],
                    "Source_Pages": row["source_pages"],
                    "Parse_Time(s)": f"{row['parse_time_seconds']:.2f}",
                    "Sec_Per_Page": f"{row['seconds_per_page']:.2f}",
                    "Noise_Ratio": f"{row['noise_ratio']:.4f}",
                    "Tokens_Per_Page": f"{row['tokens_per_page']:.2f}",
                    "Modality_Coverage_Profile": row["modality_coverage_profile"],
                    "Text_Blocks": row["text_blocks"],
                    "Image_Blocks": row["image_blocks"],
                    "Table_Blocks": row["table_blocks"],
                    "Equation_Blocks": row["equation_blocks"],
                    "Status": row["status"],
                    "Text_MD5": row["text_md5"],
                    "Doc_ID": row["doc_id"],
                    "Error": row["error"],
                }
            )

        summary = summarize_extract_metrics(experiment_rows)
        self.summary_writer.append(
            {
                "Timestamp": timestamp,
                "Experiment_ID": exp_def.id,
                "Parser": exp_def.parser,
                "Parse_Method": exp_def.parse_method,
                "Files_Total": summary["files_total"],
                "Files_Succeeded": summary["files_succeeded"],
                "Parse_Success_Rate": f"{summary['parse_success_rate']:.4f}",
                "Median_Sec_Per_Page": f"{summary['median_seconds_per_page']:.2f}",
                "Median_Noise_Ratio": f"{summary['median_noise_ratio']:.4f}",
                "Median_Tokens_Per_Page": f"{summary['median_tokens_per_page']:.2f}",
                "Modality_Coverage_Profile": summary["modality_coverage_profile"],
                "Mean_Text_Blocks_Per_Page": f"{summary['mean_text_blocks_per_page']:.2f}",
                "Mean_Tables_Per_100_Pages": f"{summary['mean_tables_per_100_pages']:.2f}",
                "Mean_Figures_Per_100_Pages": f"{summary['mean_figures_per_100_pages']:.2f}",
                "Mean_Equations_Per_100_Pages": f"{summary['mean_equations_per_100_pages']:.2f}",
                "Parser_Kwargs": json.dumps(effective_parser_kwargs, ensure_ascii=False),
                "Notes": exp_def.notes,
            }
        )
