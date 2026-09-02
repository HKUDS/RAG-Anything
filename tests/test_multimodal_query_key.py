"""Tests for multimodal query cache key generation."""

import logging
from types import SimpleNamespace

import pytest

from raganything.query import QueryMixin


def _cache_key(file_path: str) -> str:
    return QueryMixin()._generate_multimodal_cache_key(
        "describe this image",
        [{"type": "image", "img_path": file_path}],
        "mix",
    )


def _query_options_key(**kwargs) -> str:
    return QueryMixin()._generate_multimodal_cache_key(
        "summarize this table",
        [{"type": "table", "table_data": "name,value\nalpha,1"}],
        "mix",
        **kwargs,
    )


def test_cache_key_distinguishes_same_named_files_with_different_content(tmp_path):
    first = tmp_path / "first" / "diagram.png"
    second = tmp_path / "second" / "diagram.png"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first image")
    second.write_bytes(b"second image")

    assert _cache_key(str(first)) != _cache_key(str(second))


def test_cache_key_changes_when_file_content_changes(tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"original image")
    original_key = _cache_key(str(image))

    image.write_bytes(b"updated image")

    assert _cache_key(str(image)) != original_key


def test_cache_key_distinguishes_unavailable_paths_with_same_name(tmp_path):
    first = tmp_path / "first" / "missing.png"
    second = tmp_path / "second" / "missing.png"

    assert _cache_key(str(first)) != _cache_key(str(second))


@pytest.mark.parametrize(
    ("first_options", "second_options"),
    [
        ({"only_need_context": False}, {"only_need_context": True}),
        ({"only_need_prompt": False}, {"only_need_prompt": True}),
        ({"chunk_top_k": 10}, {"chunk_top_k": 20}),
        (
            {"conversation_history": [{"role": "user", "content": "first"}]},
            {"conversation_history": [{"role": "user", "content": "second"}]},
        ),
        ({"user_prompt": "be concise"}, {"user_prompt": "be detailed"}),
        ({"enable_rerank": False}, {"enable_rerank": True}),
        ({"include_references": False}, {"include_references": True}),
    ],
)
def test_cache_key_distinguishes_result_affecting_query_options(
    first_options, second_options
):
    assert _query_options_key(**first_options) != _query_options_key(**second_options)


def test_cache_key_distinguishes_model_functions():
    def first_model():
        return None

    def second_model():
        return None

    first_key = _query_options_key(model_func=first_model)

    assert first_key == _query_options_key(model_func=first_model)
    assert first_key != _query_options_key(model_func=second_model)


class _MemoryCache:
    def __init__(self):
        self.global_config = {"enable_llm_cache": True}
        self.entries = {}

    async def get_by_id(self, cache_key):
        return self.entries.get(cache_key)

    async def upsert(self, entries):
        self.entries.update(entries)

    async def index_done_callback(self):
        return None


class _QueryHarness(QueryMixin):
    def __init__(self):
        self.logger = logging.getLogger("test.multimodal_query_key")
        self.lightrag = SimpleNamespace(llm_response_cache=_MemoryCache())
        self.only_context_calls = []

    async def _ensure_lightrag_initialized(self):
        return {"success": True}

    async def _process_multimodal_query_content(self, query, multimodal_content):
        return f"enhanced: {query}"

    async def aquery(self, query, mode="mix", system_prompt=None, **kwargs):
        only_need_context = kwargs.get("only_need_context", False)
        self.only_context_calls.append(only_need_context)
        return "retrieved context" if only_need_context else "generated answer"


@pytest.mark.asyncio
async def test_context_only_cache_entry_is_not_reused_as_a_generated_answer():
    harness = _QueryHarness()
    content = [{"type": "table", "table_data": "name,value\nalpha,1"}]

    context = await harness.aquery_with_multimodal(
        "summarize this table",
        content,
        only_need_context=True,
    )
    answer = await harness.aquery_with_multimodal(
        "summarize this table",
        content,
        only_need_context=False,
    )

    assert context == "retrieved context"
    assert answer == "generated answer"
    assert harness.only_context_calls == [True, False]
