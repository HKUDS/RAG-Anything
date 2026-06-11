"""
RRF Hybrid Search Engine — Three-channel parallel retrieval with RRF fusion.

Channels:
  1. BM25 keyword search (Okapi BM25 + jieba tokenizer)
  2. Vector semantic search (via LightRAG's HNSW index)
  3. Knowledge graph search (entity matching + neighbor traversal)

Fusion: RRF (Reciprocal Rank Fusion) — Σ 1/(k + rank_i)
"""

import os
import asyncio
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

from lightrag.utils import logger as lightrag_logger


# ═══════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════


@dataclass
class ScoredChunk:
    """A retrieved chunk with its RRF fusion score and source channels."""

    chunk_id: str
    content: str
    score: float
    sources: List[str] = field(default_factory=list)
    # Per-channel ranks for diagnostics
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    graph_rank: Optional[int] = None

    def __repr__(self):
        return (
            f"ScoredChunk(id={self.chunk_id[:16]}..., score={self.score:.4f}, "
            f"sources={self.sources})"
        )


# ═══════════════════════════════════════════════════════════
# BM25 Keyword Index Manager
# ═══════════════════════════════════════════════════════════


class BM25IndexManager:
    """
    Okapi BM25 inverted index with jieba tokenization.

    Env vars:
        BM25_K1: k1 parameter (default 1.5)
        BM25_B:  b parameter (default 0.75)
        BM25_TOP_K: candidates returned per query (default 50)
        BM25_TOKENIZER: tokenizer choice — "jieba" (default) or "nltk"
    """

    def __init__(self, tokenizer: Optional[Callable] = None):
        self._k1 = float(os.getenv("BM25_K1", "1.5"))
        self._b = float(os.getenv("BM25_B", "0.75"))
        self._top_k = int(os.getenv("BM25_TOP_K", "50"))
        self._tokenizer_name = os.getenv("BM25_TOKENIZER", "jieba")

        self._index = None
        self._chunks: List[Dict[str, Any]] = []  # [{chunk_id, content}, ...]
        self._tokenizer = tokenizer or self._create_tokenizer()
        self._lock = asyncio.Lock()  # guards index rebuilds

    # ------------------------------------------------------------------
    # Tokenizer
    # ------------------------------------------------------------------

    def _create_tokenizer(self) -> Callable[[str], List[str]]:
        """Create the configured tokenizer function."""
        if self._tokenizer_name == "nltk":
            try:
                import nltk

                nltk.download("punkt", quiet=True)
                return lambda text: nltk.word_tokenize(text.lower())
            except ImportError:
                lightrag_logger.warning(
                    "NLTK not installed for BM25 tokenizer; falling back to jieba"
                )

        # Default: jieba
        import jieba

        return lambda text: list(jieba.cut(text))

    # ------------------------------------------------------------------
    # Index Building
    # ------------------------------------------------------------------

    def build_index(self, chunks: List[Dict[str, Any]]):
        """Build BM25 index from a list of chunks (synchronous blocking call).

        Args:
            chunks: List of {'chunk_id': str, 'content': str}
        """
        from rank_bm25 import BM25Okapi

        self._chunks = list(chunks)
        if not self._chunks:
            self._index = None
            return

        corpus = [self._tokenizer(c["content"]) for c in self._chunks]
        self._index = BM25Okapi(
            corpus, k1=self._k1, b=self._b, epsilon=0.25
        )

    async def rebuild_index_async(self, chunks: List[Dict[str, Any]]):
        """Async-safe index rebuild: build in background, atomically swap."""
        import concurrent.futures

        loop = asyncio.get_running_loop()
        async with self._lock:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, self.build_index, list(chunks))

    async def update_index_incremental(self, new_chunks: List[Dict[str, Any]]):
        """Rebuild index with added chunks (full rebuild for correctness)."""
        # For BM25Okapi accuracy, we rebuild the entire index.
        # Future optimization: shard-based partial rebuild for large corpora.
        all_chunks = self._chunks + list(new_chunks)
        await self.rebuild_index_async(all_chunks)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, query: str, top_k: int | None = None
    ) -> List[ScoredChunk]:
        """Search BM25 index, returning scored results.

        Args:
            query: Search query string
            top_k: Max results (default: BM25_TOP_K env var)

        Returns:
            List of ScoredChunk with bm25 sources, ranked by BM25 score descending
        """
        top_k = top_k or self._top_k
        if self._index is None or not self._chunks:
            return []

        tokenized = self._tokenizer(query)
        if not tokenized:
            return []

        scores = self._index.get_scores(tokenized)
        # Get top_k indices sorted by score descending
        if len(scores) <= top_k:
            ranked_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )
        else:
            # Use argpartition for efficiency with large result sets
            import numpy as np

            ranked_indices = np.argsort(scores)[::-1][:top_k].tolist()

        results = []
        for rank, idx in enumerate(ranked_indices):
            if scores[idx] <= 0:
                continue
            chunk = self._chunks[idx]
            results.append(
                ScoredChunk(
                    chunk_id=chunk["chunk_id"],
                    content=chunk["content"],
                    score=float(scores[idx]),
                    sources=["bm25"],
                    bm25_rank=rank + 1,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def is_ready(self) -> bool:
        return self._index is not None


# ═══════════════════════════════════════════════════════════
# Knowledge Graph Retriever
# ═══════════════════════════════════════════════════════════


class GraphRetriever:
    """
    Knowledge graph retrieval channel using LightRAG's entity graph.

    Env vars:
        GRAPH_DEPTH: neighbor traversal depth (default 2)
        GRAPH_TOP_K: max candidates returned (default 30)
    """

    def __init__(self, lightrag_instance=None):
        self._lightrag = lightrag_instance
        self._depth = int(os.getenv("GRAPH_DEPTH", "2"))
        self._top_k = int(os.getenv("GRAPH_TOP_K", "30"))

    def set_lightrag(self, lightrag_instance):
        """Set or update the LightRAG reference."""
        self._lightrag = lightrag_instance

    # ------------------------------------------------------------------
    # Entity Matching
    # ------------------------------------------------------------------

    def _match_entities(self, query: str) -> List[Dict[str, Any]]:
        """Extract entity names from query text and match in LightRAG's graph.

        Returns:
            List of matched entity dicts: {name, entity_id, degree, ...}
        """
        if self._lightrag is None:
            return []

        try:
            # LightRAG stores entities in chunk_entity_relation_graph
            graph = getattr(self._lightrag, "chunk_entity_relation_graph", None)
            if graph is None:
                return []

            # Collect all entity names and match against query
            matched = []
            query_lower = query.lower()

            for node, data in graph.nodes(data=True):
                entity_name = data.get("entity_name", node)
                if not isinstance(entity_name, str):
                    continue
                # Simple substring match (fuzzy matching can be added later)
                if entity_name.lower() in query_lower or any(
                    token.lower() in entity_name.lower()
                    for token in query_lower.split()
                    if len(token) >= 2
                ):
                    matched.append(
                        {
                            "name": entity_name,
                            "node_id": node,
                            "degree": graph.degree(node),
                            "entity_type": data.get("entity_type", "unknown"),
                        }
                    )

            # Sort by degree (more connected entities first)
            matched.sort(key=lambda e: e["degree"], reverse=True)
            return matched

        except Exception as exc:
            lightrag_logger.warning(f"Graph entity matching failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Neighbor Traversal
    # ------------------------------------------------------------------

    def _traverse_neighbors(
        self, matched_entities: List[Dict[str, Any]], depth: int | None = None
    ) -> Dict[str, float]:
        """Traverse graph neighbors from matched entities, returning weighted chunk IDs.

        Args:
            matched_entities: Entities matched from the query
            depth: Traversal depth (default: self._depth)

        Returns:
            {chunk_id: weight} — weight decays with distance (1/(d+1))
        """
        depth = depth or self._depth
        graph = getattr(self._lightrag, "chunk_entity_relation_graph", None)
        if graph is None or not matched_entities:
            return {}

        chunk_scores: Dict[str, float] = {}

        for entity in matched_entities:
            node_id = entity["node_id"]
            # BFS traversal
            visited = {node_id}
            frontier = [node_id]
            for d in range(depth + 1):
                next_frontier = []
                weight = 1.0 / (d + 1)  # distance decay
                for node in frontier:
                    # Collect chunks from this entity node
                    node_data = graph.nodes.get(node, {})
                    entity_chunks = node_data.get("chunk_ids", [])
                    if isinstance(entity_chunks, list):
                        for cid in entity_chunks:
                            chunk_scores[cid] = max(
                                chunk_scores.get(cid, 0.0), weight
                            )
                    # Explore neighbors
                    for neighbor in graph.neighbors(node):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            next_frontier.append(neighbor)
                frontier = next_frontier
                if not frontier:
                    break

        return chunk_scores

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int | None = None) -> List[ScoredChunk]:
        """Execute full graph retrieval: match entities → traverse → rank chunks.

        Args:
            query: Search query
            top_k: Max results (default: GRAPH_TOP_K env var)

        Returns:
            List of ScoredChunk with graph sources
        """
        top_k = top_k or self._top_k
        if self._lightrag is None:
            return []

        matched = self._match_entities(query)
        if not matched:
            return []

        chunk_scores = self._traverse_neighbors(matched)

        if not chunk_scores:
            return []

        # Sort by weight descending and limit to top_k
        sorted_chunks = sorted(
            chunk_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]

        results = []
        for rank, (chunk_id, weight) in enumerate(sorted_chunks):
            # Try to get chunk content from LightRAG storage
            content = ""
            try:
                if hasattr(self._lightrag, "text_chunks"):
                    content = self._lightrag.text_chunks.get(chunk_id, "")
                if not content and hasattr(self._lightrag, "chunks"):
                    content = self._lightrag.chunks.get(chunk_id, "")
            except Exception:
                pass

            results.append(
                ScoredChunk(
                    chunk_id=str(chunk_id),
                    content=content if isinstance(content, str) else str(content),
                    score=weight,
                    sources=["graph"],
                    graph_rank=rank + 1,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Visualization Data
    # ------------------------------------------------------------------

    def get_subgraph(
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

        # Resolve entities
        if entity_ids:
            seed_nodes = set(entity_ids)
        elif query:
            matched = self._match_entities(query)
            seed_nodes = {e["node_id"] for e in matched}
        else:
            seed_nodes = set()

        if not seed_nodes:
            return {"nodes": [], "edges": []}

        # Collect subgraph: seed nodes + 1-hop neighbors
        sub_nodes = set(seed_nodes)
        for node in list(seed_nodes):
            for neighbor in graph.neighbors(node):
                sub_nodes.add(neighbor)

        nodes = []
        for node in sub_nodes:
            data = graph.nodes.get(node, {})
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
        for u, v, data in graph.edges(data=True):
            if u in sub_nodes and v in sub_nodes:
                edges.append(
                    {
                        "source": u,
                        "target": v,
                        "relation": data.get("relation", data.get("description", "")),
                    }
                )

        return {"nodes": nodes, "edges": edges}


# ═══════════════════════════════════════════════════════════
# Hybrid Search Engine (RRF Fusion)
# ═══════════════════════════════════════════════════════════


class HybridSearchEngine:
    """
    Three-channel parallel retrieval with RRF fusion.

    Channels:
      - BM25 keyword search (Okapi BM25)
      - Vector semantic search (LightRAG HNSW)
      - Knowledge graph search (entity + traversal)

    Env vars:
        RRF_K: RRF constant k (default 60)
        VECTOR_TOP_K: vector channel candidate count (default 100)
        BM25_TOP_K: BM25 channel candidate count (default 50) — read by BM25IndexManager
        GRAPH_TOP_K: graph channel candidate count (default 30) — read by GraphRetriever
        RRF_ENABLED_CHANNELS: comma-separated list, e.g. "bm25,vector,graph"
    """

    def __init__(
        self,
        lightrag_instance=None,
        bm25_manager: Optional[BM25IndexManager] = None,
        graph_retriever: Optional[GraphRetriever] = None,
    ):
        self._lightrag = lightrag_instance
        self._bm25 = bm25_manager or BM25IndexManager()
        self._graph = graph_retriever or GraphRetriever(lightrag_instance)

        self._rrf_k = int(os.getenv("RRF_K", "60"))
        self._vector_top_k = int(os.getenv("VECTOR_TOP_K", "100"))

        # Which channels to enable
        default_channels = "bm25,vector,graph"
        channels_str = os.getenv("RRF_ENABLED_CHANNELS", default_channels)
        self._enabled_channels = [
            c.strip() for c in channels_str.split(",") if c.strip()
        ]

        self._bm25_top_k = int(os.getenv("BM25_TOP_K", "50"))
        self._graph_top_k = int(os.getenv("GRAPH_TOP_K", "30"))

        self._channel_timeout = float(os.getenv("RRF_CHANNEL_TIMEOUT", "10.0"))

        self._logger = lightrag_logger

    def set_lightrag(self, lightrag_instance):
        """Set/update the LightRAG instance reference."""
        self._lightrag = lightrag_instance
        self._graph.set_lightrag(lightrag_instance)

    async def ensure_bm25_index(self):
        """Build BM25 index from existing LightRAG chunks if not already built.

        Called after initialization to ensure the BM25 index covers all
        existing documents in the knowledge base.
        """
        if self._bm25.is_ready:
            return

        if self._lightrag is None:
            self._logger.warning("No LightRAG instance, skipping BM25 index build")
            return

        try:
            import json
            from pathlib import Path

            # Read chunks from LightRAG's text_chunks KV store JSON
            chunk_file = Path(self._lightrag.working_dir) / "kv_store_text_chunks.json"
            if not chunk_file.exists():
                self._logger.info(f"No existing chunks file at {chunk_file}")
                return

            data = json.loads(chunk_file.read_text(encoding="utf-8"))
            if not data:
                return

            chunk_list = [
                {"chunk_id": cid, "content": c.get("content", "")}
                for cid, c in data.items()
            ]
            if chunk_list:
                await self._bm25.rebuild_index_async(chunk_list)
                self._logger.info(f"BM25 index built from {len(chunk_list)} existing chunks")
        except Exception as exc:
            self._logger.warning(f"Failed to build BM25 index from existing chunks: {exc}")

    # ------------------------------------------------------------------
    # Channel Searches
    # ------------------------------------------------------------------

    async def _bm25_search(self, query: str, top_k: int) -> List[ScoredChunk]:
        """BM25 channel (sync, run in executor)."""
        if "bm25" not in self._enabled_channels:
            return []
        loop = asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(
                pool, self._bm25.search, query, top_k
            )

    async def _vector_search(self, query: str, top_k: int) -> List[ScoredChunk]:
        """Vector semantic search via LightRAG's internal retrieval."""
        if "vector" not in self._enabled_channels:
            return []
        if self._lightrag is None:
            return []

        try:
            # Use LightRAG's query with only_need_context to get raw chunks
            from lightrag import QueryParam

            param = QueryParam(mode="local", only_need_context=True, top_k=top_k)
            result = await self._lightrag.aquery(query, param=param)

            if not result or not isinstance(result, str):
                return []

            # LightRAG returns context as a formatted string; extract chunk references
            chunks = self._parse_lightrag_context(result)
            return [
                ScoredChunk(
                    chunk_id=c.get("chunk_id", str(i)),
                    content=c.get("content", ""),
                    score=1.0,  # Will be replaced by RRF rank
                    sources=["vector"],
                    vector_rank=i + 1,
                )
                for i, c in enumerate(chunks[:top_k])
            ]
        except Exception as exc:
            self._logger.warning(f"Vector search failed: {exc}")
            return []

    async def _graph_search(self, query: str, top_k: int) -> List[ScoredChunk]:
        """Knowledge graph search (sync, run in executor)."""
        if "graph" not in self._enabled_channels:
            return []
        loop = asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(
                pool, self._graph.search, query, top_k
            )

    # ------------------------------------------------------------------
    # RRF Fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_fuse(
        channel_results: List[List[ScoredChunk]], k: int = 60
    ) -> List[ScoredChunk]:
        """RRF fusion: Σ 1/(k + rank_i) for each chunk across channels.

        Args:
            channel_results: Per-channel result lists (ordered by channel rank)
            k: RRF constant (default 60)

        Returns:
            Fused results sorted by RRF score descending, with dedup and source labels
        """
        # Aggregate: {chunk_id: {score, content, sources, ranks}}
        fused: Dict[str, Dict[str, Any]] = {}

        channel_names = ["bm25", "vector", "graph"]
        for ch_idx, results in enumerate(channel_results):
            for rank, chunk in enumerate(results):
                cid = chunk.chunk_id
                rrf_contrib = 1.0 / (k + rank + 1)

                if cid not in fused:
                    fused[cid] = {
                        "chunk_id": cid,
                        "content": chunk.content,
                        "score": 0.0,
                        "sources": [],
                        "bm25_rank": None,
                        "vector_rank": None,
                        "graph_rank": None,
                    }

                entry = fused[cid]
                entry["score"] += rrf_contrib
                ch_name = channel_names[ch_idx] if ch_idx < len(channel_names) else f"ch{ch_idx}"
                if ch_name not in entry["sources"]:
                    entry["sources"].append(ch_name)
                # Preserve best per-channel rank
                rank_key = f"{ch_name}_rank"
                current = entry.get(rank_key)
                if current is None or (rank + 1) < current:
                    entry[rank_key] = rank + 1

        # Build result list
        result_list = [
            ScoredChunk(
                chunk_id=v["chunk_id"],
                content=v["content"],
                score=v["score"],
                sources=v["sources"],
                bm25_rank=v.get("bm25_rank"),
                vector_rank=v.get("vector_rank"),
                graph_rank=v.get("graph_rank"),
            )
            for v in fused.values()
        ]

        result_list.sort(key=lambda c: c.score, reverse=True)
        return result_list

    # ------------------------------------------------------------------
    # Main Search Entry Point
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 100,
        channels: List[str] | None = None,
    ) -> List[ScoredChunk]:
        """Main RRF hybrid search: parallel channels → fuse → return.

        Args:
            query: Search query
            top_k: Final number of results after fusion
            channels: Override enabled channels (e.g., ["bm25", "vector"])

        Returns:
            Fused, deduplicated, RRF-scored results
        """
        if channels:
            self._enabled_channels = channels

        # Launch all enabled channels in parallel with per-channel timeout
        tasks = []
        task_labels = []

        if "bm25" in self._enabled_channels:
            tasks.append(
                asyncio.wait_for(
                    self._bm25_search(query, self._bm25_top_k),
                    timeout=self._channel_timeout,
                )
            )
            task_labels.append("bm25")

        if "vector" in self._enabled_channels:
            tasks.append(
                asyncio.wait_for(
                    self._vector_search(query, self._vector_top_k),
                    timeout=self._channel_timeout,
                )
            )
            task_labels.append("vector")

        if "graph" in self._enabled_channels:
            tasks.append(
                asyncio.wait_for(
                    self._graph_search(query, self._graph_top_k),
                    timeout=self._channel_timeout,
                )
            )
            task_labels.append("graph")

        if not tasks:
            return []

        # Run in parallel, catching per-channel failures
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        channel_results: List[List[ScoredChunk]] = []
        for label, result in zip(task_labels, gathered):
            if isinstance(result, Exception):
                self._logger.warning(
                    f"Channel '{label}' failed or timed out: {result}"
                )
                channel_results.append([])
            elif isinstance(result, list):
                channel_results.append(result)
            else:
                channel_results.append([])

        # Check if ALL channels failed
        if all(len(r) == 0 for r in channel_results):
            self._logger.error("All RRF channels failed — returning empty results")
            return []

        # RRF fusion
        fused = self._rrf_fuse(channel_results, k=self._rrf_k)
        return fused[:top_k]

    # ------------------------------------------------------------------
    # Context Parsing Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_lightrag_context(raw_context: str) -> List[Dict[str, Any]]:
        """Parse LightRAG's only_need_context output into structured chunk list.

        LightRAG returns context as chunks separated by double newlines, each
        prefixed with a chunk_id marker like ``[chunk_xxx]`` or ``{chunk_id}``.
        """
        if not raw_context:
            return []

        import re

        chunks = []
        # Split on common chunk separators
        parts = re.split(r"\n(?=\[|\{)", raw_context)
        if len(parts) <= 1:
            parts = raw_context.split("\n\n")

        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Try to extract chunk_id marker
            marker_match = re.match(r"[\[{]([^\]}]+)[\]}]", part)
            chunk_id = marker_match.group(1) if marker_match else ""
            content = part[marker_match.end():].strip() if marker_match else part
            if content:
                chunks.append({"chunk_id": chunk_id, "content": content[:500]})

        return chunks

    # ------------------------------------------------------------------
    # Index Management Delegates
    # ------------------------------------------------------------------

    async def build_bm25_index(self, chunks: List[Dict[str, Any]]):
        """Build/rebuild BM25 index from chunks."""
        await self._bm25.rebuild_index_async(chunks)

    async def update_bm25_index(self, new_chunks: List[Dict[str, Any]]):
        """Incrementally update BM25 index with new chunks."""
        await self._bm25.update_index_incremental(new_chunks)

    @property
    def bm25_ready(self) -> bool:
        return self._bm25.is_ready

    # ------------------------------------------------------------------
    # Graph Visualization Delegate
    # ------------------------------------------------------------------

    def get_subgraph(
        self, entity_ids: List[str] | None = None, query: str | None = None
    ) -> Dict[str, Any]:
        """Get subgraph data for visualization."""
        return self._graph.get_subgraph(entity_ids=entity_ids, query=query)
