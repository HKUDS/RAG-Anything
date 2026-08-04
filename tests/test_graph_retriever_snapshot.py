"""Tests for GraphRetriever query-scoped snapshot retrieval.

Covers: single-pass snapshot loading, seed capping, batch chunk fetching, and
result-shape preservation for ``search`` / ``search_with_paths``.
"""

import pytest
from types import SimpleNamespace

from raganything.graph_rag import GraphRAGConfig, GraphRetriever


class FakeGraphStorage:
    """Minimal chunk_entity_relation_graph stub counting storage access."""

    def __init__(self, nodes, edges):
        self._nodes = nodes
        self._edges = edges
        self.get_all_nodes_calls = 0
        self.get_all_edges_calls = 0
        self.per_node_calls = 0

    async def get_all_nodes(self):
        self.get_all_nodes_calls += 1
        return [dict(n) for n in self._nodes]

    async def get_all_edges(self):
        self.get_all_edges_calls += 1
        return [dict(e) for e in self._edges]

    async def get_node(self, node_id):
        self.per_node_calls += 1
        return None

    async def get_node_edges(self, node_id):
        self.per_node_calls += 1
        return []

    async def get_edge(self, src, tgt):
        self.per_node_calls += 1
        return None


class FakeTextChunks:
    def __init__(self, records):
        self._records = records
        self.get_by_ids_calls = 0
        self.get_by_id_calls = 0

    async def get_by_ids(self, ids):
        self.get_by_ids_calls += 1
        return [self._records.get(cid) for cid in ids]

    async def get_by_id(self, chunk_id):
        self.get_by_id_calls += 1
        return self._records.get(chunk_id)


NODES = [
    {
        "id": "e1", "entity_id": "e1", "entity_name": "BatteryMgmt",
        "entity_type": "module", "chunk_ids": ["c1"],
    },
    {
        "id": "e2", "entity_id": "e2", "entity_name": "ChargeCtrl",
        "entity_type": "function", "chunk_ids": ["c2"],
    },
]

EDGES = [{"source": "e1", "target": "e2", "relation": "related_to"}]

CHUNKS = {
    "c1": {"id": "c1", "content": "battery management handles energy dispatch", "document_name": "docA", "file_path": "a.pdf"},
    "c2": {"id": "c2", "content": "charge control executes the charging flow", "document_name": "docB", "file_path": "b.pdf"},
}


def make_retriever(**config_overrides):
    graph = FakeGraphStorage(NODES, EDGES)
    chunks = FakeTextChunks(CHUNKS)
    lightrag = SimpleNamespace(
        chunk_entity_relation_graph=graph,
        text_chunks=chunks,
    )
    retriever = GraphRetriever(
        lightrag_instance=lightrag,
        config=GraphRAGConfig(**config_overrides),
    )
    return retriever, graph, chunks


@pytest.mark.asyncio
async def test_search_uses_single_snapshot_and_batch_chunk_fetch():
    retriever, graph, chunks = make_retriever()
    results = await retriever.search("battery", top_k=10)

    assert len(results) == 2
    assert results[0].chunk_id == "c1"
    assert results[0].content == "battery management handles energy dispatch"
    assert results[0].document_name == "docA"
    assert results[0].file_path == "a.pdf"
    assert results[0].sources == ["graph"]
    assert results[0].graph_rank == 1
    # Depth-1 neighbor chunk carries the seed entity path
    assert results[1].chunk_id == "c2"
    assert results[1].graph_entities == ["BatteryMgmt"]
    # Storage is touched exactly once per snapshot call, never per node/edge
    assert graph.get_all_nodes_calls == 1
    assert graph.get_all_edges_calls == 1
    assert graph.per_node_calls == 0
    assert chunks.get_by_ids_calls == 1
    assert chunks.get_by_id_calls == 0


@pytest.mark.asyncio
async def test_search_with_paths_preserves_shape_and_stats():
    retriever, graph, _chunks = make_retriever()
    result = await retriever.search_with_paths("battery", top_k=10)

    assert set(result.keys()) == {"matched_entities", "results", "graph_stats"}
    assert result["graph_stats"]["total_entities"] == 2
    assert result["graph_stats"]["matched_count"] == 1
    assert result["graph_stats"]["traversal_depth"] == retriever._depth
    assert result["matched_entities"][0]["name"] == "BatteryMgmt"
    assert len(result["results"]) == 2
    path_map = {r["chunk"].chunk_id: r["paths"] for r in result["results"]}
    # Direct seed chunk has a "direct" path; neighbor chunk records the relation
    assert path_map["c1"] == [{"entity": "BatteryMgmt", "relation": "direct", "depth": 0}]
    assert path_map["c2"] == [{"entity": "BatteryMgmt", "relation": "related_to", "depth": 1}]
    assert graph.get_all_nodes_calls == 1
    assert graph.get_all_edges_calls == 1


