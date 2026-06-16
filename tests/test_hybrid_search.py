"""
Tests for RRF Hybrid Search Engine.

Covers: BM25IndexManager, GraphRetriever, HybridSearchEngine, RRF fusion.
"""

import os
import pytest
import asyncio
from dataclasses import dataclass

from raganything.hybrid_search import (
    ScoredChunk,
    BM25IndexManager,
    GraphRetriever,
    HybridSearchEngine,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def sample_chunks():
    """Standard test chunks in Chinese and English."""
    return [
        {"chunk_id": "c1", "content": "年假政策规定员工每年享有5天带薪年假"},
        {"chunk_id": "c2", "content": "工龄超过10年的员工年假天数增加至10天"},
        {"chunk_id": "c3", "content": "病假需要提供医院开具的证明文件"},
        {"chunk_id": "c4", "content": "Machine learning models require large amounts of training data"},
        {"chunk_id": "c5", "content": "Deep learning is a subset of machine learning using neural networks"},
        {"chunk_id": "c6", "content": "年假申请需要提前一周向直属领导提交"},
        {"chunk_id": "c7", "content": "Natural language processing combines linguistics and AI"},
        {"chunk_id": "c8", "content": "年终绩效考核结果影响第二年薪资调整"},
        {"chunk_id": "c9", "content": "Transfer learning allows models trained on one task to be reused"},
        {"chunk_id": "c10", "content": "员工手册包含公司各项规章制度和政策说明"},
    ]


@pytest.fixture
def bm25_manager(sample_chunks):
    """Pre-built BM25IndexManager with sample chunks."""
    mgr = BM25IndexManager()
    mgr.build_index(sample_chunks)
    return mgr


# ═══════════════════════════════════════════════════════════
# ScoredChunk Tests
# ═══════════════════════════════════════════════════════════


class TestScoredChunk:
    def test_creation_defaults(self):
        chunk = ScoredChunk(chunk_id="abc", content="test", score=0.5)
        assert chunk.chunk_id == "abc"
        assert chunk.content == "test"
        assert chunk.score == 0.5
        assert chunk.sources == []
        assert chunk.bm25_rank is None

    def test_creation_with_sources(self):
        chunk = ScoredChunk(
            chunk_id="xyz", content="hello", score=0.8, sources=["bm25"],
            bm25_rank=3, vector_rank=None, graph_rank=5,
        )
        assert chunk.sources == ["bm25"]
        assert chunk.bm25_rank == 3
        assert chunk.graph_rank == 5

    def test_repr(self):
        chunk = ScoredChunk(chunk_id="test_id_123456789", content="x", score=0.1234)
        repr_str = repr(chunk)
        assert "test_id_12345678" in repr_str
        assert "0.1234" in repr_str


# ═══════════════════════════════════════════════════════════
# BM25IndexManager Tests
# ═══════════════════════════════════════════════════════════


class TestBM25IndexManager:
    def test_initial_state(self):
        mgr = BM25IndexManager()
        assert not mgr.is_ready
        assert mgr.chunk_count == 0

    def test_build_index(self, sample_chunks):
        mgr = BM25IndexManager()
        mgr.build_index(sample_chunks)
        assert mgr.is_ready
        assert mgr.chunk_count == len(sample_chunks)

    def test_search_returns_results(self, bm25_manager):
        results = bm25_manager.search("年假政策")
        assert len(results) > 0
        # Top result should be about 年假
        assert any("年假" in r.content for r in results[:3])

    def test_search_chinese_tokenization(self, bm25_manager):
        """jieba should segment Chinese text correctly."""
        results = bm25_manager.search("员工年假天数")
        assert len(results) > 0
        # Results should have "bm25" in sources
        assert all("bm25" in r.sources for r in results)

    def test_search_english(self, bm25_manager):
        results = bm25_manager.search("machine learning")
        assert len(results) > 0
        assert any("machine learning" in r.content.lower() for r in results)

    def test_search_no_match(self, bm25_manager):
        # BM25 returns top_k results even for non-matching queries, but all
        # with score 0.0 — verify no chunk received a positive match score
        results = bm25_manager.search("zzzxnonexistentzzzx")
        assert all(r.score == 0.0 for r in results)

    def test_search_top_k_limit(self, bm25_manager):
        results = bm25_manager.search("年假", top_k=2)
        assert len(results) <= 2

    def test_search_empty_query(self, bm25_manager):
        results = bm25_manager.search("")
        assert results == []

    def test_build_empty_index(self):
        mgr = BM25IndexManager()
        mgr.build_index([])
        assert not mgr.is_ready
        results = mgr.search("test")
        assert results == []

    def test_rank_ordering(self, bm25_manager):
        """Higher BM25 scores should appear first."""
        results = bm25_manager.search("年假")
        scores = [r.score for r in results]
        if len(scores) >= 2:
            assert scores[0] >= scores[1]

    def test_bm25_rank_preserved(self, bm25_manager):
        """Each result should have its BM25 rank recorded."""
        results = bm25_manager.search("年假政策", top_k=5)
        for i, r in enumerate(results):
            assert r.bm25_rank == i + 1

    def test_jieba_tokenizer(self):
        """Test that jieba is the default tokenizer."""
        mgr = BM25IndexManager()
        tokens = mgr._tokenizer("员工年假申请流程")
        assert len(tokens) > 1  # Should segment into multiple tokens
        assert "年假" in tokens or "员工" in tokens


# ═══════════════════════════════════════════════════════════
# RRF Fusion Algorithm Tests
# ═══════════════════════════════════════════════════════════


class TestRRFFusion:
    def make_chunk(self, chunk_id, content, channel, rank):
        """Helper to create a ScoredChunk with channel rank."""
        sources = [channel]
        bm25_rank = rank + 1 if channel == "bm25" else None
        vector_rank = rank + 1 if channel == "vector" else None
        graph_rank = rank + 1 if channel == "graph" else None
        return ScoredChunk(
            chunk_id=chunk_id, content=content, score=1.0,
            sources=sources,
            bm25_rank=bm25_rank, vector_rank=vector_rank, graph_rank=graph_rank,
        )

    def test_rrf_formula_correctness(self):
        """Test RRF = Σ 1/(k + rank) with k=60.

        _rrf_fuse uses the list position (0-based) as rank, so rank = position + 1.
        A chunk at index 0 in two channels gets: 1/(60+1) + 1/(60+1) = 2/61
        """
        # chunk-A in both BM25 (pos 0) and vector (pos 0)
        bm25_results = [self.make_chunk("A", "content A", "bm25", 0)]
        vector_results = [self.make_chunk("A", "content A", "vector", 0)]
        graph_results = []

        fused = HybridSearchEngine._rrf_fuse(
            [bm25_results, vector_results, graph_results], k=60
        )

        # RRF_score: both at list position 0 → rank=1 → 1/61 + 1/61 = 2/61
        expected = 2.0 / 61
        assert len(fused) == 1
        assert fused[0].chunk_id == "A"
        assert abs(fused[0].score - expected) < 0.0001
        assert set(fused[0].sources) == {"bm25", "vector"}

    def test_rrf_cross_channel_boost(self):
        """A chunk appearing in multiple channels should rank higher."""
        # chunk-A: BM25 rank=5, vector rank=5 → moderate scores
        bm25 = [self.make_chunk("A", "multi", "bm25", 4)]
        vector = [self.make_chunk("A", "multi", "vector", 4)]
        graph = []

        # chunk-B: BM25 rank=1 → high score in one channel only
        bm25.append(self.make_chunk("B", "bm25-only", "bm25", 0))

        fused = HybridSearchEngine._rrf_fuse(
            [bm25, vector, graph], k=60
        )

        # chunk-A: 2 channels → should have higher RRF score
        # RRF(A) = 1/65 + 1/65
        # RRF(B) = 1/61
        score_a = next(c.score for c in fused if c.chunk_id == "A")
        score_b = next(c.score for c in fused if c.chunk_id == "B")
        assert score_a > score_b, (
            f"Cross-channel chunk should outrank single-channel: "
            f"A={score_a:.4f}, B={score_b:.4f}"
        )

    def test_rrf_dedup_by_chunk_id(self):
        """Same chunk_id across channels should be deduplicated."""
        bm25 = [self.make_chunk("DUP", "dup content", "bm25", 0)]
        vector = [self.make_chunk("DUP", "dup content", "vector", 1)]
        graph = [self.make_chunk("DUP", "dup content", "graph", 2)]

        fused = HybridSearchEngine._rrf_fuse(
            [bm25, vector, graph], k=60
        )
        assert len(fused) == 1
        assert fused[0].chunk_id == "DUP"
        assert sorted(fused[0].sources) == ["bm25", "graph", "vector"]

    def test_rrf_k_parameter_effect(self):
        """Smaller k increases rank differentiation."""
        bm25 = [self.make_chunk("A", "a", "bm25", 0), self.make_chunk("B", "b", "bm25", 4)]
        vector = []
        graph = []

        small_k = HybridSearchEngine._rrf_fuse([bm25, vector, graph], k=10)
        large_k = HybridSearchEngine._rrf_fuse([bm25, vector, graph], k=100)

        # With smaller k, the rank-1 chunk should have a larger relative advantage
        ratio_small = small_k[0].score / small_k[1].score if len(small_k) >= 2 else float("inf")
        ratio_large = large_k[0].score / large_k[1].score if len(large_k) >= 2 else float("inf")
        assert ratio_small > ratio_large, "Smaller k should amplify rank differences"

    def test_rrf_empty_channels(self):
        """Empty channel results should not affect fusion."""
        fused = HybridSearchEngine._rrf_fuse([[], [], []], k=60)
        assert fused == []

    def test_rrf_sources_merged(self):
        """Sources should reflect all channels a chunk appeared in."""
        bm25 = [self.make_chunk("X", "x", "bm25", 0)]
        vector = [self.make_chunk("X", "x", "vector", 0)]
        graph = []

        fused = HybridSearchEngine._rrf_fuse([bm25, vector, graph], k=60)
        assert set(fused[0].sources) == {"bm25", "vector"}


# ═══════════════════════════════════════════════════════════
# GraphRetriever Tests
# ═══════════════════════════════════════════════════════════


class TestGraphRetriever:
    @pytest.mark.asyncio
    async def test_no_lightrag_returns_empty(self):
        retriever = GraphRetriever(lightrag_instance=None)
        results = await retriever.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_no_lightrag_entity_match_returns_empty(self):
        retriever = GraphRetriever(lightrag_instance=None)
        entities = await retriever._match_entities("test")
        assert entities == []

    @pytest.mark.asyncio
    async def test_no_lightrag_subgraph_returns_empty(self):
        retriever = GraphRetriever(lightrag_instance=None)
        subgraph = await retriever.get_subgraph(query="test")
        assert subgraph == {"nodes": [], "edges": []}

    def test_env_var_config(self, monkeypatch):
        monkeypatch.setenv("GRAPH_DEPTH", "3")
        monkeypatch.setenv("GRAPH_TOP_K", "50")
        retriever = GraphRetriever()
        assert retriever._depth == 3
        assert retriever._top_k == 50

    def test_set_lightrag(self):
        retriever = GraphRetriever()
        assert retriever._lightrag is None
        retriever.set_lightrag("fake_instance")
        assert retriever._lightrag == "fake_instance"


# ═══════════════════════════════════════════════════════════
# HybridSearchEngine Integration Tests
# ═══════════════════════════════════════════════════════════


class TestHybridSearchEngine:
    def test_init_with_env_config(self, monkeypatch):
        monkeypatch.setenv("RRF_K", "50")
        monkeypatch.setenv("RRF_ENABLED_CHANNELS", "bm25,vector")
        engine = HybridSearchEngine()
        assert engine._rrf_k == 50
        assert "bm25" in engine._enabled_channels
        assert "vector" in engine._enabled_channels

    def test_init_with_components(self, sample_chunks):
        bm25 = BM25IndexManager()
        bm25.build_index(sample_chunks)
        graph = GraphRetriever()
        engine = HybridSearchEngine(bm25_manager=bm25, graph_retriever=graph)
        assert engine._bm25 is bm25
        assert engine._graph is graph

    @pytest.mark.asyncio
    async def test_bm25_only_search(self, sample_chunks):
        """Search with only BM25 channel enabled."""
        bm25 = BM25IndexManager()
        bm25.build_index(sample_chunks)
        engine = HybridSearchEngine(bm25_manager=bm25, graph_retriever=GraphRetriever())
        engine._enabled_channels = ["bm25"]

        results = await engine.search("年假政策")
        assert len(results) > 0
        assert all("bm25" in r.sources for r in results)

    @pytest.mark.asyncio
    async def test_search_graceful_channel_failure(self, sample_chunks):
        """When vector channel fails (no LightRAG), BM25 still works."""
        bm25 = BM25IndexManager()
        bm25.build_index(sample_chunks)
        engine = HybridSearchEngine(bm25_manager=bm25)

        # All channels enabled, but no LightRAG for vector/graph
        results = await engine.search("年假政策")
        # BM25 should succeed, others should fail gracefully
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_all_channels_disabled(self):
        """No channels enabled → empty results."""
        engine = HybridSearchEngine()
        engine._enabled_channels = []
        results = await engine.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_top_k_limit(self, sample_chunks):
        bm25 = BM25IndexManager()
        bm25.build_index(sample_chunks)
        engine = HybridSearchEngine(bm25_manager=bm25)
        engine._enabled_channels = ["bm25"]

        results = await engine.search("年假", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_async_build_index(self, sample_chunks):
        bm25 = BM25IndexManager()
        await bm25.rebuild_index_async(sample_chunks)
        assert bm25.is_ready
        assert bm25.chunk_count == len(sample_chunks)


# ═══════════════════════════════════════════════════════════
# Degradation Scenario Tests
# ═══════════════════════════════════════════════════════════


class TestDegradationScenarios:
    """Tests for fault tolerance and degradation."""

    def test_vector_parse_returns_empty(self):
        """parse_lightrag_context with empty/None input."""
        result = HybridSearchEngine._parse_lightrag_context("")
        assert result == []

        result = HybridSearchEngine._parse_lightrag_context(None)
        assert result == []

    def test_vector_parse_with_brackets(self):
        """Parse LightRAG context with [chunk_id] markers."""
        raw = "[c001] 这是第一段内容\n\n[c002] 这是第二段内容"
        result = HybridSearchEngine._parse_lightrag_context(raw)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_bm25_search_on_empty_index(self):
        """Search on unbuilt BM25 index returns empty."""
        mgr = BM25IndexManager()
        results = mgr.search("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_graph_retriever_handles_none_lightrag_gracefully(self):
        """Graph retriever should not crash when LightRAG is None."""
        retriever = GraphRetriever(lightrag_instance=None)
        # All public methods should return safely
        assert await retriever.search("query") == []
        assert await retriever._match_entities("query") == []
        scores, paths = await retriever._traverse_neighbors([])
        assert scores == {}
        assert paths == {}
        assert await retriever.get_subgraph(query="test") == {"nodes": [], "edges": []}
