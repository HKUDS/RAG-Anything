"""Exact page-context compatibility and ingestion-local index lifetime."""

import asyncio
import random

import pytest

from raganything.document_context import (
    _page_indexes,
    document_context,
    page_context_items,
)
from raganything.modalprocessors import (
    BaseModalProcessor,
    ContextConfig,
    ContextExtractor,
)


def reference_context(extractor, content, info):
    """Baseline scan, including its error-to-empty behavior at the public boundary."""
    try:
        page = info.get("page_idx", 0)
        start = max(0, page - extractor.config.context_window)
        end = page + extractor.config.context_window + 1
        texts = []
        for item in content:
            item_page = item.get("page_idx", 0)
            if (
                start <= item_page < end
                and item.get("type", "") in extractor.config.filter_content_types
            ):
                text = extractor._extract_text_from_item(item)
                if text and text.strip():
                    texts.append(
                        f"[Page {item_page}] {text}" if item_page != page else text
                    )
        return extractor._truncate_context("\n".join(texts))
    except Exception:
        return ""


def processor(config=None, tokenizer=None):
    result = BaseModalProcessor.__new__(BaseModalProcessor)
    result.content_source = None
    result.content_format = "auto"
    result.context_extractor = ContextExtractor(config, tokenizer)
    return result


class CharacterTokenizer:
    def encode(self, text):
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)


@pytest.mark.asyncio
@pytest.mark.parametrize("tokenizer", [None, CharacterTokenizer()])
async def test_exact_context_for_randomized_interleaved_pages_and_configs(tokenizer):
    rng = random.Random(1247)
    contents = [[], [{"type": "text", "text": "one"}]]
    for size in (3, 40, 300):
        content = []
        for index in range(size):
            item = {
                "type": rng.choice(["text", "image", "table", "equation"]),
                "text": rng.choice(["", " ", f" Héading {index}\n中 "]),
                "text_level": rng.randrange(3),
                "image_caption": "caption",
                "table_caption": ["A", "B"],
            }
            if index % 7:
                item["page_idx"] = rng.randrange(-2, 14)
            content.append(item)
        rng.shuffle(content)
        contents.append(content)

    @document_context
    async def check(content, config):
        p = processor(config, tokenizer)
        p.set_content_source(content, "minerU")
        for page in (-3, 0, 1, 7, 14, 30):
            expected = reference_context(
                p.context_extractor, content, {"page_idx": page}
            )
            assert p._get_context_for_item({"page_idx": page}) == expected

    for content in contents:
        for window in (-1, 0, 1, 3, 100):
            for captions, headers, filters in [
                (True, True, ["text"]),
                (True, False, ["text", "image", "table"]),
                (False, True, []),
            ]:
                await check(
                    content,
                    ContextConfig(
                        context_window=window,
                        max_context_tokens=17,
                        include_headers=headers,
                        include_captions=captions,
                        filter_content_types=filters,
                    ),
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "1", 1.5, True, [], {}])
async def test_non_integer_page_metadata_keeps_baseline_behavior(bad):
    content = [
        {"type": "text", "text": "valid", "page_idx": 0},
        {"type": "text", "text": "unusual", "page_idx": bad},
    ]

    @document_context
    async def check():
        p = processor()
        p.set_content_source(content)
        assert p._get_context_for_item({"page_idx": 0}) == reference_context(
            p.context_extractor, content, {}
        )
        assert page_context_items(content, 0, 2) is content

    await check()


@pytest.mark.asyncio
async def test_malformed_block_preserves_error_behavior():
    @document_context
    async def check():
        p = processor()
        p.set_content_source([{"type": "text", "text": "valid"}, None])
        assert p._get_context_for_item({}) == ""

    await check()


