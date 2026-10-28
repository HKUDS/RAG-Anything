"""Prove multimodal KG extraction call count does not scale ~N with images (#348)."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Do NOT stub lightrag/raganything in sys.modules at import time — that poisons
# collection of other tests in the same pytest process (CI runs `pytest tests/`).

from lightrag.utils import compute_mdhash_id
from raganything.config import RAGAnythingConfig
from raganything.processor import ProcessorMixin


class _FakeTokenizer:
    """Rough tokenizer: 1 token ≈ 4 chars (matches extraction fallback)."""

    def encode(self, text):
        return list(range(max(1, len(text) // 4)))


def _image_data(index: int, description: str, neighbor: str) -> dict:
    return {
        "index": index,
        "content_type": "image",
        "description": description,
        "entity_info": {
            "entity_name": f"Image {index}",
            "entity_type": "image",
            "summary": description[:80],
        },
        "original_item": {
            "type": "image",
            "img_path": f"/tmp/img_{index}.png",
            "image_caption": [f"caption-{index}"],
            "image_footnote": [],
            "_neighbor_text": neighbor,
            "_section_path": "Products",
        },
        "item_info": {"page_idx": 0, "index": index, "type": "image"},
        "chunk_order_index": index,
        "file_path": "page.html",
    }


def test_description_only_text_omits_neighbor_text():
    mixin = ProcessorMixin.__new__(ProcessorMixin)
    neighbor = "UNIQUE_NEIGHBOR_TOKEN shared page prose about Acme Widget Pro"
    data = _image_data(0, "A red product photo of Acme Widget Pro", neighbor)
    text = mixin._modal_description_only_text(data)
    assert "UNIQUE_NEIGHBOR_TOKEN" not in text
    assert "Acme Widget Pro" in text  # from description
    assert "caption-0" in text
    assert "[image]" in text


def test_packed_mode_collapses_many_short_captions_into_few_chunks():
    mixin = ProcessorMixin.__new__(ProcessorMixin)
    mixin.lightrag = SimpleNamespace(
        tokenizer=_FakeTokenizer(),
        chunk_token_size=500,
    )
    neighbor = "SHARED " * 40  # would bloat per-item templates
    data_list = [
        _image_data(i, f"Short visual description number {i} of the product.", neighbor)
        for i in range(8)
    ]
    # Build fake stored chunks (full templates not needed beyond ids)
    lightrag_chunks = {}
    for data in data_list:
        # Use apply path via a minimal stub template
        content = f"FULL TEMPLATE with {data['original_item']['_neighbor_text']} :: {data['description']}"
        cid = compute_mdhash_id(content, prefix="chunk-")
        # Monkeypatch apply to stable content matching convert hashing
        data["_test_full"] = content
        lightrag_chunks[cid] = {
            "content": content,
            "tokens": 100,
            "full_doc_id": "doc-1",
            "chunk_order_index": data["chunk_order_index"],
            "file_path": "page.html",
        }

    # Patch _apply_chunk_template so hashing matches our fake stored chunks
    mixin._apply_chunk_template = lambda ctype, item, desc: next(
        d["_test_full"] for d in data_list if d["description"] == desc
    )

    packed = mixin._build_multimodal_extraction_chunks(
        data_list, lightrag_chunks, mode="packed"
    )
    per_item = mixin._build_multimodal_extraction_chunks(
        data_list, lightrag_chunks, mode="per_item"
    )

    assert len(per_item) == 8
    assert len(packed) < 8
    assert len(packed) >= 1
    # Packed content must not include neighbor prose
    for chunk in packed.values():
        assert "SHARED" not in chunk["content"]
        assert "Short visual description" in chunk["content"]


def test_config_defaults_to_packed_mode():
    cfg = RAGAnythingConfig()
    assert cfg.multimodal_kg_extraction_mode == "packed"
    assert cfg.max_parallel_modal_items is None


def _load_batch_method():
    source = REPO_ROOT / "raganything" / "processor.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    mixin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProcessorMixin"
    )
    method = next(
        node
        for node in mixin.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_process_multimodal_content_batch_type_aware"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            method,
        ],
        type_ignores=[],
    )
    namespace = {
        "asyncio": asyncio,
        "get_processor_for_type": lambda processors, kind: processors.get(kind),
    }
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)  # noqa: S102
    return namespace[method.name]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expect_extract_calls_max,expect_merge",
    [
        ("skip", 0, False),
        ("packed", 1, True),  # 8 short captions -> 1 pack with large budget
        ("per_item", 8, True),
    ],
)
async def test_batch_path_extract_call_scaling(
    mode, expect_extract_calls_max, expect_merge
):
    """Mocked end-to-end of the batch method: vision N, extract ≪ N when packed/skip."""
    batch = _load_batch_method()
    vision_calls = []
    extract_calls = []
    merge_calls = []

    async def generate(*, modal_content, **kwargs):
        vision_calls.append(modal_content["index"])
        return [
            {
                "description": f"desc-{modal_content['index']}",
                "entity_info": {
                    "entity_name": f"E{modal_content['index']}",
                    "entity_type": "image",
                    "summary": "s",
                },
                "window_meta": None,
            }
        ]

    async def fake_extract(chunks):
        extract_calls.append(len(chunks))
        return [({}, {}) for _ in chunks]

    async def fake_merge(*args, **kwargs):
        merge_calls.append(1)

    def build_extraction(data_list, lightrag_chunks, mode="packed"):
        # Mirror real packing enough for call-count assertions
        if mode == "per_item":
            return {
                f"c{i}": {"content": d["description"]} for i, d in enumerate(data_list)
            }
        if mode == "packed":
            return {
                "pack0": {"content": "\n\n".join(d["description"] for d in data_list)}
            }
        return {}

    config = SimpleNamespace(
        multimodal_kg_extraction_mode=mode,
        max_parallel_modal_items=8,
    )
    processor = SimpleNamespace(
        lightrag=SimpleNamespace(
            doc_status=SimpleNamespace(
                get_by_id=AsyncMock(return_value={"chunks_count": 0})
            ),
            max_parallel_insert=2,
            chunk_token_size=1200,
            tokenizer=_FakeTokenizer(),
        ),
        logger=Mock(),
        config=config,
        modal_processors={"image": SimpleNamespace(generate_chunk_sections=generate)},
        _convert_to_lightrag_chunks_type_aware=Mock(
            return_value={f"chunk-{i}": {"content": f"c{i}"} for i in range(8)}
        ),
        _build_multimodal_extraction_chunks=build_extraction,
        _store_chunks_to_lightrag_storage_type_aware=AsyncMock(),
        _store_multimodal_main_entities=AsyncMock(),
        _batch_extract_entities_lightrag_style_type_aware=fake_extract,
        _batch_add_belongs_to_relations_type_aware=AsyncMock(
            side_effect=lambda results, data: results
        ),
        _batch_merge_lightrag_style_type_aware=fake_merge,
        _update_doc_status_with_chunks_type_aware=AsyncMock(),
    )

    items = [{"type": "image", "index": i, "_content_list_index": i} for i in range(8)]
    await batch(processor, items, "page.html", "doc-1")

    assert len(vision_calls) == 8
    if expect_extract_calls_max == 0:
        assert extract_calls == []
    else:
        assert len(extract_calls) == 1  # one batch extract invocation
        assert extract_calls[0] <= expect_extract_calls_max
        if mode == "packed":
            assert extract_calls[0] < 8
        if mode == "per_item":
            assert extract_calls[0] == 8
    assert bool(merge_calls) is expect_merge


@pytest.mark.asyncio
async def test_max_parallel_modal_items_overrides_max_parallel_insert():
    batch = _load_batch_method()
    entered = asyncio.Queue()
    release = asyncio.Event()
    active = peak = 0

    async def generate(*, modal_content, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await entered.put(modal_content["index"])
        await release.wait()
        active -= 1
        return [
            {
                "description": "d",
                "entity_info": {
                    "entity_name": "e",
                    "entity_type": "image",
                    "summary": "s",
                },
                "window_meta": None,
            }
        ]

    processor = SimpleNamespace(
        lightrag=SimpleNamespace(
            doc_status=SimpleNamespace(
                get_by_id=AsyncMock(return_value={"chunks_count": 0})
            ),
            max_parallel_insert=8,  # would allow 8 if not overridden
        ),
        logger=Mock(),
        config=SimpleNamespace(
            multimodal_kg_extraction_mode="skip",
            max_parallel_modal_items=2,
        ),
        modal_processors={"image": SimpleNamespace(generate_chunk_sections=generate)},
        _convert_to_lightrag_chunks_type_aware=Mock(return_value={"c": {}}),
        _build_multimodal_extraction_chunks=Mock(return_value={}),
        _store_chunks_to_lightrag_storage_type_aware=AsyncMock(),
        _store_multimodal_main_entities=AsyncMock(),
        _batch_extract_entities_lightrag_style_type_aware=AsyncMock(return_value=[]),
        _batch_add_belongs_to_relations_type_aware=AsyncMock(return_value=[]),
        _batch_merge_lightrag_style_type_aware=AsyncMock(),
        _update_doc_status_with_chunks_type_aware=AsyncMock(),
    )

    items = [{"type": "image", "index": i} for i in range(4)]
    task = asyncio.create_task(batch(processor, items, "f", "d"))
    await entered.get()
    await entered.get()
    await asyncio.sleep(0.05)
    assert peak == 2
    assert entered.empty()
    release.set()
    await task
