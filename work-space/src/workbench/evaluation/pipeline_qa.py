from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.config import ENV
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.judging.openai_eval import build_openai_judge_client
from src.workbench.observability import CSVReportWriter, JSONLReportWriter
from src.workbench.query import RAGQueryEngine

logger = logging.getLogger("PipelineQAEval")


def _file_md5(path: Path) -> str:
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _linearize_content_list(content_list: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in content_list:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "text")
        if item_type == "text":
            text = str(item.get("text", "") or "").strip()
            if text:
                parts.append(f"[TEXT]\n{text}")
        elif item_type == "table":
            caption = str(item.get("table_caption", "") or "").strip()
            body = str(item.get("table_body", "") or "").strip()
            if caption or body:
                parts.append(f"[TABLE]\nCaption: {caption}\nBody: {body}")
        elif item_type == "image":
            captions = item.get("image_caption") or item.get("img_caption") or []
            footnotes = item.get("image_footnote") or item.get("img_footnote") or []
            caption_text = ", ".join(map(str, captions)) if isinstance(captions, list) else str(captions)
            footnote_text = ", ".join(map(str, footnotes)) if isinstance(footnotes, list) else str(footnotes)
            if caption_text or footnote_text:
                parts.append(f"[FIGURE]\nCaptions: {caption_text}\nFootnotes: {footnote_text}")
        elif item_type == "equation":
            eq_text = str(item.get("text", "") or item.get("equation_text", "") or "").strip()
            if eq_text:
                parts.append(f"[EQUATION]\n{eq_text}")
    merged = "\n\n".join(parts).strip()
    if len(merged) > 30000:
        merged = merged[:30000].rstrip()
    return merged


def _extract_text_fallback(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            with open(path, "rb") as f:
                reader = PdfReader(f)
                text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
            return text[:30000]
        except Exception:
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:30000]
    except Exception:
        return ""


def _resolve_reference_content(doc_path: Path) -> tuple[str, str]:
    search_order = [
        Path(ENV.output_base_dir) / "extract_benchmark" / "ext4_mineru_cloud_vlm" / "content_list",
        Path(ENV.output_base_dir) / "extract_benchmark" / "ext1_mineru_default_multimodal" / "content_list",
        Path(ENV.output_base_dir) / "extract_benchmark" / "ext2_docling_default" / "content_list",
        Path(ENV.output_base_dir) / "extract_benchmark" / "ext3_kreuzberg_paddleocr" / "content_list",
    ]
    stem = doc_path.stem
    for directory in search_order:
        for suffix in ["_content_list.json", "_content_list_v2.json"]:
            candidate = directory / f"{stem}{suffix}"
            if candidate.exists():
                try:
                    content_list = _load_json(candidate)
                    if isinstance(content_list, list) and content_list:
                        return _linearize_content_list(content_list), str(candidate)
                except Exception:
                    continue
    return _extract_text_fallback(doc_path), str(doc_path)


def _resolve_successful_docs_for_experiment(exp_def) -> List[Path]:
    input_dir = Path(exp_def.input_dir_override or ENV.input_dir)
    manifest_path = Path(ENV.output_base_dir) / exp_def.id / "processed_manifest.json"
    if manifest_path.exists():
        try:
            data = _load_json(manifest_path)
            files = data.get("files", {}) if isinstance(data, dict) else {}
            resolved: List[Path] = []
            for _, meta in files.items():
                if str(meta.get("status", "")).lower() != "success":
                    continue
                source_path = meta.get("source_path")
                if not source_path:
                    continue
                candidate = Path(source_path)
                if candidate.exists():
                    resolved.append(candidate)
            if resolved:
                return resolved
        except Exception:
            logger.warning("Failed to read processed manifest for %s", exp_def.id)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    docs = [p for p in input_dir.glob("*.*") if p.is_file()]
    if not docs:
        raise RuntimeError(f"No documents found in {input_dir}")
    return docs


