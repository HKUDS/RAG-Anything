"""
Standalone GraphRAG module — knowledge graph retrieval with entity-path tracing.

Provides :class:`GraphRetriever` for entity matching, neighbor traversal, and
subgraph visualization, and :class:`GraphRAGConfig` for centralized
configuration.  The retriever can be used directly (``mode="graph"`` query) or
as the graph channel inside :class:`HybridSearchEngine` for RRF fusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import functools

import jieba
from lightrag.utils import logger as lightrag_logger
from lightrag.utils import get_env_value

# ScoredChunk is imported lazily inside methods to break the circular import
# between graph_rag ↔ hybrid_search (graph_rag needs ScoredChunk, hybrid_search
# needs GraphRetriever).


@functools.lru_cache(maxsize=8192)
def _tokenize_entity(name: str) -> frozenset[str]:
    """Tokenize a single entity name with jieba (cached across queries)."""
    return frozenset(t for t in jieba.lcut(name) if len(t) >= 1)


def _normalize_node_id(value: str) -> str:
    """Normalize a storage node/edge id (strips enclosing JSON quotes)."""
    normalized = (value or "").strip()
    if len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"'):
        return normalized[1:-1]
    return normalized


# ═══════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════


@dataclass
class GraphRAGConfig:
    """Centralized configuration for graph-based retrieval.

    All fields can be overridden via environment variables.  Uses
    ``default_factory`` so env vars are read at instance creation time
    (not class definition time), allowing tests and runtime overrides.
    """

    graph_depth: int = field(
        default_factory=lambda: get_env_value("GRAPH_DEPTH", 2, int)
    )
    """Neighbor traversal depth (default 2). Controls 1-N hop BFS expansion."""

    graph_top_k: int = field(
        default_factory=lambda: get_env_value("GRAPH_TOP_K", 30, int)
    )
    """Max candidates returned by graph-only queries."""

    graph_min_score: float = field(
        default_factory=lambda: get_env_value("GRAPH_MIN_SCORE", 0.0, float)
    )
    """Minimum distance-decay weight for a chunk to be included (0 = no filter)."""

    graph_max_seed_entities: int = field(
        default_factory=lambda: get_env_value("GRAPH_MAX_SEED_ENTITIES", 20, int)
    )
    """Max entity seeds fed into neighbor traversal (bounds BFS cost)."""


# ═══════════════════════════════════════════════════════════
# Graph Retriever
# ═══════════════════════════════════════════════════════════


class GraphRetriever:
    """Knowledge graph retrieval using LightRAG's entity graph.

    Entity matching → BFS neighbor traversal → chunk ranking with
    distance-decay weighting.  Also provides subgraph data for
    D3 force-directed visualization.

    Env vars:
        GRAPH_DEPTH: neighbor traversal depth (default 2)
        GRAPH_TOP_K: max candidates returned (default 30)
        GRAPH_MIN_SCORE: minimum weight threshold (default 0.0)
    """

    def __init__(self, lightrag_instance=None, config: GraphRAGConfig | None = None):
        self._lightrag = lightrag_instance
        cfg = config or GraphRAGConfig()
        self._depth: int = cfg.graph_depth
        self._top_k: int = cfg.graph_top_k
        self._min_score: float = cfg.graph_min_score
        self._max_seed_entities: int = cfg.graph_max_seed_entities

    @property
    def config_snapshot(self) -> Dict[str, Any]:
        """Return a snapshot of current configuration for API exposure."""
        return {
            "graph_depth": self._depth,
            "graph_top_k": self._top_k,
            "graph_min_score": self._min_score,
            "graph_max_seed_entities": self._max_seed_entities,
        }

    def set_lightrag(self, lightrag_instance):
        """Set or update the LightRAG reference."""
        self._lightrag = lightrag_instance

    # ------------------------------------------------------------------
    # Query-Scoped Snapshot
    # ------------------------------------------------------------------

    async def _load_snapshot(
        self,
    ) -> Tuple[Dict[str, Any], Dict[str, List[Tuple[str, Dict[str, Any]]]], Dict[str, int]] | None:
        """Load graph nodes/edges once and build local lookup structures.

        Returns ``(node_by_id, adjacency, degree_map)`` where ``adjacency``
        maps a node id to ``(neighbor_id, edge_data)`` pairs for both edge
        orientations.  Accessing the graph storage through a single snapshot
        avoids thousands of per-node/per-edge storage calls (each of which
        acquires the storage lock and re-checks the reload flag).
        """
        graph = getattr(self._lightrag, "chunk_entity_relation_graph", None)
        if graph is None:
            return None

        try:
            all_nodes = await graph.get_all_nodes() or []
        except Exception as exc:
            lightrag_logger.warning(f"Graph snapshot node load failed: {exc}")
            return None
        try:
            all_edges = await graph.get_all_edges() or []
        except Exception as exc:
            lightrag_logger.warning(f"Graph snapshot edge load failed: {exc}")
            all_edges = []

        node_by_id: Dict[str, Any] = {}
        for node_data in all_nodes:
            node_id = _normalize_node_id(
                node_data.get("entity_id")
                or node_data.get("entity_name")
                or node_data.get("id")
                or ""
            )
            if node_id:
                node_by_id[node_id] = node_data

        adjacency: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        degree_map: Dict[str, int] = {}
        for edge in all_edges:
            src = _normalize_node_id(edge.get("source") or edge.get("src_id") or "")
            tgt = _normalize_node_id(edge.get("target") or edge.get("tgt_id") or "")
            if not src or not tgt:
                continue
            degree_map[src] = degree_map.get(src, 0) + 1
            degree_map[tgt] = degree_map.get(tgt, 0) + 1
            adjacency.setdefault(src, []).append((tgt, edge))
            adjacency.setdefault(tgt, []).append((src, edge))

        return node_by_id, adjacency, degree_map

    def _cap_seed_entities(
        self, matched: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Bound the number of traversal seeds to keep BFS cost predictable."""
        if self._max_seed_entities > 0 and len(matched) > self._max_seed_entities:
            lightrag_logger.info(
                "Graph seed entities capped to %d (matched %d)",
                self._max_seed_entities,
                len(matched),
            )
            return matched[: self._max_seed_entities]
        return matched

    # ------------------------------------------------------------------
    # Entity Matching
    # ------------------------------------------------------------------

    async def _match_entities(
        self, query: str, snapshot: Tuple | None = None
    ) -> List[Dict[str, Any]]:
        """Extract entity names from query text and match in LightRAG's graph.

        Uses jieba token-overlap scoring for weighted matching:
        - Entities with more overlapping tokens with the query score higher.
        - Pure substring match (no token overlap) gets a base score of 0.5 as fallback.
        - Results are sorted by token-overlap score desc, then graph degree desc.

        Args:
            query: The search query text
            snapshot: Optional preloaded ``_load_snapshot()`` result; loaded
                on demand when omitted.

        Returns:
            List of matched entity dicts: {name, node_id, degree, entity_type, score}
        """
        if self._lightrag is None:
            return []

        try:
            if snapshot is None:
                snapshot = await self._load_snapshot()
                if snapshot is None:
                    return []
            node_by_id, _adjacency, degree_map = snapshot

            # Tokenize query with jieba for overlap scoring
            query_lower = query.lower()
            query_tokens = set(t for t in jieba.lcut(query) if len(t) >= 1)

            scored = []
            for node_id, node_data in node_by_id.items():
                entity_name = node_data.get("entity_name", node_id)
                if not isinstance(entity_name, str) or not entity_name:
                    continue

                entity_lower = entity_name.lower()

                # Token-overlap score (jieba, cached per entity name)
                entity_tokens = _tokenize_entity(entity_name)
                overlap = len(query_tokens & entity_tokens)

                # Substring match as fallback
                substring_match = (
                    entity_lower in query_lower
                    or any(
                        token.lower() in entity_lower
                        for token in query_lower.split()
                        if len(token) >= 2
                    )
                )

                if overlap > 0:
                    score = float(overlap)
                elif substring_match:
                    score = 0.5  # fallback: substring but no token overlap
                else:
                    continue

                degree = degree_map.get(node_id, 0)
                scored.append(
                    {
                        "name": entity_name,
                        "node_id": node_id,
                        "degree": degree,
                        "entity_type": node_data.get("entity_type", "unknown"),
                        "score": score,
                    }
                )

            # Sort: token-overlap score desc, then degree desc
            scored.sort(key=lambda e: (e["score"], e["degree"]), reverse=True)
            return scored

        except Exception as exc:
            lightrag_logger.warning(f"Graph entity matching failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Neighbor Traversal
    # ------------------------------------------------------------------

    async def _traverse_neighbors(
        self,
        matched_entities: List[Dict[str, Any]],
        depth: int | None = None,
        snapshot: Tuple | None = None,
    ) -> Tuple[Dict[str, float], Dict[str, List[Tuple[str, str, int]]]]:
        """BFS traversal returning chunk scores and entity→chunk paths.

        Args:
            matched_entities: Entities matched from the query
            depth: Traversal depth (default: self._depth)
            snapshot: Optional preloaded ``_load_snapshot()`` result; loaded
                on demand when omitted.

        Returns:
            (chunk_scores, entity_paths) where:
              chunk_scores: {chunk_id: weight}
              entity_paths: {chunk_id: [(entity_name, relation, hop_depth), ...]}
        """
        depth = self._depth if depth is None else depth
        if not matched_entities:
            return {}, {}
        if snapshot is None:
            snapshot = await self._load_snapshot()
            if snapshot is None:
                return {}, {}
        node_by_id, adjacency, _degree_map = snapshot

        chunk_scores: Dict[str, float] = {}
        entity_paths: Dict[str, List[Tuple[str, str, int]]] = {}

        for entity in matched_entities:
            node_id = entity["node_id"]
            entity_name = entity["name"]
            visited = {node_id}
            frontier = [node_id]
            # Track path: {neighbor_id: (entity_name, edge_relation, hop_depth)}
            path_tracker: Dict[str, Tuple[str, str, int]] = {}

            for d in range(depth + 1):
                next_frontier = []
                weight = 1.0 / (d + 1)
                for node in frontier:
                    node_data = node_by_id.get(node) or {}
                    entity_chunks = node_data.get("chunk_ids", [])
                    if isinstance(entity_chunks, list):
                        for cid in entity_chunks:
                            chunk_scores[cid] = max(
                                chunk_scores.get(cid, 0.0), weight
                            )
                            # Record path: which entity → via what relation → at what depth
                            if cid not in entity_paths:
                                entity_paths[cid] = []
                            path_info = path_tracker.get(node)
                            if path_info:
                                entity_paths[cid].append(
                                    (entity_name, path_info[1], d)
                                )
                            else:
                                # Direct entity node
                                entity_paths[cid].append(
                                    (entity_name, "direct", 0)
                                )

                    for neighbor, edge_data in adjacency.get(node, []):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            next_frontier.append(neighbor)
                            rel = edge_data.get(
                                "relation",
                                edge_data.get("description", "related_to"),
                            )
                            path_tracker[neighbor] = (entity_name, rel, d + 1)

                frontier = next_frontier
                if not frontier:
                    break

        # Filter by minimum score
        if self._min_score > 0:
            chunk_scores = {
                cid: s for cid, s in chunk_scores.items() if s >= self._min_score
            }

        return chunk_scores, entity_paths

    # ------------------------------------------------------------------
    # Search (graph-only query)
    # ------------------------------------------------------------------

    async def _fetch_chunk_contents(
        self, chunk_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Batch-fetch chunk metadata with per-id fallback for missing rows."""
        contents: Dict[str, Dict[str, Any]] = {}
        if not chunk_ids or not hasattr(self._lightrag, "text_chunks"):
            return contents
        try:
            raw = await self._lightrag.text_chunks.get_by_ids(chunk_ids)
            for record in raw or []:
                if not record:
                    continue
                record_id = record.get("id") or record.get("__id__")
                if record_id:
                    contents[record_id] = record
        except Exception as exc:
            lightrag_logger.warning(f"Graph chunk batch fetch failed: {exc}")
        missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in contents]
        for chunk_id in missing:
            try:
                record = await self._lightrag.text_chunks.get_by_id(chunk_id)
                if record:
                    contents[chunk_id] = record
            except Exception:
                pass
        return contents

    async def search(
        self, query: str, top_k: int | None = None, depth: int | None = None
    ) -> List[Any]:
        """Execute full graph retrieval: match entities → traverse → rank chunks.

        Args:
            query: Search query
            top_k: Max results (default: GRAPH_TOP_K env var)
            depth: Per-request neighbor traversal depth (default: configured depth)

        Returns:
            List of ScoredChunk with graph sources
        """
        from raganything.hybrid_search import ScoredChunk  # lazy — circular import

        top_k = top_k or self._top_k
        if self._lightrag is None:
            return []

        snapshot = await self._load_snapshot()
        if snapshot is None:
            return []

        matched = await self._match_entities(query, snapshot=snapshot)
        if not matched:
            return []

        seeds = self._cap_seed_entities(matched)
        chunk_scores, entity_paths = await self._traverse_neighbors(
            seeds, depth, snapshot=snapshot
        )

        if not chunk_scores:
            return []

        sorted_chunks = sorted(
            chunk_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]

        chunk_contents = await self._fetch_chunk_contents(
            [chunk_id for chunk_id, _weight in sorted_chunks]
        )

        results = []
        for rank, (chunk_id, weight) in enumerate(sorted_chunks):
            chunk_data = chunk_contents.get(chunk_id, {})
            content = chunk_data.get("content", "")
            doc_name = chunk_data.get("document_name")
            file_path = chunk_data.get("file_path")

            # Extract source entity names for this chunk
            chunk_entities = []
            if chunk_id in entity_paths:
                seen = set()
                for entity_name, _relation, _depth in entity_paths[chunk_id]:
                    if entity_name not in seen:
                        chunk_entities.append(entity_name)
                        seen.add(entity_name)

            results.append(
                ScoredChunk(
                    chunk_id=str(chunk_id),
                    content=content if isinstance(content, str) else str(content),
                    score=weight,
                    sources=["graph"],
                    graph_rank=rank + 1,
                    graph_entities=chunk_entities,
                    document_name=doc_name,
                    file_path=file_path,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Search with entity paths (for graph-only query mode)
    # ------------------------------------------------------------------

    async def search_with_paths(
        self, query: str, top_k: int | None = None
    ) -> Dict[str, Any]:
        """Graph retrieval with entity-path tracing for explainable results.

        Returns:
            {
                "matched_entities": [...],
                "results": [
                    {"chunk": ScoredChunk, "paths": [(entity, relation, depth), ...]},
                    ...
                ],
                "graph_stats": {"total_entities": N, "matched_count": M, ...}
            }
        """
        from raganything.hybrid_search import ScoredChunk  # lazy — circular import

        top_k = top_k or self._top_k
        empty_result = {
            "matched_entities": [],
            "results": [],
            "graph_stats": {"total_entities": 0, "matched_count": 0, "traversal_depth": self._depth},
        }

        if self._lightrag is None:
            return empty_result

        snapshot = await self._load_snapshot()
        if snapshot is None:
            return empty_result
        node_by_id, _adjacency, _degree_map = snapshot

        matched = await self._match_entities(query, snapshot=snapshot)
        total_entities = len(node_by_id)
        if not matched:
            empty_result["graph_stats"]["total_entities"] = total_entities
            return empty_result

        seeds = self._cap_seed_entities(matched)
        chunk_scores, entity_paths = await self._traverse_neighbors(
            seeds, snapshot=snapshot
        )

        if not chunk_scores:
            return {
                "matched_entities": [
                    {"name": e["name"], "type": e["entity_type"], "degree": e["degree"]}
                    for e in matched
                ],
                "results": [],
                "graph_stats": {
                    "total_entities": total_entities,
                    "matched_count": len(matched),
                    "traversal_depth": self._depth,
                    "note": "No chunks reachable from matched entities",
                },
            }

        sorted_chunks = sorted(
            chunk_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]

        chunk_contents = await self._fetch_chunk_contents(
            [chunk_id for chunk_id, _weight in sorted_chunks]
        )

        results = []
        for rank, (chunk_id, weight) in enumerate(sorted_chunks):
            chunk_data = chunk_contents.get(chunk_id, {})
            content = chunk_data.get("content", "")
            doc_name = chunk_data.get("document_name")
            file_path = chunk_data.get("file_path")

            paths = entity_paths.get(chunk_id, [])
            # Deduplicate paths: keep unique (entity, relation) per chunk
            seen = set()
            unique_paths = []
            for p in paths:
                key = (p[0], p[1])
                if key not in seen:
                    seen.add(key)
                    unique_paths.append(p)

            # Extract unique entity names for this chunk
            chunk_entity_names = []
            seen_entities = set()
            for p in unique_paths:
                if p[0] not in seen_entities:
                    chunk_entity_names.append(p[0])
                    seen_entities.add(p[0])

            results.append(
                {
                    "chunk": ScoredChunk(
                        chunk_id=str(chunk_id),
                        content=content if isinstance(content, str) else str(content),
                        score=weight,
                        sources=["graph"],
                        graph_rank=rank + 1,
                        graph_entities=chunk_entity_names,
                        document_name=doc_name,
                        file_path=file_path,
                    ),
                    "paths": [
                        {"entity": p[0], "relation": p[1], "depth": p[2]}
                        for p in unique_paths
                    ],
                }
            )

        return {
            "matched_entities": [
                {"name": e["name"], "type": e["entity_type"], "degree": e["degree"]}
                for e in matched
            ],
            "results": results,
            "graph_stats": {
                "total_entities": total_entities,
                "matched_count": len(matched),
                "traversal_depth": self._depth,
            },
        }

    # ------------------------------------------------------------------
    # Visualization Data
    # ------------------------------------------------------------------

    async def get_subgraph(
        self, entity_ids: List[str] | None = None, query: str | None = None
    ) -> Dict[str, Any]:
        """Return subgraph data for D3 force-directed visualization.

        Args:
            entity_ids: Specific entity node IDs to include
            query: If provided, auto-match entities from query text

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        graph = getattr(self._lightrag, "chunk_entity_relation_graph", None)
        if graph is None:
            return {"nodes": [], "edges": []}

        if entity_ids:
            seed_nodes = set(entity_ids)
        elif query:
            matched = await self._match_entities(query)
            seed_nodes = {e["node_id"] for e in matched}
        else:
            seed_nodes = set()

        if not seed_nodes:
            return {"nodes": [], "edges": []}

        sub_nodes = set(seed_nodes)
        for node in list(seed_nodes):
            edges_list = await graph.get_node_edges(node)
            if edges_list:
                for src, tgt in edges_list:
                    neighbor = tgt if src == node else src
                    sub_nodes.add(neighbor)

        nodes = []
        for node in sub_nodes:
            data = await graph.get_node(node) or {}
            nodes.append(
                {
                    "id": node,
                    "name": data.get("entity_name", node),
                    "type": data.get("entity_type", "unknown"),
                    "chunk_count": len(data.get("chunk_ids", [])),
                    "is_seed": node in seed_nodes,
                }
            )

        edges = []
        all_edges = await graph.get_all_edges()
        if all_edges:
            for edge_data in all_edges:
                u = edge_data.get("src_id", edge_data.get("source", ""))
                v = edge_data.get("tgt_id", edge_data.get("target", ""))
                if u in sub_nodes and v in sub_nodes:
                    edges.append(
                        {
                            "source": u,
                            "target": v,
                            "relation": edge_data.get(
                                "relation",
                                edge_data.get("description", ""),
                            ),
                        }
                    )

        return {"nodes": nodes, "edges": edges}
