"""
Tests for RRF Hybrid Search Engine.

Covers: BM25IndexManager, GraphRetriever, HybridSearchEngine, RRF fusion.
"""

import os
import pytest
import asyncio
import raganything.hybrid_search as hybrid_module
from dataclasses import dataclass
from types import SimpleNamespace

from raganything.hybrid_search import (
    ScoredChunk,
    BM25IndexManager,
    GraphRetriever,
    HybridSearchEngine,
    RetrievalOptions,
    BM25IndexKey,
    BoundedBM25IndexCache,
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


def test_scoped_index_cache_keeps_configs_isolated_and_evicts_lru():
    cache = BoundedBM25IndexCache(max_size=2)
    first = BM25IndexKey("workspace-a", "rev-1", "jieba", 1.5, 0.75)
    same = BM25IndexKey("workspace-a", "rev-1", "jieba", 1.5, 0.75)
    other_config = BM25IndexKey("workspace-a", "rev-1", "jieba", 2.0, 0.75)
    other_workspace = BM25IndexKey("workspace-b", "rev-1", "jieba", 1.5, 0.75)
    first_manager = BM25IndexManager()

    cache.put(first, first_manager)
    assert cache.get(same) is first_manager
    assert cache.get(other_config) is None
    cache.put(other_config, BM25IndexManager(k1=2.0))
    cache.put(other_workspace, BM25IndexManager())

    assert cache.get(first) is None
    assert cache.get(other_config) is not None
    assert cache.get(other_workspace) is not None


def test_scoped_index_cache_resize_applies_platform_capacity():
    cache = BoundedBM25IndexCache(max_size=3)
    keys = [BM25IndexKey("workspace", f"rev-{index}", "jieba", 1.5, 0.75) for index in range(3)]
    for key in keys:
        cache.put(key, BM25IndexManager())

    cache.resize(1)

    assert len(cache) == 1
    assert cache.get(keys[-1]) is not None


@pytest.mark.asyncio
async def test_revision_bm25_hit_skips_postgres_preparation(monkeypatch):
    cache = BoundedBM25IndexCache(max_size=2)
    manager = BM25IndexManager()
    key = BM25IndexKey("workspace-a", "revision-1", "jieba", 1.5, 0.75)
    cache.put(key, manager)
    monkeypatch.setattr(hybrid_module, "_bm25_index_cache", cache)
    monkeypatch.setattr(
        "raganything.services.pg_state_repo.get_pg_pool",
        lambda: (_ for _ in ()).throw(AssertionError("PG must not be read on hit")),
    )
    engine = HybridSearchEngine(
        lightrag_instance=SimpleNamespace(working_dir="workspace-a"),
    )

    resolved = await engine._bm25_for_options(
        RetrievalOptions(
            channels=("bm25",), workspace="workspace-a", corpus_revision="revision-1"
        )
    )

    assert resolved is manager


@pytest.mark.asyncio
async def test_revision_bm25_build_is_single_flight_when_a_waiter_is_cancelled(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = {"fetch": 0}

    class Connection:
        async def fetch(self, *_args):
            calls["fetch"] += 1
            started.set()
            await release.wait()
            return []

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr(hybrid_module, "_bm25_index_cache", BoundedBM25IndexCache(2))
    monkeypatch.setattr(hybrid_module, "_bm25_build_tasks", {})
    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())
    engine = HybridSearchEngine(
        lightrag_instance=SimpleNamespace(working_dir="workspace-a", text_chunks=None),
    )
    options = RetrievalOptions(
        channels=("bm25",), workspace="workspace-a", corpus_revision="revision-2"
    )

    cancelled_waiter = asyncio.create_task(engine._bm25_for_options(options))
    await started.wait()
    surviving_waiter = asyncio.create_task(engine._bm25_for_options(options))
    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter
    release.set()

    assert isinstance(await surviving_waiter, BM25IndexManager)
    assert calls["fetch"] == 1


@pytest.mark.asyncio
async def test_revision_bm25_build_records_pg_and_index_phases(monkeypatch):
    events = []

    class RecordingTiming:
        def __init__(self, trace_id):
            assert trace_id == "trace-private"

        def record(self, phase, _elapsed, **labels):
            events.append((phase, labels["outcome"], labels["cache_status"], labels["channel"]))

    class Connection:
        async def fetch(self, *_args):
            return [{"chunks_list": ["chunk-1"]}]

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    class Chunks:
        async def get_by_ids(self, _ids):
            return [{"id": "chunk-1", "content": "content"}]

    import raganything.services.query_timing as query_timing

    monkeypatch.setattr(query_timing, "QueryTiming", RecordingTiming)
    monkeypatch.setattr(hybrid_module, "_bm25_index_cache", BoundedBM25IndexCache(2))
    monkeypatch.setattr(hybrid_module, "_bm25_build_tasks", {})
    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())
    engine = HybridSearchEngine(
        lightrag_instance=SimpleNamespace(working_dir="workspace-a", text_chunks=Chunks()),
    )

    await engine._bm25_for_options(
        RetrievalOptions(
            channels=("bm25",),
            workspace="workspace-a",
            corpus_revision="revision-3",
            trace_id="trace-private",
        )
    )

    assert ("bm25_pg_read", "ok", "miss", "bm25") in events
    assert ("bm25_build", "ok", "miss", "bm25") in events


