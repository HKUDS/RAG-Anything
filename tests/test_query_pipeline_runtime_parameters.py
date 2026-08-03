import logging
from types import SimpleNamespace

import pytest

from raganything.query.pipeline import QueryMixin


def _query_mixin(lightrag, hybrid_engine=None):
    query = object.__new__(QueryMixin)
    query.lightrag = lightrag
    query.hybrid_search_engine = hybrid_engine
    query.callback_manager = None
    query.logger = logging.getLogger("raganything.query.pipeline")
    return query


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "global", "naive"])
async def test_non_rrf_modes_strip_rrf_only_runtime_options(mode):
    captured = {}

    class LightRAG:
        async def aquery(self, _query, *, param, system_prompt=None):
            captured["param"] = param
            return "context"

    result = await _query_mixin(LightRAG()).aquery(
        "question",
        mode=mode,
        only_need_context=True,
        retrieval_options=SimpleNamespace(channels=("vector",)),
        vlm_enhanced=False,
    )

    assert result == "context"
    assert captured["param"].mode == mode
    assert captured["param"].only_need_context is True


@pytest.mark.asyncio
async def test_rrf_fallback_strips_pipeline_only_runtime_options():
    captured = {}

    class LightRAG:
        async def aquery(self, _query, *, param, system_prompt=None):
            captured["param"] = param
            return "fallback context"

    result = await _query_mixin(LightRAG())._aquery_rrf(
        "question",
        only_need_context=True,
        retrieval_options=SimpleNamespace(channels=("vector",)),
        vlm_enhanced=False,
    )

    assert result == "fallback context"
    assert captured["param"].mode == "hybrid"
    assert captured["param"].only_need_context is True