@pytest.mark.asyncio
async def test_index_is_lazy_shared_and_released_and_nested_scope_restores_parent():
    content = [{"type": "text", "text": str(i), "page_idx": i} for i in range(10)]
    p, other = processor(), processor()

    @document_context
    async def nested():
        other.set_content_source([{"type": "text", "text": "nested"}])
        assert other._get_context_for_item({}) == "nested"
        assert id(content) not in _page_indexes.get()

    @document_context
    async def check():
        p.set_content_source(content)
        other.set_content_source(content)
        index = _page_indexes.get()[id(content)]
        assert index.buckets is None
        assert p._get_context_for_item({"page_idx": 5}) == "[Page 4] 4\n5\n[Page 6] 6"
        assert index.buckets is None
        assert (
            other._get_context_for_item({"page_idx": 5}) == "[Page 4] 4\n5\n[Page 6] 6"
        )
        buckets = index.buckets
        await asyncio.gather(
            *[
                asyncio.to_thread(other._get_context_for_item, {"page_idx": 5})
                for _ in range(3)
            ]
        )
        assert index.buckets is buckets
        await nested()
        assert _page_indexes.get()[id(content)] is index
        # Contents/configuration are formatted live, not cached as context text.
        content[5]["text"] = "new"
        other.context_extractor.config.include_headers = False
        assert "new" in other._get_context_for_item({"page_idx": 5})

    await check()
    assert _page_indexes.get() is None


@pytest.mark.asyncio
async def test_direct_mutable_sources_never_use_index_and_setters_replace_operation_source():
    content = [{"type": "text", "text": "old", "page_idx": 0}]
    p = processor()
    p.set_content_source(content)
    assert p._get_context_for_item({}) == "old"
    content[0]["page_idx"] = 8
    assert p._get_context_for_item({}) == ""
    content[:] = [{"type": "text", "text": "replacement"}]
    assert p._get_context_for_item({}) == "replacement"

    @document_context
    async def check():
        p.set_content_source(content)
        assert p._get_context_for_item({}) == "replacement"
        # Re-registering a source after page edits must invalidate its index.
        content[0]["page_idx"] = 8
        p.set_content_source(content)
        assert p._get_context_for_item({}) == ""
        content.append({"type": "text", "text": "appended", "page_idx": 0})
        assert p._get_context_for_item({}) == "appended"
        p.set_content_source("plain context", "text")
        assert p._get_context_for_item({}) == "plain context"

    await check()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chunk", "page"])
async def test_text_chunks_do_not_build_page_index(mode):
    @document_context
    async def check():
        p = processor(ContextConfig(context_mode=mode))
        source = ["left", "current", "right"]
        p.set_content_source(source, "text_chunks")
        assert p._get_context_for_item({"index": 1}) == "left\nright"
        assert not _page_indexes.get()

    await check()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_index_scope_restored_after_failure(failure):
    @document_context
    async def fail():
        p = processor()
        p.set_content_source([{"type": "text", "text": "temporary"}])
        p._get_context_for_item({})
        raise failure()

    with pytest.raises(failure):
        await fail()
    assert _page_indexes.get() is None


@pytest.mark.asyncio
async def test_list_subclass_with_custom_iteration_falls_back_to_scan():
    class ReversedList(list):
        def __iter__(self):
            return reversed(self)

    source = ReversedList(
        [
            {"type": "text", "text": "first", "page_idx": 0},
            {"type": "text", "text": "second", "page_idx": 1},
            {"type": "text", "text": "far away", "page_idx": 9},
        ]
    )

    @document_context
    async def check():
        p = processor()
        p.set_content_source(source)
        assert p._get_context_for_item({}) == "[Page 1] second\nfirst"
        assert id(source) not in _page_indexes.get()

    await check()


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [0.5, True, "0", None])
async def test_non_integer_query_bounds_preserve_baseline(page):
    source = [
        {"type": "text", "text": "first", "page_idx": 0},
        {"type": "text", "text": "second", "page_idx": 2},
    ]

    @document_context
    async def check():
        p = processor()
        p.set_content_source(source)
        assert p._get_context_for_item({"page_idx": page}) == reference_context(
            p.context_extractor, source, {"page_idx": page}
        )

    await check()
