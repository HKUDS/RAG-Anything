from __future__ import annotations

import base64
import csv
import html as html_lib
import json
import math
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
from pyvis.network import Network

from src.config import ENV
from src.pruning.algorithms import prune_baseline, prune_hybrid
from src.pruning.semantic_summary import (
    EmbeddingSemanticSummarizer,
    GlobalNarrativeSteinerSummarizer,
    SemanticSummaryConfig,
)
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.experiments.pruning.definitions import PRUNING_EXPERIMENTS
from src.workbench.judging import build_openai_pruning_client
from src.workbench.observability import CSVReportWriter, JSONLReportWriter


GENERIC_NODE_TERMS = {
    "study",
    "analysis",
    "result",
    "results",
    "data",
    "method",
    "methods",
    "content",
    "document",
    "page",
    "entity",
    "information",
}


def _normalize_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", _normalize_text(text)) if token}


def _split_source_ids(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part for part in re.split(r"[,\n;|]+", raw) if part.strip()]


def _is_chunk_node(node_id: str, attrs: dict[str, Any]) -> bool:
    node_id_str = str(node_id)
    entity_type = _normalize_text(attrs.get("entity_type", ""))
    return node_id_str.startswith("chunk-") or entity_type in {"chunk", "textchunk", "documentchunk"}


