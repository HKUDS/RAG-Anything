from __future__ import annotations

import hashlib
import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.config import ENV
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.experiments.retrieval.definitions import RETRIEVAL_EXPERIMENTS
from src.workbench.observability import CSVReportWriter, JSONLReportWriter
from src.workbench.query import RAGQueryEngine


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize_keywords(text: str) -> set[str]:
    normalized = _normalize_text(text)
    return {token for token in re.split(r"[^a-z0-9]+", normalized) if token}


def _resolve_successful_docs_for_pipeline_experiment(exp_def) -> List[Path]:
    manifest_path = Path(ENV.output_base_dir) / exp_def.id / "processed_manifest.json"
    if manifest_path.exists():
        data = _load_json(manifest_path)
        files = data.get("files", {}) if isinstance(data, dict) else {}
        resolved: List[Path] = []
        for meta in files.values():
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

    input_dir = Path(exp_def.input_dir_override or ENV.input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    docs = [p for p in input_dir.glob("*.*") if p.is_file()]
    if not docs:
        raise RuntimeError(f"No documents found in {input_dir}")
    return docs


class RetrievalEvaluator:
    summary_header = [
        "Timestamp",
        "Retrieval_Experiment_ID",
        "Base_Experiment_ID",
        "Experiment_Profile",
        "Provider",
        "Experiment_Parser",
        "Query_Mode",
        "Documents_Evaluated",
        "Questions_Total",
        "Evidence_Recall_at_5",
        "Evidence_Recall_at_10",
        "MRR",
        "Precision_at_5",
        "Status",
    ]

    def __init__(
        self,
        *,
        summary_report_file: Path | None = None,
        detail_report_file: Path | None = None,
        gold_dir: Path | None = None,
    ):
        reports_dir = Path(ENV.output_base_dir) / "reports"
        self.summary_writer = CSVReportWriter(
            Path(summary_report_file or reports_dir / "retrieval_benchmark_summary.csv"),
            self.summary_header,
        )
        self.detail_writer = JSONLReportWriter(
            Path(detail_report_file or reports_dir / "retrieval_benchmark_details.jsonl")
        )
        self.gold_dir = Path(gold_dir or Path("datasets/pipeline_qa/gold_qa"))

    def _remove_existing_records(self, retrieval_experiment_id: str) -> None:
        summary_path = self.summary_writer.path
        if summary_path.exists():
            with open(summary_path, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            filtered = [
                row
                for row in rows
                if row.get("Retrieval_Experiment_ID") != retrieval_experiment_id
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
                    if record.get("retrieval_experiment_id") == retrieval_experiment_id:
                        continue
                    kept_lines.append(json.dumps(record, ensure_ascii=False))
            with open(detail_path, "w", encoding="utf-8") as f:
                for line in kept_lines:
                    f.write(line + "\n")

    def _gold_file(self, doc_path: Path) -> Path:
        return self.gold_dir / f"{doc_path.stem}.json"

    @staticmethod
    def _relevance_score(
        chunk_content: str,
        evidence_snippets: list[str],
        evidence_keywords: list[str],
    ) -> int:
        normalized_chunk = _normalize_text(chunk_content)
        if not normalized_chunk:
            return 0

        normalized_snippets = [_normalize_text(snippet) for snippet in evidence_snippets if str(snippet).strip()]
        matched_snippet = any(
            snippet and (snippet in normalized_chunk or normalized_chunk in snippet)
            for snippet in normalized_snippets
        )

        keyword_set = {_normalize_text(keyword) for keyword in evidence_keywords if str(keyword).strip()}
        chunk_tokens = _tokenize_keywords(normalized_chunk)
        matched_keywords = [kw for kw in keyword_set if kw and kw in chunk_tokens]

        if matched_snippet:
            return 2
        if len(matched_keywords) >= 2:
            return 2
        if len(matched_keywords) == 1:
            return 1
        return 0

    @classmethod
    def _rank_chunks(
        cls,
        chunks: list[dict[str, Any]],
        evidence_snippets: list[str],
        evidence_keywords: list[str],
    ) -> list[dict[str, Any]]:
        ranked = []
        for idx, chunk in enumerate(chunks):
            content = str(chunk.get("content", "") or "")
            relevance = cls._relevance_score(content, evidence_snippets, evidence_keywords)
            ranked.append(
                {
                    "rank": idx + 1,
                    "reference_id": chunk.get("reference_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "file_path": chunk.get("file_path", ""),
                    "content": content,
                    "relevance_score": relevance,
                }
            )
        return ranked

    @staticmethod
    def _recall_at_k(ranked_chunks: list[dict[str, Any]], k: int) -> int:
        return int(any(chunk["relevance_score"] > 0 for chunk in ranked_chunks[:k]))

    @staticmethod
    def _mrr(ranked_chunks: list[dict[str, Any]]) -> float:
        for chunk in ranked_chunks:
            if chunk["relevance_score"] > 0:
                return 1.0 / float(chunk["rank"])
        return 0.0

    @staticmethod
    def _precision_at_k(ranked_chunks: list[dict[str, Any]], k: int) -> float:
        top_chunks = ranked_chunks[:k]
        if not top_chunks:
            return 0.0
        relevant = sum(1 for chunk in top_chunks if chunk["relevance_score"] > 0)
        return float(relevant) / float(len(top_chunks))

    @classmethod
    def _compute_summary(cls, exp_def, detail_rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(detail_rows)
        if total == 0:
            return {
                "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Retrieval_Experiment_ID": exp_def.id,
                "Base_Experiment_ID": exp_def.base_experiment_id,
                "Experiment_Profile": PIPELINE_EXPERIMENTS[exp_def.base_experiment_id].profile_name,
                "Provider": PIPELINE_EXPERIMENTS[exp_def.base_experiment_id].provider,
                "Experiment_Parser": PIPELINE_EXPERIMENTS[exp_def.base_experiment_id].parser,
                "Query_Mode": exp_def.query_mode,
                "Documents_Evaluated": 0,
                "Questions_Total": 0,
                "Evidence_Recall_at_5": "0.0000",
                "Evidence_Recall_at_10": "0.0000",
                "MRR": "0.0000",
                "Precision_at_5": "0.0000",
                "Status": "NoData",
            }

        pipeline_exp = PIPELINE_EXPERIMENTS[exp_def.base_experiment_id]
        docs = len({row["document_name"] for row in detail_rows})
        recall_5 = sum(float(row["evidence_recall_at_5"]) for row in detail_rows) / total
        recall_10 = sum(float(row["evidence_recall_at_10"]) for row in detail_rows) / total
        mrr = sum(float(row["mrr"]) for row in detail_rows) / total
        precision_5 = sum(float(row["precision_at_5"]) for row in detail_rows) / total
        return {
            "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Retrieval_Experiment_ID": exp_def.id,
            "Base_Experiment_ID": exp_def.base_experiment_id,
            "Experiment_Profile": pipeline_exp.profile_name,
            "Provider": pipeline_exp.provider,
            "Experiment_Parser": pipeline_exp.parser,
            "Query_Mode": exp_def.query_mode,
            "Documents_Evaluated": docs,
            "Questions_Total": total,
            "Evidence_Recall_at_5": f"{recall_5:.4f}",
            "Evidence_Recall_at_10": f"{recall_10:.4f}",
            "MRR": f"{mrr:.4f}",
            "Precision_at_5": f"{precision_5:.4f}",
            "Status": "Success",
        }

    async def evaluate_experiment(self, retrieval_experiment_id: str) -> dict[str, Any]:
        if retrieval_experiment_id not in RETRIEVAL_EXPERIMENTS:
            raise ValueError(f"Unknown retrieval experiment: {retrieval_experiment_id}")

        exp_def = RETRIEVAL_EXPERIMENTS[retrieval_experiment_id]
        if exp_def.base_experiment_id not in PIPELINE_EXPERIMENTS:
            raise ValueError(f"Unknown base pipeline experiment: {exp_def.base_experiment_id}")

        self._remove_existing_records(exp_def.id)

        pipeline_exp = PIPELINE_EXPERIMENTS[exp_def.base_experiment_id]
        docs = _resolve_successful_docs_for_pipeline_experiment(pipeline_exp)

        query_engine = RAGQueryEngine(
            exp_def.base_experiment_id,
            reranker_name=exp_def.reranker_name,
        )
        await query_engine.initialize()
        detail_rows: list[dict[str, Any]] = []

        try:
            for doc_path in docs:
                gold_file = self._gold_file(doc_path)
                if not gold_file.exists():
                    raise FileNotFoundError(
                        f"Missing gold QA file for retrieval benchmark: {gold_file}. Run pipeline QA generation first."
                    )
                gold = _load_json(gold_file)
                for qa_item in gold.get("questions", []):
                    retrieval_trace = await query_engine.retrieve_data(
                        qa_item.get("question", ""),
                        mode=exp_def.query_mode,
                        **dict(exp_def.retrieval_kwargs),
                    )
                    raw_result = retrieval_trace.get("raw_result", {}) or {}
                    data = raw_result.get("data", {}) if isinstance(raw_result, dict) else {}
                    chunks = list(data.get("chunks", [])) if isinstance(data, dict) else []
                    ranked_chunks = self._rank_chunks(
                        chunks,
                        list(qa_item.get("evidence_snippets", [])),
                        list(qa_item.get("evidence_keywords", [])),
                    )

                    recall_5 = self._recall_at_k(ranked_chunks, 5)
                    recall_10 = self._recall_at_k(ranked_chunks, 10)
                    mrr = self._mrr(ranked_chunks)
                    precision_5 = self._precision_at_k(ranked_chunks, 5)

                    row = {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "retrieval_experiment_id": exp_def.id,
                        "base_experiment_id": exp_def.base_experiment_id,
                        "experiment_profile": pipeline_exp.profile_name,
                        "provider": pipeline_exp.provider,
                        "experiment_parser": pipeline_exp.parser,
                        "document_name": doc_path.name,
                        "question_id": qa_item.get("question_id"),
                        "difficulty": qa_item.get("difficulty"),
                        "question_type": qa_item.get("question_type"),
                        "question": qa_item.get("question"),
                        "gold_evidence_snippets": qa_item.get("evidence_snippets", []),
                        "gold_evidence_keywords": qa_item.get("evidence_keywords", []),
                        "query_mode": exp_def.query_mode,
                        "reranker_name": exp_def.reranker_name,
                        "retrieval_kwargs": dict(exp_def.retrieval_kwargs),
                        "total_retrieved_chunks": len(ranked_chunks),
                        "evidence_recall_at_5": recall_5,
                        "evidence_recall_at_10": recall_10,
                        "mrr": round(mrr, 6),
                        "precision_at_5": round(precision_5, 6),
                        "top_chunks": ranked_chunks[:10],
                        "processing_info": raw_result.get("metadata", {}).get("processing_info", {}) if isinstance(raw_result, dict) else {},
                    }
                    self.detail_writer.append(row)
                    detail_rows.append(row)
        finally:
            try:
                await query_engine.aclose()
            except Exception:
                query_engine.close()

        summary = self._compute_summary(exp_def, detail_rows)
        self.summary_writer.append(summary)
        return summary

    async def evaluate_many(self, retrieval_experiment_ids: Iterable[str]) -> list[dict[str, Any]]:
        results = []
        for retrieval_experiment_id in retrieval_experiment_ids:
            results.append(await self.evaluate_experiment(retrieval_experiment_id))
        return results
