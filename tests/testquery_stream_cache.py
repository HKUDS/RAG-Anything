import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from raganything.query import QueryMixin


class QueryHarness(QueryMixin):
    pass


@pytest.fixture
def query_harness():
    cache = SimpleNamespace(
        global_config={"enable_llm_cache": True},
        get_by_id=AsyncMock(return_value=None),
        upsert=AsyncMock(),
        index_done_callback=AsyncMock(),
    )
    query = QueryHarness()
    query.logger = logging.getLogger(__name__)
    query.lightrag = SimpleNamespace(llm_response_cache=cache, aquery=AsyncMock())
    query.vision_model_func = None
    query._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    query._process_multimodal_query_content = AsyncMock(
        return_value="enhanced question"
    )
    return query, cache


@pytest.mark.asyncio
async def test_streaming_queries_return_fresh_streams_without_result_cache(
    query_harness,
):
    query, cache = query_harness

    async def tokens():
        yield "hello"
        yield " world"

    query.lightrag.aquery.side_effect = [tokens(), tokens()]
    for _ in range(2):
        result = await query.aquery_with_multimodal(
            "question",
            [{"type": "table", "table_data": "x,y"}],
            stream=True,
            vlm_enhanced=False,
        )
        assert "".join([token async for token in result]) == "hello world"
    assert query.lightrag.aquery.await_count == 2
    assert all(
        call.kwargs["param"].stream for call in query.lightrag.aquery.await_args_list
    )
    cache.get_by_id.assert_not_awaited()
    cache.upsert.assert_not_awaited()
    cache.index_done_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_ignores_preexisting_cached_text(query_harness):
    query, cache = query_harness
    cache.get_by_id.return_value = {"return": "cached non-streamed answer"}

    async def tokens():
        yield "fresh"

    query.lightrag.aquery.return_value = tokens()
    result = await query.aquery_with_multimodal(
        "question",
        [{"type": "table"}],
        stream=True,
        vlm_enhanced=False,
    )
    assert [token async for token in result] == ["fresh"]
    cache.get_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_streaming_results_still_use_cache(query_harness):
    query, cache = query_harness
    query.lightrag.aquery.return_value = "answer"
    content = [{"type": "table"}]
    assert await query.aquery_with_multimodal("question", content) == "answer"
    cache.upsert.assert_awaited_once()
    cache.index_done_callback.assert_awaited_once()
    entry = next(iter(cache.upsert.await_args.args[0].values()))
    cache.get_by_id.return_value = entry
    assert await query.aquery_with_multimodal("question", content) == "answer"
    assert query.lightrag.aquery.await_count == 1