def _is_multimodal_anchor(attrs: dict[str, Any]) -> bool:
    entity_type = _normalize_text(attrs.get("entity_type", ""))
    return any(
        token in entity_type
        for token in ["visual", "table", "figure", "image", "clinicaltable"]
    )


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _trim(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_successful_docs_for_pipeline_experiment(exp_def) -> list[Path]:
    manifest_path = Path(ENV.output_base_dir) / exp_def.id / "processed_manifest.json"
    if manifest_path.exists():
        data = _load_json(manifest_path)
        files = data.get("files", {}) if isinstance(data, dict) else {}
        resolved: list[Path] = []
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


@dataclass
class GraphBenchmarkContext:
    graph: nx.Graph
    base_experiment_id: str
    important_nodes: set[str]
    evidence_nodes: set[str]
    communities: list[set[str]]
    doc_names: set[str]


class GraphContextBuilder:
    def __init__(self, gold_dir: Path | None = None):
        self.gold_dir = Path(gold_dir or Path("datasets/pipeline_qa/gold_qa"))

    def load_context(self, base_experiment_id: str) -> GraphBenchmarkContext:
        if base_experiment_id not in PIPELINE_EXPERIMENTS:
            raise ValueError(f"Unknown base pipeline experiment: {base_experiment_id}")

        pipeline_exp = PIPELINE_EXPERIMENTS[base_experiment_id]
        graph_path = Path(ENV.output_base_dir) / base_experiment_id / "rag_storage" / "graph_chunk_entity_relation.graphml"
        if not graph_path.exists():
            raise FileNotFoundError(f"Graph file not found: {graph_path}")

        graph = nx.read_graphml(graph_path)
        docs = _resolve_successful_docs_for_pipeline_experiment(pipeline_exp)
        doc_names = {doc.name for doc in docs}
        evidence_nodes = self._resolve_evidence_nodes(graph, docs)
        important_nodes, communities = self._resolve_structural_ground_truth(graph)
        return GraphBenchmarkContext(
            graph=graph,
            base_experiment_id=base_experiment_id,
            important_nodes=important_nodes,
            evidence_nodes=evidence_nodes,
            communities=communities,
            doc_names=doc_names,
        )

    def _resolve_evidence_nodes(self, graph: nx.Graph, docs: list[Path]) -> set[str]:
        gold_records: list[dict[str, Any]] = []
        for doc in docs:
            gold_path = self.gold_dir / f"{doc.stem}.json"
            if gold_path.exists():
                gold_records.append(_load_json(gold_path))

        evidence_snippets: list[str] = []
        evidence_keywords: list[str] = []
        for record in gold_records:
            for qa_item in record.get("questions", []):
                evidence_snippets.extend(list(qa_item.get("evidence_snippets", [])))
                evidence_keywords.extend(list(qa_item.get("evidence_keywords", [])))

        evidence_nodes: set[str] = set()
        normalized_snippets = [_normalize_text(text) for text in evidence_snippets if str(text).strip()]
        normalized_keywords = {_normalize_text(text) for text in evidence_keywords if str(text).strip()}

        for node_id, attrs in graph.nodes(data=True):
            if _is_chunk_node(node_id, attrs):
                continue
            haystack = " ".join(
                [
                    str(node_id),
                    str(attrs.get("entity_id", "")),
                    str(attrs.get("description", "")),
                    str(attrs.get("entity_type", "")),
                ]
            )
            normalized_haystack = _normalize_text(haystack)
            token_set = _tokenize(normalized_haystack)

            snippet_hit = any(
                snippet and (snippet in normalized_haystack or normalized_haystack in snippet)
                for snippet in normalized_snippets
            )
            keyword_hits = sum(1 for keyword in normalized_keywords if keyword and keyword in token_set)
            if snippet_hit or keyword_hits >= 1:
                evidence_nodes.add(str(node_id))

        return evidence_nodes

    @staticmethod
    def _resolve_structural_ground_truth(graph: nx.Graph) -> tuple[set[str], list[set[str]]]:
        entity_graph = graph.copy()
        entity_graph.remove_nodes_from(
            [node_id for node_id, attrs in graph.nodes(data=True) if _is_chunk_node(node_id, attrs)]
        )

        if entity_graph.number_of_nodes() == 0:
            return set(), []

        degrees = dict(entity_graph.degree())
        top_degree = [node for node, _ in sorted(degrees.items(), key=lambda item: item[1], reverse=True)[:20]]

        try:
            betweenness = nx.betweenness_centrality(entity_graph)
        except Exception:
            betweenness = {node: 0.0 for node in entity_graph.nodes()}
        top_betweenness = [
            node for node, _ in sorted(betweenness.items(), key=lambda item: item[1], reverse=True)[:20]
        ]

        try:
            pagerank = nx.pagerank(entity_graph)
        except Exception:
            pagerank = {node: 0.0 for node in entity_graph.nodes()}
        top_pagerank = [node for node, _ in sorted(pagerank.items(), key=lambda item: item[1], reverse=True)[:20]]

        try:
            communities = [set(community) for community in nx.community.louvain_communities(entity_graph, seed=42)]
        except Exception:
            communities = [set(entity_graph.nodes())]

        important_nodes = set(top_degree) | set(top_betweenness) | set(top_pagerank)
        return important_nodes, communities


class PruningMethodSuite:
    @staticmethod
    def baseline(graph: nx.Graph, top_k: int) -> tuple[list[str], dict[str, Any]]:
        pruned = prune_baseline(graph, max_nodes=top_k, ensure_coverage=False)
        selected = list(pruned.nodes())
        return selected, {"candidate_pool_size": len(selected)}

    @staticmethod
    def hybrid(graph: nx.Graph, top_k: int) -> tuple[list[str], dict[str, Any]]:
        pruned = prune_hybrid(graph, max_nodes=top_k, ensure_coverage=False)
        selected = list(pruned.nodes())
        return selected, {"candidate_pool_size": len(selected)}

    @staticmethod
    def personalized_pagerank(
        graph: nx.Graph,
        top_k: int,
        evidence_nodes: set[str],
    ) -> tuple[list[str], dict[str, Any]]:
        candidate_graph = graph.copy()
        personalization: dict[str, float] = {}
        for node_id, attrs in candidate_graph.nodes(data=True):
            base = 0.10
            if str(node_id) in evidence_nodes:
                base += 1.5
            if _is_multimodal_anchor(attrs):
                base += 0.8
            base += min(1.0, len(_split_source_ids(attrs.get("source_id", ""))) * 0.2)
            if _is_chunk_node(node_id, attrs):
                base *= 0.05
            personalization[str(node_id)] = base

        try:
            scores = nx.pagerank(candidate_graph, personalization=personalization)
        except Exception:
            scores = {str(node_id): float(candidate_graph.degree(node_id)) for node_id in candidate_graph.nodes()}

        ranked = sorted(candidate_graph.nodes(), key=lambda node_id: scores.get(str(node_id), 0.0), reverse=True)
        selected: list[str] = []
        for node_id in ranked:
            if _is_chunk_node(node_id, candidate_graph.nodes[node_id]):
                continue
            selected.append(str(node_id))
            if len(selected) >= top_k:
                break
        return selected, {"candidate_pool_size": len(ranked)}


class CandidatePoolBuilder:
    def __init__(self, context: GraphBenchmarkContext):
        self.context = context

    def build(
        self,
        candidate_pool_size: int,
        *,
        include_evidence: bool = True,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        graph = self.context.graph
        working_graph = graph.copy()
        working_graph.remove_nodes_from(
            [node_id for node_id, attrs in graph.nodes(data=True) if _is_chunk_node(node_id, attrs)]
        )
        if working_graph.number_of_nodes() == 0 or candidate_pool_size <= 0:
            return [], []

        degrees = dict(working_graph.degree())
        max_degree = max(degrees.values()) if degrees else 1
        try:
            pagerank = nx.pagerank(working_graph)
        except Exception:
            pagerank = {node_id: 0.0 for node_id in working_graph.nodes()}
        try:
            betweenness = nx.betweenness_centrality(working_graph)
        except Exception:
            betweenness = {node_id: 0.0 for node_id in working_graph.nodes()}
        community_lookup: dict[str, int] = {}
        for idx, community in enumerate(self.context.communities):
            for node_id in community:
                community_lookup[str(node_id)] = idx

        max_pr = max(pagerank.values()) if pagerank else 1.0
        max_bt = max(betweenness.values()) if betweenness else 1.0

        rows: list[dict[str, Any]] = []
        for node_id, attrs in working_graph.nodes(data=True):
            node_id = str(node_id)
            degree_norm = degrees.get(node_id, 0) / max_degree if max_degree else 0.0
            pr_norm = pagerank.get(node_id, 0.0) / max_pr if max_pr else 0.0
            bt_norm = betweenness.get(node_id, 0.0) / max_bt if max_bt else 0.0
            evidence_hit = 1.0 if include_evidence and node_id in self.context.evidence_nodes else 0.0
            support_count = len(_split_source_ids(attrs.get("source_id", "")))
            multimodal = 1.0 if _is_multimodal_anchor(attrs) else 0.0
            score = (
                0.30 * pr_norm
                + 0.25 * bt_norm
                + 0.20 * degree_norm
                + 0.15 * evidence_hit
                + 0.10 * multimodal
                + min(0.10, support_count * 0.02)
            )
            neighbors = sorted(
                (str(neighbor) for neighbor in working_graph.neighbors(node_id)),
                key=lambda neighbor: degrees.get(neighbor, 0),
                reverse=True,
            )[:4]
            rows.append(
                {
                    "node_id": node_id,
                    "label": str(attrs.get("entity_id", node_id)),
                    "entity_type": str(attrs.get("entity_type", "")),
                    "description": _trim(attrs.get("description", ""), 160),
                    "importance_score": round(score, 6),
                    "evidence_hit": bool(evidence_hit),
                    "multimodal_anchor": bool(multimodal),
                    "degree": degrees.get(node_id, 0),
                    "community_id": int(community_lookup.get(node_id, -1)),
                    "support_count": support_count,
                    "neighbors": neighbors,
                }
            )

        rows.sort(key=lambda item: item["importance_score"], reverse=True)
        score_lookup = {row["node_id"]: row["importance_score"] for row in rows}

        selected_ids: list[str] = []
        selected_set: set[str] = set()

        def append_candidate(node_id: str) -> bool:
            if len(selected_ids) >= candidate_pool_size:
                return False
            node_id = str(node_id)
            if node_id not in working_graph or node_id in selected_set:
                return True
            selected_ids.append(node_id)
            selected_set.add(node_id)
            return True

        if include_evidence:
            evidence_candidates = [
                str(node_id)
                for node_id in self.context.evidence_nodes
                if str(node_id) in working_graph
            ]
            evidence_candidates.sort(
                key=lambda node_id: score_lookup.get(node_id, 0.0),
                reverse=True,
            )
            for node_id in evidence_candidates:
                if not append_candidate(node_id):
                    break

        for community in self.context.communities:
            if len(selected_ids) >= candidate_pool_size:
                break
            community_candidates = [node_id for node_id in community if node_id in working_graph]
            community_candidates.sort(
                key=lambda node_id: score_lookup.get(str(node_id), 0.0),
                reverse=True,
            )
            for node_id in community_candidates[:2]:
                if not append_candidate(node_id):
                    break

        for row in rows:
            if not append_candidate(row["node_id"]):
                break

        candidate_rows = [row for row in rows if row["node_id"] in selected_set]
        candidate_rows.sort(key=lambda item: item["importance_score"], reverse=True)
        ordered_ids = [row["node_id"] for row in candidate_rows]
        return candidate_rows, ordered_ids


class LLMPruner:
    def __init__(self, *, allow_merge: bool, model_name: str | None = None):
        self.allow_merge = allow_merge
        self.client = build_openai_pruning_client(model_name=model_name)

    async def select(
        self,
        *,
        candidate_rows: list[dict[str, Any]],
        ordered_candidate_ids: list[str],
        top_k: int,
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
        payload = json.dumps(candidate_rows, ensure_ascii=False, indent=2)
        response = await self.client.select_nodes(
            candidate_json=payload,
            top_k=top_k,
            allow_merge=self.allow_merge,
        )
        selected_ids = [
            node_id
            for node_id in response.get("selected_node_ids", [])
            if node_id in ordered_candidate_ids
        ]
        seen = set(selected_ids)
        for node_id in ordered_candidate_ids:
            if len(selected_ids) >= top_k:
                break
            if node_id not in seen:
                selected_ids.append(node_id)
                seen.add(node_id)

        selected_ids = selected_ids[:top_k]
        merge_groups = self._validate_merge_groups(
            response.get("merge_groups", []),
            selected_ids,
            candidate_rows,
        )
        return selected_ids, merge_groups, response

    def _validate_merge_groups(
        self,
        groups: Any,
        selected_ids: list[str],
        candidate_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self.allow_merge or not isinstance(groups, list):
            return []

        candidate_lookup = {row["node_id"]: row for row in candidate_rows}
        selected_set = set(selected_ids)
        used_members: set[str] = set()
        validated: list[dict[str, Any]] = []

        for group in groups:
            if not isinstance(group, dict):
                continue
            members = [node_id for node_id in group.get("member_node_ids", []) if node_id in selected_set]
            members = [node_id for node_id in members if node_id not in used_members]
            if len(members) < 2 or len(members) > 4:
                continue

            member_rows = [candidate_lookup[node_id] for node_id in members if node_id in candidate_lookup]
            if len(member_rows) != len(members):
                continue

            types = {_normalize_text(row.get("entity_type", "")) for row in member_rows}
            lexical_scores = []
            neighbor_sets = [set(row.get("neighbors", [])) for row in member_rows]
            for i in range(len(member_rows)):
                for j in range(i + 1, len(member_rows)):
                    tokens_i = _tokenize(member_rows[i]["label"])
                    tokens_j = _tokenize(member_rows[j]["label"])
                    union = tokens_i | tokens_j
                    overlap = (tokens_i & tokens_j)
                    lexical_scores.append(len(overlap) / len(union) if union else 0.0)
            avg_lexical = sum(lexical_scores) / len(lexical_scores) if lexical_scores else 0.0
            neighbor_overlap = 0.0
            if len(neighbor_sets) >= 2:
                union_neighbors = set.union(*neighbor_sets)
                inter_neighbors = set.intersection(*neighbor_sets)
                neighbor_overlap = len(inter_neighbors) / len(union_neighbors) if union_neighbors else 0.0

            type_safe = len(types) == 1
            semantic_safe = avg_lexical >= 0.45 or neighbor_overlap >= 0.60
            if not (type_safe and semantic_safe):
                continue

            merged_label = str(group.get("merged_label", "")).strip() or member_rows[0]["label"]
            confidence = min(1.0, max(0.0, _safe_float(group.get("confidence", 0.0))))
            reason = str(group.get("reason", "")).strip()
            validated.append(
                {
                    "merged_label": merged_label,
                    "member_node_ids": members,
                    "reason": reason,
                    "confidence": confidence,
                    "merge_safety_score": round((avg_lexical + neighbor_overlap + 1.0) / 3.0, 6),
                }
            )
            used_members.update(members)

        return validated


IMAGE_EXTENSIONS = {".apng", ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


class ChunkMediaResolver:
    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.text_chunks = self._load_text_chunks(self.storage_dir / "kv_store_text_chunks.json")

    def resolve_for_node(self, node_id: str, attrs: dict[str, Any]) -> dict[str, Any]:
        source_ids = _split_source_ids(attrs.get("source_id", ""))
        chunk_contents = [self._chunk_content(source_id) for source_id in source_ids]
        content = "\n\n".join(part for part in chunk_contents if part)
        entity_type = _normalize_text(attrs.get("entity_type", ""))

        media_path = self._resolve_media_path(
            self._first_attr(
                attrs,
                ["media_path", "img_path", "image_path", "table_img_path", "equation_img_path"],
            )
            or self._extract_line(content, "Image Path")
        )
        table_body = self._first_attr(attrs, ["table_body", "structure", "table_html"])
        if not table_body:
            table_body = self._extract_block(content, "Structure", ["Footnotes:", "Analysis:", "Caption:", "Equation:", "Format:"])

        equation_text = ""
        if "equation" in entity_type:
            equation_text = self._first_attr(attrs, ["equation_text", "latex", "text"])
        if not equation_text:
            equation_text = self._extract_line(content, "Equation") or self._extract_block(content, "Equation", ["Format:", "Analysis:"])
        equation_format = self._first_attr(attrs, ["equation_format", "text_format"]) or self._extract_line(content, "Format")
        caption = self._extract_block(content, "Caption", ["Structure:", "Footnotes:", "Analysis:", "Equation:", "Format:"])

        media_type = self._infer_media_type(entity_type, content, media_path, table_body, equation_text)
        media_path_exists = bool(media_path and Path(media_path).exists())
        return {
            "source_chunk_ids": source_ids,
            "source_file": str(attrs.get("file_path", "")),
            "media_type": media_type,
            "media_path": media_path,
            "media_path_exists": media_path_exists,
            "media_caption": _trim(caption, 500),
            "table_body": self._limit_block(table_body),
            "equation_text": _trim(equation_text, 1200),
            "equation_format": _trim(equation_format, 80),
            "media_available": bool(media_path_exists or table_body or equation_text),
        }

    @staticmethod
    def _load_text_chunks(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = _load_json(path)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _chunk_content(self, source_id: str) -> str:
        chunk = self.text_chunks.get(source_id)
        if isinstance(chunk, dict):
            return str(chunk.get("content", ""))
        if isinstance(chunk, str):
            return chunk
        return ""

    @staticmethod
    def _first_attr(attrs: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = str(attrs.get(key, "")).strip()
            if value and value.lower() not in {"none", "null", "n/a"}:
                return value
        return ""

    @staticmethod
    def _extract_line(content: str, field_name: str) -> str:
        if not content:
            return ""
        pattern = rf"(?im)^\s*{re.escape(field_name)}\s*:\s*(.*?)\s*$"
        match = re.search(pattern, content)
        if not match:
            return ""
        value = match.group(1).strip()
        return "" if value.lower() in {"none", "null", "n/a"} else value

    @staticmethod
    def _extract_block(content: str, field_name: str, stop_markers: list[str]) -> str:
        if not content:
            return ""
        start_pattern = rf"(?im)^\s*{re.escape(field_name)}\s*:\s*"
        start_match = re.search(start_pattern, content)
        if not start_match:
            return ""
        start = start_match.end()
        stop_positions = []
        for marker in stop_markers:
            stop_match = re.search(rf"(?im)^\s*{re.escape(marker)}", content[start:])
            if stop_match:
                stop_positions.append(start + stop_match.start())
        end = min(stop_positions) if stop_positions else len(content)
        value = content[start:end].strip()
        return "" if value.lower() in {"none", "null", "n/a"} else value

    def _resolve_media_path(self, raw_path: str) -> str:
        raw_path = str(raw_path or "").strip().strip('"').strip("'")
        if not raw_path or raw_path.lower() in {"none", "null", "n/a"}:
            return ""
        candidate = Path(raw_path)
        candidates = [candidate]
        if not candidate.is_absolute():
            candidates.extend(
                [
                    self.storage_dir / candidate,
                    self.storage_dir.parent / candidate,
                    Path(ENV.output_base_dir) / candidate,
                    Path.cwd() / candidate,
                ]
            )
        for path in candidates:
            if path.exists():
                return str(path.resolve())
        return raw_path

    @staticmethod
    def _infer_media_type(
        entity_type: str,
        content: str,
        media_path: str,
        table_body: str,
        equation_text: str,
    ) -> str:
        normalized_content = _normalize_text(content[:80])
        if "table" in entity_type or normalized_content.startswith("table analysis") or table_body:
            return "table"
        if "equation" in entity_type or equation_text:
            return "equation"
        suffix = Path(media_path).suffix.lower() if media_path else ""
        if any(token in entity_type for token in ["image", "figure", "visual"]) or suffix in IMAGE_EXTENSIONS:
            return "image"
        return ""

    @staticmethod
    def _limit_block(value: str, limit: int = 20000) -> str:
        value = str(value or "").strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3].rstrip() + "..."


class GraphPruningMetrics:
    @staticmethod
    def important_node_retention(important_nodes: set[str], retained_source_nodes: set[str]) -> float:
        if not important_nodes:
            return 0.0
        return len(important_nodes & retained_source_nodes) / len(important_nodes)

    @staticmethod
    def evidence_entity_coverage(evidence_nodes: set[str], retained_source_nodes: set[str]) -> float:
        if not evidence_nodes:
            return 0.0
        return len(evidence_nodes & retained_source_nodes) / len(evidence_nodes)

    @staticmethod
    def community_coverage(communities: list[set[str]], retained_source_nodes: set[str]) -> float:
        if not communities:
            return 0.0
        covered = sum(1 for community in communities if community & retained_source_nodes)
        return covered / len(communities)

    @staticmethod
    def connectivity(graph: nx.Graph) -> float:
        if graph.number_of_nodes() == 0:
            return 0.0
        if graph.number_of_nodes() == 1:
            return 1.0
        components = list(nx.connected_components(graph))
        if not components:
            return 0.0
        largest = max(components, key=len)
        return len(largest) / graph.number_of_nodes()

    @staticmethod
    def chunk_leakage_ratio(graph: nx.Graph) -> float:
        if graph.number_of_nodes() == 0:
            return 0.0
        chunk_nodes = sum(1 for node_id, attrs in graph.nodes(data=True) if _is_chunk_node(str(node_id), attrs))
        return chunk_nodes / graph.number_of_nodes()

    @staticmethod
    def noise_ratio(graph: nx.Graph) -> float:
        node_noise = 0
        for node_id, attrs in graph.nodes(data=True):
            label = _normalize_text(attrs.get("entity_id", node_id))
            description = _normalize_text(attrs.get("description", ""))
            label_tokens = _tokenize(label)
            generic_only = label_tokens and label_tokens.issubset(GENERIC_NODE_TERMS)
            if _is_chunk_node(str(node_id), attrs):
                node_noise += 1
            elif generic_only and len(label_tokens) <= 2:
                node_noise += 1
            elif not description or description in {"n/a", "none", "unknown"} or len(description) < 24:
                node_noise += 1

        edge_noise = 0
        for _, _, attrs in graph.edges(data=True):
            description = _normalize_text(attrs.get("description", ""))
            keywords = _normalize_text(attrs.get("keywords", ""))
            if (not description or len(description) < 20) and len(keywords) < 8:
                edge_noise += 1

        denom = graph.number_of_nodes() + graph.number_of_edges()
        if denom == 0:
            return 0.0
        return (node_noise + edge_noise) / denom

    @staticmethod
    def merge_safety(merge_groups: list[dict[str, Any]]) -> float | None:
        if not merge_groups:
            return None
        scores = [_safe_float(group.get("merge_safety_score")) for group in merge_groups]
        if not scores:
            return None
        return sum(scores) / len(scores)

    @staticmethod
    def compression_gain(selected_source_nodes: list[str], graph: nx.Graph) -> float:
        if not selected_source_nodes:
            return 0.0
        return max(0.0, 1.0 - (graph.number_of_nodes() / len(selected_source_nodes)))

    @staticmethod
    def weighted_score(
        *,
        important_node_retention: float,
        evidence_entity_coverage: float,
        community_coverage: float,
        noise_ratio: float,
        chunk_leakage_ratio: float,
        connectivity: float,
    ) -> float:
        return (
            0.25 * important_node_retention
            + 0.25 * evidence_entity_coverage
            + 0.20 * community_coverage
            + 0.15 * connectivity
            + 0.10 * (1.0 - noise_ratio)
            + 0.05 * (1.0 - chunk_leakage_ratio)
        )


class PrunedGraphBuilder:
    @staticmethod
    def build_display_graph(
        graph: nx.Graph,
        selected_node_ids: list[str],
        merge_groups: list[dict[str, Any]],
        edge_allowlist: set[tuple[str, str]] | None = None,
    ) -> tuple[nx.Graph, set[str]]:
        selected_graph = graph.subgraph(selected_node_ids).copy()
        if edge_allowlist is not None:
            removable_edges = []
            for source, target in selected_graph.edges():
                edge_key = tuple(sorted((str(source), str(target))))
                if edge_key not in edge_allowlist:
                    removable_edges.append((source, target))
            if removable_edges:
                selected_graph.remove_edges_from(removable_edges)
        retained_source_nodes = set(selected_graph.nodes())
        if not merge_groups:
            return selected_graph, retained_source_nodes

        merged_graph = selected_graph.copy()
        for index, group in enumerate(merge_groups, start=1):
            members = [node_id for node_id in group.get("member_node_ids", []) if node_id in merged_graph]
            if len(members) < 2:
                continue

            merged_node_id = f"merge::{index}::{group.get('merged_label', 'merged-node')}"
            member_attrs = [merged_graph.nodes[node_id] for node_id in members]
            merged_label = group.get("merged_label") or members[0]
            merged_type = PrunedGraphBuilder._majority_value(member_attrs, "entity_type") or "VirtualMergedEntity"
            merged_description = PrunedGraphBuilder._compose_merged_description(member_attrs, group)
            merged_graph.add_node(
                merged_node_id,
                entity_id=merged_label,
                entity_type=merged_type,
                description=merged_description,
                merged_from="|".join(members),
                is_virtual_merged="true",
            )

            edge_agg: dict[str, dict[str, Any]] = {}
            for member in members:
                for neighbor in list(merged_graph.neighbors(member)):
                    if neighbor in members:
                        continue
                    edge_key = str(neighbor)
                    attrs = merged_graph.get_edge_data(member, neighbor) or {}
                    bucket = edge_agg.setdefault(
                        edge_key,
                        {"weight": 0.0, "keywords": set(), "description_parts": []},
                    )
                    bucket["weight"] += _safe_float(attrs.get("weight", 1.0))
                    keywords = _tokenize(attrs.get("keywords", ""))
                    bucket["keywords"].update(keywords)
                    description = str(attrs.get("description", "")).strip()
                    if description:
                        bucket["description_parts"].append(description)

            for neighbor, payload in edge_agg.items():
                merged_graph.add_edge(
                    merged_node_id,
                    neighbor,
                    weight=payload["weight"] or 1.0,
                    keywords=", ".join(sorted(payload["keywords"]))[:400],
                    description=_trim(" | ".join(payload["description_parts"]), 240),
                )

            merged_graph.remove_nodes_from(members)

        return merged_graph, retained_source_nodes

    @staticmethod
    def _majority_value(attrs_list: list[dict[str, Any]], key: str) -> str:
        counts: dict[str, int] = {}
        for attrs in attrs_list:
            value = str(attrs.get(key, "")).strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
        if not counts:
            return ""
        return max(counts.items(), key=lambda item: item[1])[0]

    @staticmethod
    def _compose_merged_description(
        attrs_list: list[dict[str, Any]],
        group: dict[str, Any],
    ) -> str:
        descriptions = []
        for attrs in attrs_list:
            description = str(attrs.get("description", "")).strip()
            if description and description not in descriptions:
                descriptions.append(description)
        reason = str(group.get("reason", "")).strip()
        merged = descriptions[:2]
        if reason:
            merged.append(f"Virtual merge rationale: {reason}")
        return _trim(" ".join(merged), 320)


class GraphArtifactWriter:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)

    def write(
        self,
        *,
        pruning_experiment_id: str,
        graph: nx.Graph,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        artifact_dir = self.output_root / pruning_experiment_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        graph_path = artifact_dir / "pruned_graph.graphml"
        nx.write_graphml(graph, graph_path)

        html_path = artifact_dir / "pruned_graph.html"
        self._write_html(graph, html_path, metadata)

        metadata_path = artifact_dir / "selection.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return {
            "artifact_dir": str(artifact_dir),
            "graph_path": str(graph_path),
            "html_path": str(html_path),
            "metadata_path": str(metadata_path),
        }

    @staticmethod
    def _write_html(graph: nx.Graph, html_path: Path, metadata: dict[str, Any]) -> None:
        net = Network(height="680px", width="100%", bgcolor="#ffffff", font_color="black", notebook=False)
        node_metadata = {
            str(record.get("node_id")): record
            for record in metadata.get("selected_display_nodes", [])
            if isinstance(record, dict) and record.get("node_id")
        }
        node_tooltips: dict[str, str] = {}
        for node_id, attrs in graph.nodes(data=True):
            node_id = str(node_id)
            label = str(attrs.get("entity_id", node_id))
            record = node_metadata.get(node_id, {})
            node_tooltips[node_id] = GraphArtifactWriter._node_title_html(node_id, attrs, record)

            color = "#97c2fc"
            if str(attrs.get("is_virtual_merged", "")).lower() == "true":
                color = "#f7c873"
            elif _is_multimodal_anchor(attrs):
                color = "#ffb0b0"
            elif _is_chunk_node(node_id, attrs):
                color = "#d3d3d3"

            net.add_node(node_id, label=label, color=color)

        for source, target, attrs in graph.edges(data=True):
            title = _trim(attrs.get("description", "") or attrs.get("keywords", ""), 260)
            width = max(1.0, min(6.0, _safe_float(attrs.get("weight", 1.0))))
            net.add_edge(str(source), str(target), title=title, width=width)

        net.set_options(
            """
        var options = {
          "interaction": {
            "hover": true,
            "tooltipDelay": 1000000
          },
          "physics": {
            "forceAtlas2Based": {
              "gravitationalConstant": -55,
              "centralGravity": 0.01,
              "springLength": 110,
              "springConstant": 0.08
            },
            "maxVelocity": 45,
            "solver": "forceAtlas2Based",
            "timestep": 0.35,
            "stabilization": {"iterations": 120}
          }
        }
        """
        )
        net.save_graph(str(html_path))
        GraphArtifactWriter._inject_custom_hover_tooltips(html_path, node_tooltips)

    @staticmethod
    def _node_title_html(node_id: str, attrs: dict[str, Any], record: dict[str, Any]) -> str:
        label = str(attrs.get("entity_id", node_id))
        entity_type = str(attrs.get("entity_type", "")).strip()
        description = str(attrs.get("description", "")).strip()
        parts = [
            '<div class="rag-tooltip-card">',
            f'<div class="rag-tooltip-title">{GraphArtifactWriter._safe_html(label)}</div>',
        ]
        meta_rows = []
        if entity_type:
            meta_rows.append(("Type", entity_type))
        if record.get("story_order"):
            story = f"#{record.get('story_order')} | {record.get('story_role', '')} | {record.get('chapter_label', '')}"
            meta_rows.append(("Story", story))
        media_type = str(record.get("media_type") or "").strip()
        if media_type:
            meta_rows.append(("Media", media_type))
        if record.get("source_file"):
            meta_rows.append(("Source", str(record.get("source_file"))))
        if meta_rows:
            parts.append('<div class="rag-tooltip-meta-grid">')
            for key, value in meta_rows:
                parts.append(
                    '<div class="rag-tooltip-meta-row">'
                    f'<strong>{GraphArtifactWriter._safe_html(key)}</strong>'
                    f'<span>{GraphArtifactWriter._safe_html(value)}</span>'
                    '</div>'
                )
            parts.append('</div>')

        media_html = GraphArtifactWriter._media_tooltip_html(record)
        if media_html:
            parts.append(media_html)
        if description:
            parts.append(
                '<div class="rag-tooltip-description">'
                f'{GraphArtifactWriter._safe_html(_trim(description, 700))}</div>'
            )
        parts.append('</div>')
        return "".join(parts)

    @staticmethod
    def _media_tooltip_html(record: dict[str, Any]) -> str:
        media_type = str(record.get("media_type") or "").lower()
        media_path = str(record.get("media_path") or "").strip()
        table_body = str(record.get("table_body") or "").strip()
        equation_text = str(record.get("equation_text") or "").strip()
        caption = str(record.get("media_caption") or "").strip()
        parts: list[str] = []

        data_uri = GraphArtifactWriter._embed_image_data_uri(media_path)
        if data_uri:
            alt = GraphArtifactWriter._safe_html(str(record.get("label") or media_type or "media"))
            parts.append(
                '<figure class="rag-tooltip-media">'
                f'<img src="{data_uri}" alt="{alt}" />'
                '</figure>'
            )

        if media_type == "table" and table_body:
            parts.append(GraphArtifactWriter._format_tooltip_table(table_body))
        if media_type == "equation" and equation_text:
            parts.append(
                '<div class="rag-tooltip-equation-wrap">'
                '<div class="rag-tooltip-section-label">Equation</div>'
                '<pre class="rag-tooltip-equation">'
                f'{GraphArtifactWriter._safe_html(_trim(equation_text, 1200))}'
                '</pre></div>'
            )
        if caption:
            parts.append(
                '<figcaption class="rag-tooltip-caption">'
                f'{GraphArtifactWriter._safe_html(_trim(caption, 260))}'
                '</figcaption>'
            )
        return "".join(parts)

    @staticmethod
    def _embed_image_data_uri(media_path: str) -> str:
        media_path = str(media_path or "").strip()
        if not media_path:
            return ""
        path = Path(media_path)
        if not path.exists() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            return ""
        try:
            raw = path.read_bytes()
        except Exception:
            return ""
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _format_tooltip_table(table_body: str) -> str:
        table_body = str(table_body or "").strip()
        if not table_body:
            return ""
        if "<table" in table_body.lower():
            clean_table = re.sub(r"(?is)<script.*?</script>", "", table_body)
            clean_table = _trim(clean_table, 9000)
            return (
                '<div class="rag-tooltip-table-wrap">'
                '<div class="rag-tooltip-section-label">Table</div>'
                f'{clean_table}'
                '</div>'
            )
        return (
            '<div class="rag-tooltip-table-wrap">'
            '<div class="rag-tooltip-section-label">Table</div>'
            '<pre class="rag-tooltip-table-text">'
            f'{GraphArtifactWriter._safe_html(_trim(table_body, 2500))}'
            '</pre></div>'
        )

    @staticmethod
    def _inject_custom_hover_tooltips(html_path: Path, node_tooltips: dict[str, str]) -> None:
        try:
            html_content = html_path.read_text(encoding="utf-8")
        except Exception:
            return
        payload = json.dumps(node_tooltips, ensure_ascii=False)
        injection = f"""
<style>
.vis-tooltip {{
  display: none !important;
}}
.rag-hover-tooltip {{
  position: fixed;
  z-index: 999999;
  display: none;
  max-width: min(520px, calc(100vw - 32px));
  max-height: min(620px, calc(100vh - 32px));
  overflow: auto;
  border: 1px solid #cfd8dc;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.24);
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  pointer-events: none;
}}
.rag-tooltip-card {{
  box-sizing: border-box;
  width: 500px;
  max-width: 100%;
  padding: 12px;
  color: #17202a;
  background: #ffffff;
  font-size: 12px;
  line-height: 1.42;
}}
.rag-tooltip-title {{
  font-size: 14px;
  font-weight: 750;
  margin-bottom: 8px;
}}
.rag-tooltip-meta-grid {{
  display: grid;
  gap: 4px;
  margin-bottom: 8px;
}}
.rag-tooltip-meta-row {{
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}}
.rag-tooltip-meta-row strong {{
  color: #111827;
  font-weight: 700;
}}
.rag-tooltip-meta-row span {{
  color: #374151;
  overflow-wrap: anywhere;
}}
.rag-tooltip-description,
.rag-tooltip-caption {{
  margin-top: 8px;
  color: #34495e;
}}
.rag-tooltip-section-label {{
  margin: 8px 0 4px;
  color: #111827;
  font-weight: 750;
  font-size: 12px;
}}
.rag-tooltip-media {{
  margin: 8px 0;
}}
.rag-tooltip-media img {{
  display: block;
  width: 100%;
  max-height: 320px;
  object-fit: contain;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
}}
.rag-tooltip-table-wrap {{
  max-height: 280px;
  overflow: auto;
  margin-top: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
}}
.rag-tooltip-table-wrap .rag-tooltip-section-label {{
  position: sticky;
  top: 0;
  margin: 0;
  padding: 6px 8px;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
}}
.rag-tooltip-table-wrap table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}}
.rag-tooltip-table-wrap td,
.rag-tooltip-table-wrap th {{
  border: 1px solid #d1d5db;
  padding: 4px 6px;
  vertical-align: top;
}}
.rag-tooltip-equation,
.rag-tooltip-table-text {{
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px;
  margin: 0;
  font-size: 11px;
}}
</style>
<script>
(function() {{
  const RAG_NODE_TOOLTIPS = {payload};
  function installRagHoverTooltip() {{
    if (typeof network === 'undefined' || !network || network.__ragHoverTooltipInstalled) {{
      if (typeof network === 'undefined' || !network) window.setTimeout(installRagHoverTooltip, 80);
      return;
    }}
    network.__ragHoverTooltipInstalled = true;
    const tooltip = document.createElement('div');
    tooltip.className = 'rag-hover-tooltip';
    document.body.appendChild(tooltip);

    function place(event) {{
      const margin = 16;
      let x = event.clientX + margin;
      let y = event.clientY + margin;
      tooltip.style.left = '0px';
      tooltip.style.top = '0px';
      const rect = tooltip.getBoundingClientRect();
      if (x + rect.width > window.innerWidth - 12) x = event.clientX - rect.width - margin;
      if (y + rect.height > window.innerHeight - 12) y = window.innerHeight - rect.height - 12;
      tooltip.style.left = Math.max(12, x) + 'px';
      tooltip.style.top = Math.max(12, y) + 'px';
    }}

    function hide() {{
      tooltip.style.display = 'none';
      tooltip.innerHTML = '';
    }}

    network.on('hoverNode', function(params) {{
      const content = RAG_NODE_TOOLTIPS[String(params.node)];
      if (!content) return;
      tooltip.innerHTML = content;
      tooltip.style.display = 'block';
      const event = params.event && params.event.srcEvent;
      if (event) place(event);
    }});
    network.on('blurNode', hide);
    network.on('dragStart', hide);
    network.on('zoom', hide);
    network.on('click', hide);

    const canvas = document.querySelector('#mynetwork canvas') || document.querySelector('.vis-network canvas');
    if (canvas) {{
      canvas.addEventListener('mousemove', function(event) {{
        if (tooltip.style.display === 'block') place(event);
      }});
      canvas.addEventListener('mouseleave', hide);
    }}
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', installRagHoverTooltip);
  }} else {{
    installRagHoverTooltip();
  }}
}})();
</script>
"""
        marker = "</body>"
        if marker in html_content:
            html_content = html_content.replace(marker, injection + "\n" + marker, 1)
        else:
            html_content += injection
        html_path.write_text(html_content, encoding="utf-8")

    @staticmethod
    def _safe_html(value: Any) -> str:
        return html_lib.escape(str(value or ""), quote=True)


class PruningBenchmarkEvaluator:
    summary_header = [
        "Timestamp",
        "Pruning_Experiment_ID",
        "Base_Experiment_ID",
        "Pruning_Method",
        "Top_K",
        "Candidate_Pool_Size",
        "Actual_Nodes",
        "Actual_Edges",
        "Important_Node_Retention",
        "Evidence_Entity_Coverage",
        "Community_Coverage",
        "Noise_Ratio",
        "Chunk_Leakage_Ratio",
        "Connectivity",
        "Merge_Safety",
        "Compression_Gain",
        "Weighted_Score",
        "Artifact_HTML_Path",
        "Artifact_Metadata_Path",
        "Status",
        "Error",
    ]

    def __init__(
        self,
        *,
        summary_report_file: Path | None = None,
        detail_report_file: Path | None = None,
        artifact_root: Path | None = None,
    ):
        reports_dir = Path(ENV.output_base_dir) / "reports"
        self.summary_writer = CSVReportWriter(
            Path(summary_report_file or reports_dir / "pruning_benchmark_summary.csv"),
            self.summary_header,
        )
        self.detail_writer = JSONLReportWriter(
            Path(detail_report_file or reports_dir / "pruning_benchmark_details.jsonl")
        )
        self.context_builder = GraphContextBuilder()
        self.artifact_writer = GraphArtifactWriter(
            Path(artifact_root or Path(ENV.output_base_dir) / "pruning_benchmark")
        )

    def _remove_existing_records(self, pruning_experiment_id: str) -> None:
        summary_path = self.summary_writer.path
        if summary_path.exists():
            with open(summary_path, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            filtered = [
                row
                for row in rows
                if row.get("Pruning_Experiment_ID") != pruning_experiment_id
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
                    if record.get("pruning_experiment_id") == pruning_experiment_id:
                        continue
                    kept_lines.append(json.dumps(record, ensure_ascii=False))
            with open(detail_path, "w", encoding="utf-8") as f:
                for line in kept_lines:
                    f.write(line + "\n")

    def _build_semantic_summary_config(self) -> SemanticSummaryConfig:
        provider = ENV.pruning_embedding_provider.lower()
        if provider == "openai":
            model = ENV.pruning_embedding_model
            api_key = ENV.openai_api_key
            base_url = None
        elif provider == "ollama":
            model = ENV.ollama_embed
            api_key = ENV.ollama_api_key
            base_url = ENV.ollama_base_url
        else:
            if ENV.openai_api_key:
                model = ENV.pruning_embedding_model
                api_key = ENV.openai_api_key
                base_url = None
            else:
                model = ENV.ollama_embed
                api_key = ENV.ollama_api_key
                base_url = ENV.ollama_base_url
        return SemanticSummaryConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            cache_file=Path(ENV.pruning_embedding_cache_file),
            seed_ratio=ENV.pruning_semantic_seed_ratio,
            mmr_lambda=ENV.pruning_semantic_mmr_lambda,
            max_extra_edges=ENV.pruning_semantic_max_extra_edges,
        )

    def _selected_node_record(
        self,
        *,
        node_id: str,
        attrs: dict[str, Any],
        media_resolver: ChunkMediaResolver,
        story_nodes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        node_id = str(node_id)
        record = {
            "node_id": node_id,
            "label": str(attrs.get("entity_id", node_id)),
            "entity_type": str(attrs.get("entity_type", "")),
            "description": str(attrs.get("description", "")),
            "source_id": str(attrs.get("source_id", "")),
            "file_path": str(attrs.get("file_path", "")),
            "is_virtual_merged": str(attrs.get("is_virtual_merged", "")).lower() == "true",
            "merged_from": str(attrs.get("merged_from", "")),
        }
        record.update(story_nodes.get(node_id, {}))
        record.update(media_resolver.resolve_for_node(node_id, attrs))
        return record

    async def evaluate_experiment(self, pruning_experiment_id: str) -> dict[str, Any]:
        if pruning_experiment_id not in PRUNING_EXPERIMENTS:
            raise ValueError(f"Unknown pruning experiment: {pruning_experiment_id}")

        exp_def = PRUNING_EXPERIMENTS[pruning_experiment_id]
        self._remove_existing_records(pruning_experiment_id)

        try:
            context = self.context_builder.load_context(exp_def.base_experiment_id)
            include_evidence_in_pool = exp_def.pruning_method != "global_narrative_steiner_summary"
            candidate_rows, ordered_candidate_ids = CandidatePoolBuilder(context).build(
                exp_def.candidate_pool_size,
                include_evidence=include_evidence_in_pool,
            )

            edge_allowlist: set[tuple[str, str]] | None = None
            story_nodes: dict[str, dict[str, Any]] = {}
            if exp_def.pruning_method == "baseline":
                selected_ids, debug_info = PruningMethodSuite.baseline(context.graph, exp_def.top_k)
                merge_groups: list[dict[str, Any]] = []
                llm_response = None
            elif exp_def.pruning_method == "hybrid":
                selected_ids, debug_info = PruningMethodSuite.hybrid(context.graph, exp_def.top_k)
                merge_groups = []
                llm_response = None
            elif exp_def.pruning_method == "personalized_pagerank":
                selected_ids, debug_info = PruningMethodSuite.personalized_pagerank(
                    context.graph,
                    exp_def.top_k,
                    context.evidence_nodes,
                )
                merge_groups = []
                llm_response = None
            elif exp_def.pruning_method == "embedding_semantic_summary":
                summarizer = EmbeddingSemanticSummarizer(self._build_semantic_summary_config())
                semantic_result = await summarizer.summarize(
                    graph=context.graph,
                    candidate_rows=candidate_rows,
                    top_k=exp_def.top_k,
                    evidence_nodes=context.evidence_nodes,
                )
                selected_ids = semantic_result.selected_node_ids
                edge_allowlist = semantic_result.edge_allowlist
                debug_info = semantic_result.debug_info
                merge_groups = []
                llm_response = None
            elif exp_def.pruning_method == "global_narrative_steiner_summary":
                summarizer = GlobalNarrativeSteinerSummarizer(self._build_semantic_summary_config())
                narrative_result = await summarizer.summarize(
                    graph=context.graph,
                    candidate_rows=candidate_rows,
                    top_k=exp_def.top_k,
                )
                selected_ids = narrative_result.selected_node_ids
                edge_allowlist = narrative_result.edge_allowlist
                debug_info = narrative_result.debug_info
                story_nodes = narrative_result.story_nodes
                merge_groups = []
                llm_response = None
            elif exp_def.pruning_method == "llm_strict_topk":
                selected_ids, merge_groups, llm_response = await LLMPruner(
                    allow_merge=False,
                    model_name=exp_def.llm_model_name,
                ).select(
                    candidate_rows=candidate_rows,
                    ordered_candidate_ids=ordered_candidate_ids,
                    top_k=exp_def.top_k,
                )
                debug_info = {"candidate_pool_size": len(candidate_rows)}
            elif exp_def.pruning_method == "llm_strict_topk_safe_merge":
                selected_ids, merge_groups, llm_response = await LLMPruner(
                    allow_merge=True,
                    model_name=exp_def.llm_model_name,
                ).select(
                    candidate_rows=candidate_rows,
                    ordered_candidate_ids=ordered_candidate_ids,
                    top_k=exp_def.top_k,
                )
                debug_info = {"candidate_pool_size": len(candidate_rows)}
            else:
                raise ValueError(f"Unsupported pruning method: {exp_def.pruning_method}")

            display_graph, retained_source_nodes = PrunedGraphBuilder.build_display_graph(
                context.graph,
                selected_ids,
                merge_groups,
                edge_allowlist=edge_allowlist,
            )

            merge_safety = GraphPruningMetrics.merge_safety(merge_groups)
            compression_gain = GraphPruningMetrics.compression_gain(selected_ids, display_graph)
            important_retention = GraphPruningMetrics.important_node_retention(
                context.important_nodes,
                retained_source_nodes,
            )
            evidence_coverage = GraphPruningMetrics.evidence_entity_coverage(
                context.evidence_nodes,
                retained_source_nodes,
            )
            community_coverage = GraphPruningMetrics.community_coverage(
                context.communities,
                retained_source_nodes,
            )
            noise_ratio = GraphPruningMetrics.noise_ratio(display_graph)
            chunk_leakage_ratio = GraphPruningMetrics.chunk_leakage_ratio(display_graph)
            connectivity = GraphPruningMetrics.connectivity(display_graph)
            weighted_score = GraphPruningMetrics.weighted_score(
                important_node_retention=important_retention,
                evidence_entity_coverage=evidence_coverage,
                community_coverage=community_coverage,
                noise_ratio=noise_ratio,
                chunk_leakage_ratio=chunk_leakage_ratio,
                connectivity=connectivity,
            )

            media_resolver = ChunkMediaResolver(
                Path(ENV.output_base_dir) / exp_def.base_experiment_id / "rag_storage"
            )
            selected_node_records = []
            for node_id in display_graph.nodes():
                attrs = display_graph.nodes[node_id]
                selected_node_records.append(
                    self._selected_node_record(
                        node_id=str(node_id),
                        attrs=attrs,
                        media_resolver=media_resolver,
                        story_nodes=story_nodes,
                    )
                )

            metadata = {
                "pruning_experiment_id": exp_def.id,
                "base_experiment_id": exp_def.base_experiment_id,
                "pruning_method": exp_def.pruning_method,
                "top_k": exp_def.top_k,
                "candidate_pool_size": len(candidate_rows),
                "selected_source_node_ids": selected_ids,
                "selected_display_nodes": selected_node_records,
                "merge_groups": merge_groups,
                "edge_allowlist": sorted([list(edge) for edge in edge_allowlist]) if edge_allowlist else [],
                "llm_response": llm_response,
                "debug_info": debug_info,
                "metrics": {
                    "important_node_retention": important_retention,
                    "evidence_entity_coverage": evidence_coverage,
                    "community_coverage": community_coverage,
                    "noise_ratio": noise_ratio,
                    "chunk_leakage_ratio": chunk_leakage_ratio,
                    "connectivity": connectivity,
                    "merge_safety": merge_safety,
                    "compression_gain": compression_gain,
                    "weighted_score": weighted_score,
                },
            }
            artifact_paths = self.artifact_writer.write(
                pruning_experiment_id=exp_def.id,
                graph=display_graph,
                metadata=metadata,
            )

            summary_row = {
                "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Pruning_Experiment_ID": exp_def.id,
                "Base_Experiment_ID": exp_def.base_experiment_id,
                "Pruning_Method": exp_def.pruning_method,
                "Top_K": exp_def.top_k,
                "Candidate_Pool_Size": len(candidate_rows),
                "Actual_Nodes": display_graph.number_of_nodes(),
                "Actual_Edges": display_graph.number_of_edges(),
                "Important_Node_Retention": f"{important_retention:.4f}",
                "Evidence_Entity_Coverage": f"{evidence_coverage:.4f}",
                "Community_Coverage": f"{community_coverage:.4f}",
                "Noise_Ratio": f"{noise_ratio:.4f}",
                "Chunk_Leakage_Ratio": f"{chunk_leakage_ratio:.4f}",
                "Connectivity": f"{connectivity:.4f}",
                "Merge_Safety": "" if merge_safety is None else f"{merge_safety:.4f}",
                "Compression_Gain": f"{compression_gain:.4f}",
                "Weighted_Score": f"{weighted_score:.4f}",
                "Artifact_HTML_Path": artifact_paths["html_path"],
                "Artifact_Metadata_Path": artifact_paths["metadata_path"],
                "Status": "Success",
                "Error": "",
            }
            self.summary_writer.append(summary_row)
            self.detail_writer.append(metadata)
            return summary_row
        except Exception as exc:
            summary_row = {
                "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Pruning_Experiment_ID": exp_def.id,
                "Base_Experiment_ID": exp_def.base_experiment_id,
                "Pruning_Method": exp_def.pruning_method,
                "Top_K": exp_def.top_k,
                "Candidate_Pool_Size": 0,
                "Actual_Nodes": 0,
                "Actual_Edges": 0,
                "Important_Node_Retention": "0.0000",
                "Evidence_Entity_Coverage": "0.0000",
                "Community_Coverage": "0.0000",
                "Noise_Ratio": "0.0000",
                "Chunk_Leakage_Ratio": "0.0000",
                "Connectivity": "0.0000",
                "Merge_Safety": "",
                "Compression_Gain": "0.0000",
                "Weighted_Score": "0.0000",
                "Artifact_HTML_Path": "",
                "Artifact_Metadata_Path": "",
                "Status": "Failed",
                "Error": str(exc),
            }
            self.summary_writer.append(summary_row)
            self.detail_writer.append(
                {
                    "pruning_experiment_id": exp_def.id,
                    "base_experiment_id": exp_def.base_experiment_id,
                    "pruning_method": exp_def.pruning_method,
                    "error": str(exc),
                }
            )
            return summary_row

    async def evaluate_many(self, pruning_experiment_ids: Iterable[str]) -> list[dict[str, Any]]:
        results = []
        for pruning_experiment_id in pruning_experiment_ids:
            results.append(await self.evaluate_experiment(pruning_experiment_id))
        return results