@pytest.mark.asyncio
async def test_seed_cap_bounds_traversal_but_reports_all_matches():
    nodes = [
        {
            "id": "e%d" % i, "entity_id": "e%d" % i,
            "entity_name": "Battery%d" % i, "entity_type": "module",
            "chunk_ids": ["c%d" % i],
        }
        for i in range(1, 6)
    ]
    records = {
        "c%d" % i: {"id": "c%d" % i, "content": "content %d" % i, "document_name": "doc%d" % i}
        for i in range(1, 6)
    }
    graph = FakeGraphStorage(nodes, [])
    chunks = FakeTextChunks(records)
    lightrag = SimpleNamespace(chunk_entity_relation_graph=graph, text_chunks=chunks)
    retriever = GraphRetriever(
        lightrag_instance=lightrag,
        config=GraphRAGConfig(graph_max_seed_entities=2),
    )

    result = await retriever.search_with_paths("battery", top_k=10)

    assert result["graph_stats"]["matched_count"] == 5
    assert len(result["matched_entities"]) == 5
    assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_no_graph_returns_empty():
    retriever = GraphRetriever(lightrag_instance=SimpleNamespace())
    assert await retriever.search("battery", top_k=10) == []
    result = await retriever.search_with_paths("battery")
    assert result["graph_stats"]["total_entities"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_missing_chunk_falls_back_to_single_fetch():
    graph = FakeGraphStorage(NODES, EDGES)

    class PartialChunks:
        async def get_by_ids(self, ids):
            return [None for _ in ids]

        async def get_by_id(self, chunk_id):
            return CHUNKS.get(chunk_id)

    lightrag = SimpleNamespace(
        chunk_entity_relation_graph=graph,
        text_chunks=PartialChunks(),
    )
    retriever = GraphRetriever(lightrag_instance=lightrag)

    results = await retriever.search("battery", top_k=10)

    assert len(results) == 2
    assert results[0].content == "battery management handles energy dispatch"

def test_config_snapshot_exposes_all_fields():
    retriever = GraphRetriever(
        lightrag_instance=SimpleNamespace(),
        config=GraphRAGConfig(
            graph_depth=3,
            graph_top_k=12,
            graph_min_score=0.25,
            graph_max_seed_entities=7,
        ),
    )
    assert retriever.config_snapshot == {
        "graph_depth": 3,
        "graph_top_k": 12,
        "graph_min_score": 0.25,
        "graph_max_seed_entities": 7,
    }


@pytest.mark.asyncio
async def test_snapshot_load_failure_degrades_gracefully():
    class FailingGraph:
        async def get_all_nodes(self):
            raise RuntimeError("storage unavailable")

        async def get_all_edges(self):
            raise RuntimeError("storage unavailable")

    lightrag = SimpleNamespace(chunk_entity_relation_graph=FailingGraph())
    retriever = GraphRetriever(lightrag_instance=lightrag)

    assert await retriever.search("battery", top_k=10) == []
    result = await retriever.search_with_paths("battery")
    assert result["graph_stats"]["total_entities"] == 0
    assert result["matched_entities"] == []
    assert result["results"] == []


@pytest.mark.asyncio
async def test_quoted_storage_ids_are_normalized():
    """PG agtype ids arrive wrapped in JSON quotes; normalization must keep
    matching/traversal working without per-node storage calls."""
    nodes = [
        {
            "id": '"e1"', "entity_id": '"e1"', "entity_name": "BatteryMgmt",
            "entity_type": "module", "chunk_ids": ["c1"],
        },
        {
            "id": '"e2"', "entity_id": '"e2"', "entity_name": "ChargeCtrl",
            "entity_type": "function", "chunk_ids": ["c2"],
        },
    ]
    edges = [{"source": '"e1"', "target": '"e2"', "relation": "related_to"}]
    graph = FakeGraphStorage(nodes, edges)
    chunks = FakeTextChunks(CHUNKS)
    lightrag = SimpleNamespace(chunk_entity_relation_graph=graph, text_chunks=chunks)
    retriever = GraphRetriever(lightrag_instance=lightrag)

    results = await retriever.search("battery", top_k=10)
    assert len(results) == 2
    assert results[1].chunk_id == "c2"
    assert results[1].graph_entities == ["BatteryMgmt"]

    paths_result = await retriever.search_with_paths("battery", top_k=10)
    assert paths_result["graph_stats"]["total_entities"] == 2
    assert paths_result["matched_entities"][0]["degree"] == 1
    assert graph.get_all_nodes_calls == 2
    assert graph.get_all_edges_calls == 2
    assert graph.per_node_calls == 0
