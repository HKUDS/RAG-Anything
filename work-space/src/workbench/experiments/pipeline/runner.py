from __future__ import annotations

import csv
import json
import logging
import shutil
import time
from pathlib import Path

from raganything import RAGAnything, RAGAnythingConfig
from raganything.parser import DoclingParser, MineruParser
from raganything.mineru_cloud import MineruCloudParser
from raganything.prompt import PROMPTS as RAG_PROMPTS
from lightrag.prompt import PROMPTS as LIGHTRAG_PROMPTS

from src.config import ENV
from src.extraction import compute_extract_metrics, get_source_page_count
from src.workbench.metrics import extract_storage_stats
from src.workbench.experiments.base import PipelineExperimentDefinition
from src.workbench.observability import CSVReportWriter, ProcessedFileManifest
from src.workbench.runtime import (
    ITERADEConfig,
    ITERADEExtractionPatch,
    RadGraphXLConfig,
    RadGraphXLExtractionPatch,
    get_model_funcs,
)

logger = logging.getLogger("PipelineRunner")


class PipelineBenchmarkRunner:
    header = [
        "Timestamp",
        "Experiment_ID",
        "Experiment_Profile",
        "Provider",
        "Experiment_Parser",
        "File_Name",
        "Source_Pages",
        "Parse_Time(s)",
        "Graph_Time(s)",
        "Total_Time(s)",
        "End_to_End_Sec_Per_Page",
        "Output_Tokens",
        "Output_Tokens_Per_Page",
        "API_Calls",
        "Graph_Expansion_Profile",
        "Multimodal_Retention_Profile",
        "Nodes_Delta",
        "Edges_Delta",
        "Chunks_Delta",
        "Entities_Delta",
        "Relations_Delta",
        "Status",
        "Error",
    ]

    def __init__(self, report_file: Path | None = None):
        self.report_file = Path(report_file or ENV.report_file)
        self.report_writer = CSVReportWriter(self.report_file, self.header)
        self.orig_rag_prompts = RAG_PROMPTS.copy()
        self.orig_lightrag_prompts = LIGHTRAG_PROMPTS.copy()

    def _apply_custom_prompts(self, custom_prompts: dict):
        if not custom_prompts:
            return
        logger.info("Applying custom prompts...")
        for key, value in custom_prompts.items():
            if key == "lightrag_entity_extract":
                LIGHTRAG_PROMPTS["entity_extraction"] = value
            else:
                RAG_PROMPTS[key] = value

    def _restore_prompts(self):
        RAG_PROMPTS.clear()
        RAG_PROMPTS.update(self.orig_rag_prompts)
        LIGHTRAG_PROMPTS.clear()
        LIGHTRAG_PROMPTS.update(self.orig_lightrag_prompts)

    @staticmethod
    def _clear_dir(path: Path):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            logger.info("Cleared: %s", path)

    def clear_report_rows(self, experiment_id: str) -> int:
        removed = self.report_writer.remove_where(Experiment_ID=experiment_id)
        if removed:
            logger.info("Removed %d existing report rows for %s", removed, experiment_id)
        return removed

    @staticmethod
    async def _finalize_rag(rag: RAGAnything | None):
        if rag is None:
            return
        try:
            await rag.finalize_storages()
        except Exception as exc:
            logger.warning("Failed to finalize RAGAnything storages cleanly: %s", exc)
        try:
            from lightrag.kg.shared_storage import finalize_share_data

            finalize_share_data()
        except Exception as exc:
            logger.debug("Failed to finalize LightRAG shared data: %s", exc)

    @staticmethod
    def _filter_files_for_parser(files, parser_name: str):
        parser_name = (parser_name or "mineru").lower()
        if parser_name == "mineru":
            supported = set([".pdf"]) | MineruParser.IMAGE_FORMATS | MineruParser.OFFICE_FORMATS | MineruParser.TEXT_FORMATS
        elif parser_name == "mineru_cloud":
            supported = {".pdf"} | MineruCloudParser.IMAGE_FORMATS | MineruCloudParser.OFFICE_FORMATS | MineruCloudParser.HTML_FORMATS
        elif parser_name == "docling":
            supported = set([".pdf"]) | DoclingParser.OFFICE_FORMATS | DoclingParser.HTML_FORMATS
        elif parser_name in {"kreuzberg", "marker"}:
            supported = set([".pdf"]) | MineruParser.IMAGE_FORMATS
        else:
            return files
        return [f for f in files if f.suffix.lower() in supported]

    async def run(self, exp_def: PipelineExperimentDefinition, fresh_run: bool = False):
        parser_name = exp_def.parser or ENV.parser
        parse_method = exp_def.parse_method or ENV.parse_method
        parser_kwargs = exp_def.parser_kwargs or {}

        logger.info(
            "STARTING %s | profile=%s | provider=%s | parser=%s | method=%s | extraction_backend=%s",
            exp_def.id,
            exp_def.profile_name,
            exp_def.provider,
            parser_name,
            parse_method,
            exp_def.entity_relation_backend,
        )
        logger.info("[%s] Effective parser kwargs: %s", exp_def.id, parser_kwargs)

        self._apply_custom_prompts(exp_def.custom_prompts)
        llm_f, vision_f, embed_f = get_model_funcs(exp_def.provider, exp_def.use_gliner, exp_def.gliner_labels)

        exp_dir = Path(ENV.output_base_dir) / exp_def.id
        rag_storage = exp_dir / "rag_storage"
        parser_output = exp_dir / "parser_output"
        manifest = ProcessedFileManifest(exp_dir / "processed_manifest.json")

        if fresh_run:
            self._clear_dir(rag_storage)
            self._clear_dir(parser_output)
            if manifest.path.exists():
                manifest.path.unlink()

        rag = RAGAnything(
            config=RAGAnythingConfig(
                working_dir=str(rag_storage),
                parser_output_dir=str(parser_output),
                parser=parser_name,
                parse_method=parse_method,
                parser_kwargs=parser_kwargs,
                max_concurrent_files=ENV.max_workers,
                **exp_def.raganything_kwargs,
            ),
            llm_model_func=llm_f,
            vision_model_func=vision_f,
            embedding_func=embed_f,
            lightrag_kwargs=exp_def.lightrag_kwargs,
        )

        extraction_patch = None
        if exp_def.entity_relation_backend == "radgraph_xl":
            extraction_patch = RadGraphXLExtractionPatch(
                RadGraphXLConfig(
                    model_type=exp_def.entity_relation_kwargs.get(
                        "model_type", ENV.radgraph_model_type
                    ),
                    batch_size=int(
                        exp_def.entity_relation_kwargs.get(
                            "batch_size", ENV.radgraph_batch_size
                        )
                    ),
                    cuda_device=int(
                        exp_def.entity_relation_kwargs.get(
                            "cuda_device", ENV.radgraph_cuda_device
                        )
                    ),
                    split_chunks=bool(
                        exp_def.entity_relation_kwargs.get(
                            "split_chunks", ENV.radgraph_split_chunks
                        )
                    ),
                    max_segment_chars=int(
                        exp_def.entity_relation_kwargs.get(
                            "max_segment_chars", ENV.radgraph_max_segment_chars
                        )
                    ),
                    sentence_overlap=int(
                        exp_def.entity_relation_kwargs.get(
                            "sentence_overlap", ENV.radgraph_sentence_overlap
                        )
                    ),
                    empty_cache_each_batch=bool(
                        exp_def.entity_relation_kwargs.get(
                            "empty_cache_each_batch",
                            ENV.radgraph_empty_cache_each_batch,
                        )
                    ),
                )
            )
        elif exp_def.entity_relation_backend in {"iter_ade", "iter_scierc"}:
            extraction_patch = ITERADEExtractionPatch(
                ITERADEConfig(
                    model_name=exp_def.entity_relation_kwargs.get(
                        "model_name", ENV.iter_model_name
                    ),
                    device=exp_def.entity_relation_kwargs.get(
                        "device", ENV.iter_device
                    ),
                    split_chunks=bool(
                        exp_def.entity_relation_kwargs.get(
                            "split_chunks", ENV.iter_split_chunks
                        )
                    ),
                    max_length=int(
                        exp_def.entity_relation_kwargs.get(
                            "max_length", ENV.iter_max_length
                        )
                    ),
                    sentence_overlap=int(
                        exp_def.entity_relation_kwargs.get(
                            "sentence_overlap", ENV.iter_sentence_overlap
                        )
                    ),
                    empty_cache_each_batch=bool(
                        exp_def.entity_relation_kwargs.get(
                            "empty_cache_each_batch",
                            ENV.iter_empty_cache_each_batch,
                        )
                    ),
                    debug_output=bool(
                        exp_def.entity_relation_kwargs.get(
                            "debug_output", ENV.iter_debug_output
                        )
                    ),
                )
            )

        input_path = Path(exp_def.input_dir_override or ENV.input_dir)
        if not input_path.exists():
            logger.warning("Input directory does not exist: %s", input_path)
            await self._finalize_rag(rag)
            self._restore_prompts()
            return
        files = [f for f in input_path.glob("*.*") if f.is_file()]
        files = self._filter_files_for_parser(files, parser_name)
        if not files:
            logger.warning("No supported input files for parser '%s' in %s", parser_name, input_path)
            await self._finalize_rag(rag)
            self._restore_prompts()
            return

        manifest_data = manifest.load()
        runnable_files = []
        for file_path in files:
            action, fingerprint = manifest.classify(file_path)
            if action == "skip_unchanged":
                logger.info("Skip unchanged: %s", file_path.name)
                continue
            if action == "skip_changed":
                logger.warning("Skip changed file to avoid mixed graph state: %s", file_path.name)
                continue
            runnable_files.append((file_path, fingerprint))

        if not runnable_files:
            logger.info("Nothing new to process for %s", exp_def.id)
            await self._finalize_rag(rag)
            self._restore_prompts()
            return

        if extraction_patch is not None:
            extraction_patch.validate()
            logger.info(
                "[%s] Using %s extraction backend with config=%s",
                exp_def.id,
                exp_def.entity_relation_backend,
                exp_def.entity_relation_kwargs,
            )

        for file_path, fingerprint in runnable_files:
            t0 = time.time()
            t_parsed = 0
            t_end = 0
            status = "Success"
            doc_id = None
            error_msg = ""
            source_pages = get_source_page_count(file_path)
            output_tokens_delta = 0
            api_calls_delta = 0
            nodes_delta = 0
            edges_delta = 0
            chunks_delta = 0
            entities_delta = 0
            relations_delta = 0
            graph_expansion_profile = "entities/chunk=0.00 | relations/entity=0.00"
            multimodal_retention_profile = "img=0.0/100p | table=0.0/100p | eq=0.0/100p"
            try:
                stats_before = extract_storage_stats(str(rag_storage))
                content_list, doc_id = await rag.parse_document(str(file_path), output_dir=str(parser_output), display_stats=False)
                t_parsed = time.time()
                content_metrics = compute_extract_metrics(content_list, source_pages_override=source_pages)
                multimodal_retention_profile = (
                    f"img={content_metrics['figures_per_100_pages']:.1f}/100p | "
                    f"table={content_metrics['tables_per_100_pages']:.1f}/100p | "
                    f"eq={content_metrics['equations_per_100_pages']:.1f}/100p"
                )
                if extraction_patch is not None:
                    extraction_patch.install()
                try:
                    await rag.insert_content_list(
                        content_list,
                        str(file_path),
                        doc_id=doc_id,
                        display_stats=False,
                    )
                finally:
                    if extraction_patch is not None:
                        extraction_patch.restore()
                t_end = time.time()
                if rag.lightrag:
                    await rag.lightrag.llm_response_cache.index_done_callback()
                    await rag.lightrag.full_entities.index_done_callback()
                    await rag.lightrag.full_relations.index_done_callback()
                    await rag.lightrag.doc_status.index_done_callback()
                    doc_status = await rag.lightrag.doc_status.get_by_id(doc_id)
                    if doc_status and str(doc_status.get("status", "")).lower() == "failed":
                        raise RuntimeError(
                            doc_status.get("error_msg")
                            or f"Document {doc_id} ended in failed doc_status"
                        )
                stats_after = extract_storage_stats(str(rag_storage))
                output_tokens_delta = max(stats_after["output_tokens"] - stats_before["output_tokens"], 0)
                api_calls_delta = max(stats_after["api_calls"] - stats_before["api_calls"], 0)
                nodes_delta = max(stats_after["nodes"] - stats_before["nodes"], 0)
                edges_delta = max(stats_after["edges"] - stats_before["edges"], 0)
                chunks_delta = max(stats_after["chunks"] - stats_before["chunks"], 0)
                entities_delta = max(stats_after["entities"] - stats_before["entities"], 0)
                relations_delta = max(stats_after["relations"] - stats_before["relations"], 0)
                entities_per_chunk = (entities_delta / chunks_delta) if chunks_delta > 0 else 0.0
                relations_per_entity = (relations_delta / entities_delta) if entities_delta > 0 else 0.0
                graph_expansion_profile = (
                    f"entities/chunk={entities_per_chunk:.2f} | "
                    f"relations/entity={relations_per_entity:.2f}"
                )
                if (
                    exp_def.entity_relation_backend != "llm"
                    and stats_after["chunks"] > 0
                    and stats_after["entities"] == 0
                ):
                    raise RuntimeError(
                        "NER extraction produced zero entities after insertion; "
                        "treating this as a failed/no-op graph build instead of Success. "
                        "Use --fresh-run for this experiment and run NER experiments in separate processes."
                    )
            except Exception as exc:
                logger.error("Pipeline experiment failed for %s: %s", file_path.name, exc)
                status = "Failed"
                error_msg = str(exc)
                t_end = time.time()
                if t_parsed == 0:
                    t_parsed = t_end

            end_to_end_sec_per_page = ((t_end - t0) / source_pages) if source_pages > 0 else 0.0
            output_tokens_per_page = (output_tokens_delta / source_pages) if source_pages > 0 else 0.0
            row = {
                "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Experiment_ID": exp_def.id,
                "Experiment_Profile": exp_def.profile_name,
                "Provider": exp_def.provider,
                "Experiment_Parser": parser_name,
                "File_Name": file_path.name,
                "Source_Pages": source_pages,
                "Parse_Time(s)": f"{t_parsed - t0:.2f}",
                "Graph_Time(s)": f"{(t_end - t_parsed) if status == 'Success' else 0:.2f}",
                "Total_Time(s)": f"{t_end - t0:.2f}",
                "End_to_End_Sec_Per_Page": f"{end_to_end_sec_per_page:.2f}",
                "Output_Tokens": output_tokens_delta,
                "Output_Tokens_Per_Page": f"{output_tokens_per_page:.2f}",
                "API_Calls": api_calls_delta,
                "Graph_Expansion_Profile": graph_expansion_profile,
                "Multimodal_Retention_Profile": multimodal_retention_profile,
                "Nodes_Delta": nodes_delta,
                "Edges_Delta": edges_delta,
                "Chunks_Delta": chunks_delta,
                "Entities_Delta": entities_delta,
                "Relations_Delta": relations_delta,
                "Status": status,
                "Error": error_msg,
            }
            self.report_writer.append(row)

            manifest_data.setdefault("files", {})[file_path.name] = {
                "source_path": str(file_path.resolve()),
                "content_md5": fingerprint["content_md5"],
                "size": fingerprint["size"],
                "mtime": fingerprint["mtime"],
                "status": status,
                "doc_id": doc_id,
                "last_run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "experiment_id": exp_def.id,
            }
            manifest.save(manifest_data)

        await self._finalize_rag(rag)
        self._restore_prompts()
