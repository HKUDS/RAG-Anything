from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import networkx as nx


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _tokenize(text: str) -> set[str]:
    text = _normalize_text(text)
    cleaned = []
    token = []
    for ch in text:
        if ch.isalnum():
            token.append(ch)
        else:
            if token:
                cleaned.append("".join(token))
                token = []
    if token:
        cleaned.append("".join(token))
    return set(cleaned)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _trim(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _split_source_ids(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    current: list[str] = []
    for ch in raw:
        if ch in {",", "\n", ";", "|"}:
            if current:
                parts.append("".join(current).strip())
                current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _is_chunk_node(node_id: str, attrs: dict[str, Any]) -> bool:
    node_id_str = str(node_id)
    entity_type = _normalize_text(attrs.get("entity_type", ""))
    return node_id_str.startswith("chunk-") or entity_type in {"chunk", "textchunk", "documentchunk"}


def _is_multimodal_anchor(attrs: dict[str, Any]) -> bool:
    entity_type = _normalize_text(attrs.get("entity_type", ""))
    return any(token in entity_type for token in ["visual", "table", "figure", "image", "clinicaltable"])


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _mean_vector(vectors: Iterable[list[float]], weights: Iterable[float] | None = None) -> list[float]:
    vectors = list(vectors)
    if not vectors:
        return []
    dim = len(vectors[0])
    if dim == 0:
        return []
    if weights is None:
        weights = [1.0] * len(vectors)
    weights = list(weights)
    total = sum(weights) or 1.0
    accum = [0.0] * dim
    for vec, weight in zip(vectors, weights):
        for idx, value in enumerate(vec):
            accum[idx] += value * weight
    return [value / total for value in accum]


@dataclass
class SemanticSummaryConfig:
    model: str
    api_key: str
    base_url: str | None
    cache_file: Path
    seed_ratio: float = 0.6
    mmr_lambda: float = 0.75
    max_extra_edges: int = 12
    embed_batch_size: int = 24
    embed_max_retries: int = 3


class EmbeddingCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except Exception:
                self._data = {}
        else:
            self._data = {}

    @staticmethod
    def _key(model: str, text: str) -> str:
        return hashlib.md5(f"{model}\n{text}".encode("utf-8")).hexdigest()

    def get(self, model: str, text: str) -> list[float] | None:
        key = self._key(model, text)
        value = self._data.get(key)
        if isinstance(value, list) and value:
            return [float(item) for item in value]
        return None

    def put(self, model: str, text: str, vector: list[float]) -> None:
        key = self._key(model, text)
        self._data[key] = vector

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data))


class EmbeddingProvider:
    def __init__(self, config: SemanticSummaryConfig):
        self.config = config
        self.cache = EmbeddingCache(config.cache_file)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        cached: list[list[float] | None] = [
            self.cache.get(self.config.model, text) for text in texts
        ]
        missing_indices = [idx for idx, vec in enumerate(cached) if vec is None]
        if missing_indices:
            from lightrag.llm.openai import openai_embed

            batch_size = max(1, self.config.embed_batch_size)
            for start in range(0, len(missing_indices), batch_size):
                batch_indices = missing_indices[start : start + batch_size]
                batch_texts = [texts[idx] for idx in batch_indices]
                last_exc: Exception | None = None
                for attempt in range(1, self.config.embed_max_retries + 1):
                    try:
                        response = openai_embed.func(
                            batch_texts,
                            model=self.config.model,
                            api_key=self.config.api_key,
                            base_url=self.config.base_url,
                        )
                        if inspect.isawaitable(response):
                            response = await response
                        vectors = [list(map(float, vector)) for vector in response]
                        for idx, vector in zip(batch_indices, vectors):
                            cached[idx] = vector
                            self.cache.put(self.config.model, texts[idx], vector)
                        self.cache.save()
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                        if attempt >= self.config.embed_max_retries:
                            raise
                        await asyncio.sleep(min(30, 2**attempt))
                if last_exc is not None:
                    raise last_exc
        return [vec or [] for vec in cached]