@pytest.mark.asyncio
async def test_hybrid_search_passes_graph_depth_as_a_local_option():
    class Graph:
        def __init__(self):
            self.received = None

        async def search(self, _query, _top_k, *, depth=None):
            self.received = depth
            return []

    graph = Graph()
    engine = HybridSearchEngine(graph_retriever=graph)

    await engine.search(
        "test", options=RetrievalOptions(channels=("graph",), graph_depth=0)
    )

    assert graph.received == 0


@pytest.mark.asyncio
async def test_hybrid_search_does_not_wait_for_cancellation_resistant_channel(
    sample_chunks,
):
    bm25 = BM25IndexManager()
    bm25.build_index(sample_chunks)
    engine = HybridSearchEngine(bm25_manager=bm25)
    release_stuck_channel = asyncio.Event()

    async def cancellation_resistant_vector(*_args, **_kwargs):
        try:
            await release_stuck_channel.wait()
        except asyncio.CancelledError:
            await release_stuck_channel.wait()
        return []

    engine._vector_search = cancellation_resistant_vector
    started = asyncio.get_running_loop().time()
    results = await engine.search(
        "年假政策",
        options=RetrievalOptions(
            channels=("bm25", "vector"),
            channel_timeout=0.02,
        ),
    )
    elapsed = asyncio.get_running_loop().time() - started
    release_stuck_channel.set()
    await asyncio.sleep(0)

    assert results
    assert elapsed < 0.2
    assert all("bm25" in result.sources for result in results)


@pytest.mark.asyncio
async def test_hybrid_search_cancels_channel_when_outer_search_is_cancelled():
    engine = HybridSearchEngine()
    channel_started = asyncio.Event()
    channel_cancelled = asyncio.Event()

    async def pending_vector(*_args, **_kwargs):
        channel_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            channel_cancelled.set()

    engine._vector_search = pending_vector
    search_task = asyncio.create_task(
        engine.search(
            "cancelled request",
            options=RetrievalOptions(channels=("vector",), channel_timeout=60),
        )
    )
    await asyncio.wait_for(channel_started.wait(), timeout=0.1)

    search_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await search_task

    await asyncio.wait_for(channel_cancelled.wait(), timeout=0.1)


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
    async def test_request_options_do_not_mutate_shared_channels(self, sample_chunks):
        bm25 = BM25IndexManager()
        bm25.build_index(sample_chunks)
        engine = HybridSearchEngine(bm25_manager=bm25, graph_retriever=GraphRetriever())
        engine._enabled_channels = ["vector"]

        results = await engine.search(
            "年假政策", options=RetrievalOptions(channels=("bm25",))
        )

        assert results
        assert all("bm25" in result.sources for result in results)
        assert engine._enabled_channels == ["vector"]

    @pytest.mark.asyncio
    async def test_scoped_bm25_failure_does_not_reuse_shared_index(self, monkeypatch, sample_chunks):
        from raganything.services import pg_state_repo

        shared = BM25IndexManager()
        shared.build_index(sample_chunks)
        engine = HybridSearchEngine(
            lightrag_instance=SimpleNamespace(working_dir="workspace-a"),
            bm25_manager=shared,
        )
        monkeypatch.setattr(
            pg_state_repo,
            "get_pg_pool",
            lambda: (_ for _ in ()).throw(RuntimeError("pg unavailable")),
        )

        manager = await engine._bm25_for_options(
            RetrievalOptions(
                channels=("bm25",),
                workspace="workspace-a",
                corpus_revision="rev-1",
                permission_scope="user:7",
                settings_fingerprint="settings-a",
                bm25_k1=2.0,
            )
        )

        assert manager is not shared
        assert manager._k1 == 2.0
        assert manager.chunk_count == 0

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
    async def test_deadline_bounded_channel_returns_before_router_watchdog(self, monkeypatch):
        """A late RRF channel cannot race the router's 60ms deadline poll."""
        engine = HybridSearchEngine()
        engine._enabled_channels = ["vector", "graph"]
        cancelled = asyncio.Event()

        async def vector_search(_query, _top_k):
            return [ScoredChunk("vector-id", "usable", 1.0, ["vector"])]

        async def late_graph_search(_query, _top_k, _depth):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(engine, "_vector_search", vector_search)
        monkeypatch.setattr(engine, "_graph_search", late_graph_search)
        deadline = asyncio.get_running_loop().time() + 0.2
        search_task = asyncio.create_task(engine.search(
            "deadline-test",
            options=RetrievalOptions(
                channels=("vector", "graph"),
                channel_timeout=1.0,
                deadline_monotonic=deadline,
            ),
        ))

        while not search_task.done():
            assert asyncio.get_running_loop().time() < deadline
            remaining = deadline - asyncio.get_running_loop().time()
            await asyncio.sleep(min(0.06, remaining))

        results = await search_task
        assert [result.chunk_id for result in results] == ["vector-id"]
        await asyncio.wait_for(cancelled.wait(), timeout=0.2)

    @pytest.mark.asyncio
    async def test_expired_deadline_does_not_start_a_channel(self, monkeypatch):
        engine = HybridSearchEngine()
        engine._enabled_channels = ["vector"]
        started = False

        async def vector_search(_query, _top_k):
            nonlocal started
            started = True
            return []

        monkeypatch.setattr(engine, "_vector_search", vector_search)

        await engine.search(
            "deadline-test",
            options=RetrievalOptions(
                channels=("vector",),
                deadline_monotonic=asyncio.get_running_loop().time() - 0.01,
            ),
        )

        assert started is False

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
