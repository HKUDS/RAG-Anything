import logging
from types import SimpleNamespace

import pytest

from raganything.query.pipeline import QueryMixin


class _CapturingHybrid:
    def __init__(self):
        self.options = None

    async def search(self, _query, *, top_k, options):
        self.options = options
        return []


class _QueryHarness(QueryMixin):
    def __init__(self):
        self.lightrag = object()
        self.hybrid_search_engine = _CapturingHybrid()
        self.logger = logging.getLogger("rrf-settings-test")
        self.callback_manager = None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rrf", "hybrid"])
async def test_rrf_converts_immutable_personal_retrieval_values_to_local_options(mode):
    harness = _QueryHarness()
    resolved = SimpleNamespace(
        channels=("bm25", "graph"),
        bm25_top_k=11,
        vector_top_k=12,
        graph_top_k=13,
        graph_depth=4,
        rrf_k=47,
        bm25_tokenizer="jieba",
        bm25_k1=1.9,
        bm25_b=0.6,
    )

    result = await harness.aquery(
        "test", mode=mode, only_need_context=True, retrieval_options=resolved,
    )

    assert result == "No relevant documents found for your query."
    assert harness.hybrid_search_engine.options.channels == ("bm25", "graph")
    assert harness.hybrid_search_engine.options.bm25_k1 == 1.9
    assert harness.hybrid_search_engine.options.bm25_b == 0.6
    assert harness.hybrid_search_engine.options.graph_depth == 4