class NodeTextBuilder:
    @staticmethod
    def build(attrs: dict[str, Any], node_id: str) -> str:
        label = str(attrs.get("entity_id", node_id)).strip()
        entity_type = str(attrs.get("entity_type", "")).strip()
        description = _trim(attrs.get("description", ""), 420)
        source_ids = _split_source_ids(attrs.get("source_id", ""))
        multimodal = "yes" if _is_multimodal_anchor(attrs) else "no"
        return (
            f"label: {label}\n"
            f"type: {entity_type}\n"
            f"description: {description}\n"
            f"support_count: {len(source_ids)}\n"
            f"multimodal_anchor: {multimodal}"
        )

    @staticmethod
    def edge_text(graph: nx.Graph, source: str, target: str) -> str:
        attrs = graph.get_edge_data(source, target) or {}
        source_label = str(graph.nodes[source].get("entity_id", source))
        target_label = str(graph.nodes[target].get("entity_id", target))
        keywords = _trim(attrs.get("keywords", ""), 160)
        description = _trim(attrs.get("description", ""), 320)
        return (
            f"source: {source_label}\n"
            f"target: {target_label}\n"
            f"keywords: {keywords}\n"
            f"description: {description}"
        )


@dataclass
class SemanticSummaryResult:
    selected_node_ids: list[str]
    edge_allowlist: set[tuple[str, str]]
    debug_info: dict[str, Any]


@dataclass
class NarrativeSummaryResult:
    selected_node_ids: list[str]
    edge_allowlist: set[tuple[str, str]]
    debug_info: dict[str, Any]
    story_nodes: dict[str, dict[str, Any]]


