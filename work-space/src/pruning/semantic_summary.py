from __future__ import annotations

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

            missing_texts = [texts[idx] for idx in missing_indices]
            response = openai_embed.func(
                missing_texts,
                model=self.config.model,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
            if inspect.isawaitable(response):
                response = await response
            vectors = [list(map(float, vector)) for vector in response]
            for idx, vector in zip(missing_indices, vectors):
                cached[idx] = vector
                self.cache.put(self.config.model, texts[idx], vector)
            self.cache.save()
        return [vec or [] for vec in cached]


class NodeTextBuilder:
    @staticmethod
    def build(attrs: dict[str, Any], node_id: str) -> str:
        label = str(attrs.get("entity_id", node_id)).strip()
        entity_type = str(attrs.get("entity_type", "")).strip()
        description = str(attrs.get("description", "")).strip()
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
        keywords = str(attrs.get("keywords", "")).strip()
        description = str(attrs.get("description", "")).strip()
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