class PipelineQAEvaluator:
    summary_header = [
        "Timestamp",
        "Experiment_ID",
        "Experiment_Profile",
        "Provider",
        "Experiment_Parser",
        "Query_Mode",
        "Documents_Evaluated",
        "Questions_Total",
        "Evidence_Recall_at_10",
        "Correctness",
        "Groundedness",
        "Completeness",
        "Unsupported_Claim_Rate",
        "Final_QA_Score",
        "Status",
    ]

    def __init__(
        self,
        *,
        summary_report_file: Path | None = None,
        detail_report_file: Path | None = None,
        gold_dir: Path | None = None,
        judge_cache_dir: Path | None = None,
    ):
        reports_dir = Path(ENV.output_base_dir) / "reports"
        self.summary_writer = CSVReportWriter(
            Path(summary_report_file or reports_dir / "pipeline_qa_summary.csv"),
            self.summary_header,
        )
        self.detail_writer = JSONLReportWriter(
            Path(detail_report_file or reports_dir / "pipeline_qa_details.jsonl")
        )
        self.gold_dir = Path(gold_dir or Path("datasets/pipeline_qa/gold_qa"))
        self.judge_cache_dir = Path(judge_cache_dir or Path(ENV.output_base_dir) / "pipeline_qa_cache")
        self.judge = build_openai_judge_client()

    def _gold_file(self, doc_path: Path) -> Path:
        return self.gold_dir / f"{doc_path.stem}.json"

    def _remove_existing_records(self, experiment_id: str, query_mode: str) -> None:
        summary_path = self.summary_writer.path
        if summary_path.exists():
            with open(summary_path, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            filtered = [
                row
                for row in rows
                if not (
                    row.get("Experiment_ID") == experiment_id
                    and row.get("Query_Mode", "mix") == query_mode
                )
            ]
            with open(summary_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.summary_header)
                writer.writeheader()
                writer.writerows(filtered)

        detail_path = self.detail_writer.path
        if detail_path.exists():
            kept_lines: list[str] = []
            with open(detail_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        record.get("experiment_id") == experiment_id
                        and record.get("query_mode", "mix") == query_mode
                    ):
                        continue
                    kept_lines.append(json.dumps(record, ensure_ascii=False))
            with open(detail_path, "w", encoding="utf-8") as f:
                for line in kept_lines:
                    f.write(line + "\n")

    def _judge_cache_file(
        self,
        experiment_id: str,
        query_mode: str,
        doc_path: Path,
        question_id: str,
    ) -> Path:
        return (
            self.judge_cache_dir
            / experiment_id
            / query_mode
            / f"{doc_path.stem}__{question_id}.json"
        )

    @staticmethod
    def _judge_input_hash(
        *,
        query_mode: str,
        qa_item: Dict[str, Any],
        trace: Dict[str, Any],
        judge_model: str,
    ) -> str:
        payload = {
            "query_mode": query_mode,
            "question": qa_item.get("question", ""),
            "gold_answer": qa_item.get("gold_answer", ""),
            "evidence_snippets": qa_item.get("evidence_snippets", []),
            "evidence_keywords": qa_item.get("evidence_keywords", []),
            "retrieved_context": trace.get("retrieved_context", ""),
            "distilled_context": trace.get("distilled_context", ""),
            "answer": trace.get("answer", ""),
            "fallback_used": trace.get("fallback_used", False),
            "judge_model": judge_model,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def _load_or_generate_gold(
        self,
        doc_path: Path,
        *,
        questions_per_doc: int,
        regenerate_gold: bool,
    ) -> Dict[str, Any]:
        gold_file = self._gold_file(doc_path)
        source_md5 = _file_md5(doc_path)
        if gold_file.exists() and not regenerate_gold:
            data = _load_json(gold_file)
            if (
                isinstance(data, dict)
                and data.get("source_md5") == source_md5
                and int(data.get("questions_per_doc", 0) or 0) == questions_per_doc
            ):
                return data

        reference_text, reference_source = _resolve_reference_content(doc_path)
        if not reference_text.strip():
            raise RuntimeError(f"Could not build reference text for gold QA generation: {doc_path}")

        generated = await self.judge.generate_gold_questions(
            doc_name=doc_path.name,
            reference_text=reference_text,
            num_questions=questions_per_doc,
        )
        payload = {
            "document_name": doc_path.name,
            "source_path": str(doc_path.resolve()),
            "source_md5": source_md5,
            "reference_source": reference_source,
            "questions_per_doc": questions_per_doc,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "generator_model": self.judge.model,
            "questions": generated.get("questions", []),
        }
        _dump_json(gold_file, payload)
        return payload

    async def _load_or_judge(
        self,
        *,
        experiment_id: str,
        query_mode: str,
        doc_path: Path,
        qa_item: Dict[str, Any],
        trace: Dict[str, Any],
        rejudge: bool,
    ) -> tuple[Dict[str, Any], bool]:
        question_id = str(qa_item.get("question_id") or hashlib.md5(str(qa_item.get("question", "")).encode("utf-8")).hexdigest()[:12])
        cache_file = self._judge_cache_file(experiment_id, query_mode, doc_path, question_id)
        input_hash = self._judge_input_hash(
            query_mode=query_mode,
            qa_item=qa_item,
            trace=trace,
            judge_model=self.judge.model,
        )

        if cache_file.exists() and not rejudge:
            cached = _load_json(cache_file)
            if isinstance(cached, dict) and cached.get("input_hash") == input_hash:
                result = dict(cached.get("judged", {}))
                if result:
                    return result, True

        judged = await self.judge.judge_answer(
            question=qa_item["question"],
            gold_answer=qa_item["gold_answer"],
            evidence_snippets=list(qa_item.get("evidence_snippets", [])),
            evidence_keywords=list(qa_item.get("evidence_keywords", [])),
            retrieved_context=trace.get("retrieved_context", ""),
            model_answer=trace.get("answer", ""),
        )
        payload = {
            "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "experiment_id": experiment_id,
            "query_mode": query_mode,
            "document_name": doc_path.name,
            "question_id": question_id,
            "judge_model": self.judge.model,
            "input_hash": input_hash,
            "judged": judged,
        }
        _dump_json(cache_file, payload)
        return judged, False

    @staticmethod
    def _compute_summary(experiment_id: str, exp_def, query_mode: str, detail_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(detail_rows)
        if total == 0:
            return {
                "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Experiment_ID": experiment_id,
                "Experiment_Profile": exp_def.profile_name,
                "Provider": exp_def.provider,
                "Experiment_Parser": exp_def.parser,
                "Query_Mode": query_mode,
                "Documents_Evaluated": 0,
                "Questions_Total": 0,
                "Evidence_Recall_at_10": "0.0000",
                "Correctness": "0.0000",
                "Groundedness": "0.0000",
                "Completeness": "0.0000",
                "Unsupported_Claim_Rate": "0.0000",
                "Final_QA_Score": "0.0000",
                "Status": "NoData",
            }

        docs = len({row["document_name"] for row in detail_rows})
        evidence_recall = sum(float(row["evidence_recall_at_10"]) for row in detail_rows) / total
        correctness = sum(float(row["correctness"]) / 4.0 for row in detail_rows) / total
        groundedness = sum(float(row["groundedness"]) / 4.0 for row in detail_rows) / total
        completeness = sum(float(row["completeness"]) / 4.0 for row in detail_rows) / total
        unsupported = sum(float(row["unsupported_claim"]) for row in detail_rows) / total
        qa_score = (
            0.40 * correctness
            + 0.30 * groundedness
            + 0.20 * completeness
            + 0.10 * evidence_recall
        ) * (1.0 - unsupported)

        return {
            "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Experiment_ID": experiment_id,
            "Experiment_Profile": exp_def.profile_name,
            "Provider": exp_def.provider,
            "Experiment_Parser": exp_def.parser,
            "Query_Mode": query_mode,
            "Documents_Evaluated": docs,
            "Questions_Total": total,
            "Evidence_Recall_at_10": f"{evidence_recall:.4f}",
            "Correctness": f"{correctness:.4f}",
            "Groundedness": f"{groundedness:.4f}",
            "Completeness": f"{completeness:.4f}",
            "Unsupported_Claim_Rate": f"{unsupported:.4f}",
            "Final_QA_Score": f"{qa_score:.4f}",
            "Status": "Success",
        }

    async def evaluate_experiment(
        self,
        experiment_id: str,
        *,
        questions_per_doc: int = 10,
        regenerate_gold: bool = False,
        rejudge: bool = False,
        query_mode: str = "mix",
    ) -> Dict[str, Any]:
        if experiment_id not in PIPELINE_EXPERIMENTS:
            raise ValueError(f"Unknown pipeline experiment: {experiment_id}")

        exp_def = PIPELINE_EXPERIMENTS[experiment_id]
        docs = _resolve_successful_docs_for_experiment(exp_def)
        self._remove_existing_records(experiment_id, query_mode)

        query_engine = RAGQueryEngine(experiment_id)
        await query_engine.initialize()
        detail_rows: List[Dict[str, Any]] = []
        try:
            for doc_path in docs:
                gold = await self._load_or_generate_gold(
                    doc_path,
                    questions_per_doc=questions_per_doc,
                    regenerate_gold=regenerate_gold,
                )
                for qa_item in gold.get("questions", []):
                    trace = await query_engine.query_with_trace(
                        qa_item["question"],
                        mode=query_mode,
                    )
                    judged, judge_cache_hit = await self._load_or_judge(
                        experiment_id=experiment_id,
                        query_mode=query_mode,
                        doc_path=doc_path,
                        qa_item=qa_item,
                        trace=trace,
                        rejudge=rejudge,
                    )
                    row = {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "experiment_id": experiment_id,
                        "experiment_profile": exp_def.profile_name,
                        "provider": exp_def.provider,
                        "experiment_parser": exp_def.parser,
                        "document_name": doc_path.name,
                        "question_id": qa_item.get("question_id"),
                        "difficulty": qa_item.get("difficulty"),
                        "question_type": qa_item.get("question_type"),
                        "question": qa_item.get("question"),
                        "gold_answer": qa_item.get("gold_answer"),
                        "gold_evidence_snippets": qa_item.get("evidence_snippets", []),
                        "gold_evidence_keywords": qa_item.get("evidence_keywords", []),
                        "query_mode": query_mode,
                        "retrieved_context": trace.get("retrieved_context", ""),
                        "distilled_context": trace.get("distilled_context", ""),
                        "answer": trace.get("answer", ""),
                        "fallback_used": trace.get("fallback_used", False),
                        "judge_cache_hit": judge_cache_hit,
                        "correctness": int(judged["correctness"]),
                        "groundedness": int(judged["groundedness"]),
                        "completeness": int(judged["completeness"]),
                        "evidence_recall_at_10": int(judged["evidence_recall_at_10"]),
                        "unsupported_claim": int(judged["unsupported_claim"]),
                        "reasoning": judged.get("reasoning", ""),
                    }
                    self.detail_writer.append(row)
                    detail_rows.append(row)
        finally:
            try:
                await query_engine.aclose()
            except Exception:
                query_engine.close()

        summary = self._compute_summary(experiment_id, exp_def, query_mode, detail_rows)
        self.summary_writer.append(summary)
        return summary

    async def evaluate_many(
        self,
        experiment_ids: Iterable[str],
        *,
        questions_per_doc: int = 10,
        regenerate_gold: bool = False,
        rejudge: bool = False,
        query_mode: str = "mix",
    ) -> List[Dict[str, Any]]:
        results = []
        for experiment_id in experiment_ids:
            results.append(
                await self.evaluate_experiment(
                    experiment_id,
                    questions_per_doc=questions_per_doc,
                    regenerate_gold=regenerate_gold,
                    rejudge=rejudge,
                    query_mode=query_mode,
                )
            )
        return results