class EmbeddingSemanticSummarizer:
    def __init__(self, config: SemanticSummaryConfig):
        self.config = config
        self.embedding_provider = EmbeddingProvider(config)

    async def summarize(
        self,
        *,
        graph: nx.Graph,
        candidate_rows: list[dict[str, Any]],
        top_k: int,
        evidence_nodes: set[str],
    ) -> SemanticSummaryResult:
        candidate_lookup = {row["node_id"]: row for row in candidate_rows}
        candidate_ids = [row["node_id"] for row in candidate_rows]
        if not candidate_ids:
            return SemanticSummaryResult([], set(), {"candidate_pool_size": 0})

        node_texts = [
            NodeTextBuilder.build(graph.nodes[node_id], node_id)
            for node_id in candidate_ids
        ]
        node_vectors = await self.embedding_provider.embed_texts(node_texts)
        vector_lookup = dict(zip(candidate_ids, node_vectors))

        weighted_vectors: list[list[float]] = []
        weighted_scores: list[float] = []
        evidence_vectors: list[list[float]] = []
        for row in candidate_rows:
            node_id = row["node_id"]
            vector = vector_lookup[node_id]
            if not vector:
                continue
            weight = 1.0 + _safe_float(row.get("importance_score", 0.0))
            if node_id in evidence_nodes:
                weight += 1.0
                evidence_vectors.append(vector)
            if row.get("multimodal_anchor"):
                weight += 0.25
            weighted_vectors.append(vector)
            weighted_scores.append(weight)

        centroid = _mean_vector(weighted_vectors, weighted_scores)
        evidence_centroid = _mean_vector(evidence_vectors) if evidence_vectors else centroid

        relevance: dict[str, float] = {}
        per_node_debug: dict[str, dict[str, float]] = {}
        for row in candidate_rows:
            node_id = row["node_id"]
            vector = vector_lookup[node_id]
            semantic_salience = _cosine_similarity(vector, centroid)
            evidence_proximity = _cosine_similarity(vector, evidence_centroid)
            structural_prior = _safe_float(row.get("importance_score", 0.0))
            support_bonus = min(0.15, _safe_float(row.get("support_count", 0.0)) * 0.03)
            multimodal_bonus = 0.05 if row.get("multimodal_anchor") else 0.0
            relevance_score = (
                0.45 * semantic_salience
                + 0.20 * evidence_proximity
                + 0.25 * structural_prior
                + support_bonus
                + multimodal_bonus
            )
            relevance[node_id] = relevance_score
            per_node_debug[node_id] = {
                "semantic_salience": round(semantic_salience, 6),
                "evidence_proximity": round(evidence_proximity, 6),
                "structural_prior": round(structural_prior, 6),
                "support_bonus": round(support_bonus, 6),
                "multimodal_bonus": round(multimodal_bonus, 6),
                "relevance_score": round(relevance_score, 6),
            }

        seed_count = max(6, min(top_k, int(round(top_k * self.config.seed_ratio))))
        seed_ids = self._select_seeds_mmr(candidate_ids, relevance, vector_lookup, seed_count)

        working_graph = self._build_working_graph(graph)
        edge_keys = [tuple(sorted((str(source), str(target)))) for source, target in working_graph.edges()]
        edge_vectors = await self._edge_embedding_lookup(working_graph, edge_keys)

        connected_graph = self._build_connected_summary_graph(
            graph=graph,
            seed_ids=seed_ids,
            relevance=relevance,
            centroid=centroid,
            top_k=top_k,
            edge_vectors=edge_vectors,
        )

        debug_info = {
            "candidate_pool_size": len(candidate_rows),
            "seed_count": len(seed_ids),
            "seed_ids": seed_ids,
            "selected_node_count": connected_graph.number_of_nodes(),
            "selected_edge_count": connected_graph.number_of_edges(),
            "node_scores": {node_id: per_node_debug[node_id] for node_id in seed_ids[: min(10, len(seed_ids))]},
        }

        edge_allowlist = {
            tuple(sorted((str(source), str(target))))
            for source, target in connected_graph.edges()
        }
        return SemanticSummaryResult(
            selected_node_ids=[str(node_id) for node_id in connected_graph.nodes()],
            edge_allowlist=edge_allowlist,
            debug_info=debug_info,
        )

    def _select_seeds_mmr(
        self,
        candidate_ids: list[str],
        relevance: dict[str, float],
        vector_lookup: dict[str, list[float]],
        seed_count: int,
    ) -> list[str]:
        if not candidate_ids:
            return []
        selected: list[str] = []
        remaining = set(candidate_ids)

        first = max(candidate_ids, key=lambda node_id: relevance.get(node_id, 0.0))
        selected.append(first)
        remaining.remove(first)

        while remaining and len(selected) < seed_count:
            best_node = None
            best_score = -1e9
            for node_id in remaining:
                rel = relevance.get(node_id, 0.0)
                diversity_penalty = 0.0
                if selected:
                    diversity_penalty = max(
                        _cosine_similarity(vector_lookup.get(node_id, []), vector_lookup.get(other_id, []))
                        for other_id in selected
                    )
                mmr = self.config.mmr_lambda * rel - (1.0 - self.config.mmr_lambda) * diversity_penalty
                if mmr > best_score:
                    best_score = mmr
                    best_node = node_id
            if best_node is None:
                break
            selected.append(best_node)
            remaining.remove(best_node)
        return selected

    async def _edge_embedding_lookup(
        self,
        graph: nx.Graph,
        edge_keys: list[tuple[str, str]],
    ) -> dict[tuple[str, str], list[float]]:
        if not edge_keys:
            return {}
        texts = [NodeTextBuilder.edge_text(graph, source, target) for source, target in edge_keys]
        vectors = await self.embedding_provider.embed_texts(texts)
        return {key: vector for key, vector in zip(edge_keys, vectors)}

    def _edge_non_generic_bonus(self, attrs: dict[str, Any]) -> float:
        keywords = _tokenize(attrs.get("keywords", ""))
        description = _normalize_text(attrs.get("description", ""))
        if not keywords and len(description) < 20:
            return 0.0
        generic_relation_terms = {"related", "relation", "associated", "linked", "contains"}
        if keywords and keywords.issubset(generic_relation_terms):
            return 0.1
        return 0.3

    def _trim_tree_to_budget(
        self,
        tree: nx.Graph,
        seed_ids: set[str],
        relevance: dict[str, float],
        edge_quality: dict[tuple[str, str], float],
        top_k: int,
    ) -> nx.Graph:
        trimmed = tree.copy()
        while trimmed.number_of_nodes() > top_k:
            removable = []
            for node_id in trimmed.nodes():
                if node_id in seed_ids:
                    continue
                if trimmed.degree(node_id) != 1:
                    continue
                neighbor = next(iter(trimmed.neighbors(node_id)))
                edge_key = tuple(sorted((str(node_id), str(neighbor))))
                score = relevance.get(str(node_id), 0.0) + edge_quality.get(edge_key, 0.0)
                removable.append((score, str(node_id)))
            if not removable:
                break
            removable.sort(key=lambda item: item[0])
            trimmed.remove_node(removable[0][1])
        return trimmed

    def _augment_edges(
        self,
        summary_graph: nx.Graph,
        base_graph: nx.Graph,
        edge_quality: dict[tuple[str, str], float],
    ) -> nx.Graph:
        if self.config.max_extra_edges <= 0:
            return summary_graph
        augmented = summary_graph.copy()
        candidates: list[tuple[float, tuple[str, str]]] = []
        selected_nodes = set(str(node_id) for node_id in augmented.nodes())
        for source, target in base_graph.edges():
            edge_key = tuple(sorted((str(source), str(target))))
            if str(source) not in selected_nodes or str(target) not in selected_nodes:
                continue
            if augmented.has_edge(str(source), str(target)):
                continue
            candidates.append((edge_quality.get(edge_key, 0.0), edge_key))
        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, edge_key in candidates[: self.config.max_extra_edges]:
            source, target = edge_key
            attrs = base_graph.get_edge_data(source, target) or {}
            augmented.add_edge(source, target, **attrs)
        return augmented

    def _build_working_graph(self, graph: nx.Graph) -> nx.Graph:
        working = graph.copy()
        working.remove_nodes_from(
            [node_id for node_id, attrs in graph.nodes(data=True) if _is_chunk_node(str(node_id), attrs)]
        )
        if working.is_directed():
            working = working.to_undirected()
        return working

    def _path_exists(self, graph: nx.Graph, source: str, target: str) -> bool:
        try:
            return nx.has_path(graph, source, target)
        except Exception:
            return False

    def _fallback_linking(
        self,
        graph: nx.Graph,
        seed_ids: list[str],
        edge_costs: dict[tuple[str, str], float],
    ) -> nx.Graph:
        summary = nx.Graph()
        for seed in seed_ids:
            if seed in graph:
                summary.add_node(seed, **graph.nodes[seed])
        if len(seed_ids) <= 1:
            return summary
        for idx in range(1, len(seed_ids)):
            source = seed_ids[idx - 1]
            target = seed_ids[idx]
            if not (source in graph and target in graph):
                continue
            try:
                path = nx.shortest_path(
                    graph,
                    source=source,
                    target=target,
                    weight=lambda u, v, attrs: edge_costs.get(tuple(sorted((str(u), str(v)))), 1.0),
                )
            except Exception:
                continue
            nx.add_path(summary, path)
            for node_id in path:
                summary.nodes[node_id].update(graph.nodes[node_id])
            for a, b in zip(path[:-1], path[1:]):
                attrs = graph.get_edge_data(a, b) or {}
                summary.edges[a, b].update(attrs)
        return summary

    def _build_connected_summary_graph(
        self,
        *,
        graph: nx.Graph,
        seed_ids: list[str],
        relevance: dict[str, float],
        centroid: list[float],
        top_k: int,
        edge_vectors: dict[tuple[str, str], list[float]],
    ) -> nx.Graph:
        working_graph = self._build_working_graph(graph)
        if not seed_ids:
            return working_graph.subgraph([]).copy()

        edge_quality: dict[tuple[str, str], float] = {}

        for source, target in working_graph.edges():
            edge_key = tuple(sorted((str(source), str(target))))
            attrs = working_graph.get_edge_data(source, target) or {}
            endpoint_bonus = 0.5 * (
                relevance.get(str(source), 0.0) + relevance.get(str(target), 0.0)
            )
            semantic_bonus = _cosine_similarity(edge_vectors.get(edge_key, []), centroid) if edge_vectors else 0.0
            non_generic_bonus = self._edge_non_generic_bonus(attrs)
            edge_quality[edge_key] = 0.45 * endpoint_bonus + 0.35 * semantic_bonus + 0.20 * non_generic_bonus
            attrs["summary_cost"] = 1.0 / max(0.05, edge_quality[edge_key])

        valid_seeds = [seed for seed in seed_ids if seed in working_graph]
        if len(valid_seeds) == 1:
            return working_graph.subgraph(valid_seeds).copy()

        connected_seed_ids: list[str] = []
        for seed in valid_seeds:
            if not connected_seed_ids:
                connected_seed_ids.append(seed)
                continue
            if any(self._path_exists(working_graph, seed, other) for other in connected_seed_ids):
                connected_seed_ids.append(seed)
        if len(connected_seed_ids) < 2:
            return working_graph.subgraph(valid_seeds[:top_k]).copy()

        try:
            steiner = nx.algorithms.approximation.steinertree.steiner_tree(
                working_graph,
                connected_seed_ids,
                weight="summary_cost",
            )
        except Exception:
            steiner = self._fallback_linking(working_graph, connected_seed_ids, edge_quality)

        trimmed = self._trim_tree_to_budget(steiner, set(connected_seed_ids), relevance, edge_quality, top_k)
        return self._augment_edges(trimmed, working_graph, edge_quality)


