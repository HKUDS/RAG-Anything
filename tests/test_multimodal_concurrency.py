"""Offline checks of the real batch method, without parser/LLM dependencies."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def _load_batch_method():
    source = Path(__file__).resolve().parents[1] / "raganything" / "processor.py"
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
    # Execute the complete, unchanged method with only its collaborators stubbed.
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
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    return namespace[method.name]


def _make_processor(generate, limit):
    lightrag = SimpleNamespace(
        doc_status=SimpleNamespace(
            get_by_id=AsyncMock(return_value={"chunks_count": 2})
        )
    )
    if limit is not None:
        lightrag.max_parallel_insert = limit
    processor = SimpleNamespace(
        lightrag=lightrag,
        logger=Mock(),
        modal_processors={"image": SimpleNamespace(generate_chunk_sections=generate)},
        _convert_to_lightrag_chunks_type_aware=Mock(return_value={"chunk": {}}),
    )
    for name in (
        "_store_chunks_to_lightrag_storage_type_aware",
        "_store_multimodal_main_entities",
        "_batch_extract_entities_lightrag_style_type_aware",
        "_batch_add_belongs_to_relations_type_aware",
        "_batch_merge_lightrag_style_type_aware",
        "_update_doc_status_with_chunks_type_aware",
    ):
        setattr(processor, name, AsyncMock(return_value=[]))
    return processor


async def _check_concurrency(limit, calls=1, fail_first=False):
    entered = asyncio.Queue()
    release = asyncio.Event()
    active = peak = 0
    seen = []

    async def generate(*, modal_content, **kwargs):
        nonlocal active, peak
        index = modal_content["index"]
        active += 1
        peak = max(peak, active)
        seen.append(index)
        entered.put_nowait(index)
        try:
            await release.wait()
            if fail_first and index == 0:
                raise RuntimeError("simulated description failure")
            return [{"description": str(index), "entity_info": {}}]
        finally:
            active -= 1

    processor = _make_processor(generate, limit)
    method = _load_batch_method()
    items = [{"type": "image", "index": i} for i in range(7)]
    tasks = [
        asyncio.create_task(method(processor, items, "test.pdf", f"doc-{i}"))
        for i in range(calls)
    ]
    expected = (2 if limit is None else limit) * calls
    try:
        for _ in range(expected):
            await asyncio.wait_for(entered.get(), timeout=2)
        # Drain ready callbacks, without timing assumptions or a wall-clock sleep.
        barrier = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(barrier.set_result, None)
        await barrier
        assert active == peak == expected
        assert entered.empty()
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert peak == expected
    assert len(seen) == len(items) * calls
    assert active == 0
    assert processor._convert_to_lightrag_chunks_type_aware.call_count == calls
    for call in processor._convert_to_lightrag_chunks_type_aware.call_args_list:
        descriptions = call.args[0]
        assert [data["description"] for data in descriptions] == [
            str(i) for i in range(7) if not (fail_first and i == 0)
        ]
    assert processor._update_doc_status_with_chunks_type_aware.await_count == calls
    if fail_first:
        processor.logger.error.assert_called()


@pytest.mark.parametrize("limit", [None, 1, 3])
def test_item_generation_uses_instance_limit_or_missing_attribute_fallback(limit):
    asyncio.run(_check_concurrency(limit))


def test_concurrent_batches_on_same_instance_have_independent_limits():
    asyncio.run(_check_concurrency(2, calls=2))


def test_failed_item_releases_slot_and_other_items_continue():
    asyncio.run(_check_concurrency(1, fail_first=True))