class GlobalNarrativeSteinerSummarizer(EmbeddingSemanticSummarizer):
    """Global graph summarizer for presentation-oriented node storytelling.

    Unlike ``EmbeddingSemanticSummarizer``, this method deliberately ignores QA
    evidence nodes. It builds one reusable pruning artifact for the whole graph:
    representative chapter anchors, semantic core nodes, and connector nodes that
    keep the selected story navigable when the graph structure allows it.
    """

    async def summarize(
        self,
        *,
        graph: nx.Graph,
        candidate_rows: list[dict[str, Any]],
        top_k: int,
    ) -> NarrativeSummaryResult:
        candidate_lookup = {row["node_id"]: row for row in candidate_rows}
        candidate_ids = [row["node_id"] for row in candidate_rows if row.get("node_id") in graph]
        if not candidate_ids:
            return NarrativeSummaryResult([], set(), {"candidate_pool_size": 0}, {})

        node_texts = [
            NodeTextBuilder.build(graph.nodes[node_id], node_id)
            for node_id in candidate_ids
        ]
        node_vectors = await self.embedding_provider.embed_texts(node_texts)
        vector_lookup = dict(zip(candidate_ids, node_vectors))

        community_groups = self._group_candidates_by_community(candidate_rows)
        community_centroids = self._community_centroids(community_groups, vector_lookup)
        community_representatives = self._community_representatives(community_groups)
        representative_ids = set(community_representatives.values())

        weighted_vectors: list[list[float]] = []
        weighted_scores: list[float] = []
        for row in candidate_rows:
            node_id = row["node_id"]
            vector = vector_lookup.get(node_id, [])
            if not vector:
                continue
            weight = 1.0 + _safe_float(row.get("importance_score", 0.0))
            weight += min(0.30, _safe_float(row.get("support_count", 0.0)) * 0.05)
            if row.get("multimodal_anchor"):
                weight += 0.35
            if node_id in representative_ids:
                weight += 0.25
            weighted_vectors.append(vector)
            weighted_scores.append(weight)

        centroid = _mean_vector(weighted_vectors, weighted_scores)
        relevance: dict[str, float] = {}
        per_node_debug: dict[str, dict[str, float]] = {}
        row_lookup = {row["node_id"]: row for row in candidate_rows}
        total_candidates = max(1, len(candidate_rows))

        for row in candidate_rows:
            node_id = row["node_id"]
            vector = vector_lookup.get(node_id, [])
            community_id = int(row.get("community_id", -1))
            community_centroid = community_centroids.get(community_id, centroid)
            semantic_salience = _cosine_similarity(vector, centroid)
            community_salience = _cosine_similarity(vector, community_centroid)
            structural_prior = _safe_float(row.get("importance_score", 0.0))
            support_bonus = min(0.12, _safe_float(row.get("support_count", 0.0)) * 0.025)
            multimodal_bonus = 0.08 if row.get("multimodal_anchor") else 0.0
            representative_bonus = 0.08 if node_id in representative_ids else 0.0
            community_size = len(community_groups.get(community_id, []))
            coverage_bonus = min(0.06, community_size / total_candidates)
            noise_penalty = self._generic_penalty(row)
            narrative_score = (
                0.34 * semantic_salience
                + 0.22 * community_salience
                + 0.22 * structural_prior
                + support_bonus
                + multimodal_bonus
                + representative_bonus
                + coverage_bonus
                - noise_penalty
            )
            relevance[node_id] = narrative_score
            per_node_debug[node_id] = {
                "semantic_salience": round(semantic_salience, 6),
                "community_salience": round(community_salience, 6),
                "structural_prior": round(structural_prior, 6),
                "support_bonus": round(support_bonus, 6),
                "multimodal_bonus": round(multimodal_bonus, 6),
                "representative_bonus": round(representative_bonus, 6),
                "coverage_bonus": round(coverage_bonus, 6),
                "noise_penalty": round(noise_penalty, 6),
                "narrative_score": round(narrative_score, 6),
            }

        seed_count = max(8, min(top_k, int(round(top_k * self.config.seed_ratio))))
        coverage_seeds = self._coverage_seed_ids(
            community_representatives,
            relevance,
            seed_budget=max(4, min(seed_count, max(1, top_k // 6))),
        )
        coverage_seed_set = set(coverage_seeds)
        remaining_candidates = [node_id for node_id in candidate_ids if node_id not in coverage_seed_set]
        mmr_seeds = self._select_seeds_mmr(
            remaining_candidates,
            relevance,
            vector_lookup,
            max(0, seed_count - len(coverage_seeds)),
        )
        seed_ids = coverage_seeds + [node_id for node_id in mmr_seeds if node_id not in coverage_seed_set]

        working_graph = self._build_working_graph(graph)
        edge_keys = [tuple(sorted((str(source), str(target)))) for source, target in working_graph.edges()]
        edge_vectors = await self._edge_embedding_lookup(working_graph, edge_keys)

        connector_budget = max(6, min(14, int(round(top_k * 0.20))))
        summary_budget = min(working_graph.number_of_nodes(), top_k + connector_budget)
        connected_graph = self._build_connected_summary_graph(
            graph=graph,
            seed_ids=seed_ids,
            relevance=relevance,
            centroid=centroid,
            top_k=summary_budget,
            edge_vectors=edge_vectors,
        )
        connected_graph = self._add_uncovered_story_seeds(
            summary_graph=connected_graph,
            working_graph=working_graph,
            seed_ids=seed_ids,
            relevance=relevance,
            top_k=summary_budget,
        )
        connected_graph = self._add_direct_selected_edges(connected_graph, working_graph, relevance)

        edge_allowlist = {
            tuple(sorted((str(source), str(target))))
            for source, target in connected_graph.edges()
        }
        selected_node_ids = [str(node_id) for node_id in connected_graph.nodes()]
        story_nodes = self._build_story_nodes(
            summary_graph=connected_graph,
            candidate_lookup=row_lookup,
            seed_ids=set(seed_ids),
            representative_ids=representative_ids,
            relevance=relevance,
            per_node_debug=per_node_debug,
        )

        debug_info = {
            "method": "global_narrative_steiner_summary",
            "global_pruning": True,
            "uses_qa_evidence_for_selection": False,
            "candidate_pool_size": len(candidate_rows),
            "seed_count": len(seed_ids),
            "coverage_seed_count": len(coverage_seeds),
            "connector_budget": connector_budget,
            "summary_budget": summary_budget,
            "selected_node_count": connected_graph.number_of_nodes(),
            "selected_edge_count": connected_graph.number_of_edges(),
            "core_seed_ids": seed_ids,
            "community_representatives": {
                str(community_id): node_id
                for community_id, node_id in community_representatives.items()
            },
            "story_order": [node_id for node_id, _ in sorted(story_nodes.items(), key=lambda item: item[1].get("story_order", 999999))],
            "node_scores": {
                node_id: per_node_debug[node_id]
                for node_id in sorted(seed_ids, key=lambda item: relevance.get(item, 0.0), reverse=True)[: min(12, len(seed_ids))]
                if node_id in per_node_debug
            },
        }
        return NarrativeSummaryResult(selected_node_ids, edge_allowlist, debug_info, story_nodes)

    def _group_candidates_by_community(self, candidate_rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        groups: dict[int, list[dict[str, Any]]] = {}
        fallback_id = -1
        for row in candidate_rows:
            community_id = int(row.get("community_id", -1))
            if community_id < 0:
                fallback_id -= 1
                community_id = fallback_id
            groups.setdefault(community_id, []).append(row)
        return groups

    def _community_centroids(
        self,
        community_groups: dict[int, list[dict[str, Any]]],
        vector_lookup: dict[str, list[float]],
    ) -> dict[int, list[float]]:
        centroids: dict[int, list[float]] = {}
        for community_id, rows in community_groups.items():
            vectors: list[list[float]] = []
            weights: list[float] = []
            for row in rows:
                vector = vector_lookup.get(row["node_id"], [])
                if not vector:
                    continue
                vectors.append(vector)
                weights.append(1.0 + _safe_float(row.get("importance_score", 0.0)))
            centroids[community_id] = _mean_vector(vectors, weights)
        return centroids

    def _community_representatives(self, community_groups: dict[int, list[dict[str, Any]]]) -> dict[int, str]:
        representatives: dict[int, str] = {}
        for community_id, rows in community_groups.items():
            if not rows:
                continue
            best = max(rows, key=lambda row: _safe_float(row.get("importance_score", 0.0)))
            representatives[community_id] = best["node_id"]
        return representatives

    def _coverage_seed_ids(
        self,
        community_representatives: dict[int, str],
        relevance: dict[str, float],
        seed_budget: int,
    ) -> list[str]:
        ranked = sorted(
            community_representatives.items(),
            key=lambda item: relevance.get(item[1], 0.0),
            reverse=True,
        )
        return [node_id for _, node_id in ranked[:seed_budget]]

    def _generic_penalty(self, row: dict[str, Any]) -> float:
        label_tokens = _tokenize(row.get("label", ""))
        description = _normalize_text(row.get("description", ""))
        if not label_tokens:
            return 0.08
        generic_terms = {
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
        if label_tokens.issubset(generic_terms) and len(label_tokens) <= 2:
            return 0.12
        if not description or description in {"n/a", "none", "unknown"} or len(description) < 24:
            return 0.07
        return 0.0

    def _add_uncovered_story_seeds(
        self,
        *,
        summary_graph: nx.Graph,
        working_graph: nx.Graph,
        seed_ids: list[str],
        relevance: dict[str, float],
        top_k: int,
    ) -> nx.Graph:
        augmented = summary_graph.copy()
        selected = {str(node_id) for node_id in augmented.nodes()}
        ranked_missing = [node_id for node_id in seed_ids if node_id not in selected and node_id in working_graph]
        ranked_missing.sort(key=lambda node_id: relevance.get(node_id, 0.0), reverse=True)
        for node_id in ranked_missing:
            if augmented.number_of_nodes() >= top_k:
                break
            augmented.add_node(node_id, **working_graph.nodes[node_id])
            selected.add(node_id)
        return augmented

    def _add_direct_selected_edges(
        self,
        summary_graph: nx.Graph,
        working_graph: nx.Graph,
        relevance: dict[str, float],
    ) -> nx.Graph:
        augmented = summary_graph.copy()
        selected = {str(node_id) for node_id in augmented.nodes()}
        candidates: list[tuple[float, str, str, dict[str, Any]]] = []
        for source, target in working_graph.edges():
            if str(source) not in selected or str(target) not in selected:
                continue
            if augmented.has_edge(source, target):
                continue
            attrs = working_graph.get_edge_data(source, target) or {}
            score = relevance.get(str(source), 0.0) + relevance.get(str(target), 0.0)
            score += 0.05 * _safe_float(attrs.get("weight", 1.0))
            candidates.append((score, str(source), str(target), attrs))
        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, source, target, attrs in candidates[: max(0, self.config.max_extra_edges)]:
            augmented.add_edge(source, target, **attrs)
        return augmented

    def _build_story_nodes(
        self,
        *,
        summary_graph: nx.Graph,
        candidate_lookup: dict[str, dict[str, Any]],
        seed_ids: set[str],
        representative_ids: set[str],
        relevance: dict[str, float],
        per_node_debug: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, Any]]:
        order = self._story_order(summary_graph, seed_ids, relevance)
        community_labels = self._community_labels(candidate_lookup, relevance)
        story_nodes: dict[str, dict[str, Any]] = {}
        for index, node_id in enumerate(order, start=1):
            row = candidate_lookup.get(node_id, {})
            community_id = int(row.get("community_id", -1)) if row else -1
            attrs = summary_graph.nodes[node_id]
            is_multimodal = bool(row.get("multimodal_anchor")) or _is_multimodal_anchor(attrs)
            if node_id not in seed_ids:
                role = "connector"
                reason = "connector node kept to preserve graph continuity between selected story anchors"
            elif is_multimodal:
                role = "visual_anchor"
                reason = "multimodal anchor selected as a presentable visual or structured evidence point"
            elif node_id in representative_ids:
                role = "chapter_anchor"
                reason = "community representative selected to cover a major topic cluster"
            else:
                role = "core_narrative_node"
                reason = "semantically central node selected by global MMR diversification"
            score = relevance.get(node_id, 0.0)
            story_nodes[node_id] = {
                "story_order": index,
                "story_role": role,
                "chapter_id": community_id,
                "chapter_label": community_labels.get(community_id, "Unclustered"),
                "narrative_score": round(score, 6),
                "why_selected": reason,
                "score_breakdown": per_node_debug.get(node_id, {}),
            }
        return story_nodes

    def _story_order(
        self,
        summary_graph: nx.Graph,
        seed_ids: set[str],
        relevance: dict[str, float],
    ) -> list[str]:
        if summary_graph.number_of_nodes() == 0:
            return []
        undirected = summary_graph.to_undirected() if summary_graph.is_directed() else summary_graph
        components = list(nx.connected_components(undirected))
        components.sort(
            key=lambda component: max((relevance.get(str(node_id), 0.0) for node_id in component), default=0.0),
            reverse=True,
        )
        ordered: list[str] = []
        seen: set[str] = set()
        for component in components:
            start = max(
                component,
                key=lambda node_id: (
                    str(node_id) in seed_ids,
                    relevance.get(str(node_id), 0.0),
                    str(node_id),
                ),
            )
            for node_id in nx.bfs_tree(undirected.subgraph(component), start).nodes():
                node_id_str = str(node_id)
                if node_id_str in seen:
                    continue
                ordered.append(node_id_str)
                seen.add(node_id_str)
        remaining = [str(node_id) for node_id in summary_graph.nodes() if str(node_id) not in seen]
        remaining.sort(key=lambda node_id: relevance.get(node_id, 0.0), reverse=True)
        return ordered + remaining

    def _community_labels(
        self,
        candidate_lookup: dict[str, dict[str, Any]],
        relevance: dict[str, float],
    ) -> dict[int, str]:
        by_community: dict[int, list[dict[str, Any]]] = {}
        for row in candidate_lookup.values():
            community_id = int(row.get("community_id", -1))
            by_community.setdefault(community_id, []).append(row)
        labels: dict[int, str] = {}
        for community_id, rows in by_community.items():
            best = max(rows, key=lambda row: relevance.get(row.get("node_id", ""), 0.0))
            labels[community_id] = str(best.get("label") or f"Community {community_id}")
        return labels
