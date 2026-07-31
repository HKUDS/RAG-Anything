import asyncio

import pytest

from raganything.modalprocessors import base
from raganything.modalprocessors.base import BaseModalProcessor
from raganything.modalprocessors.image import ImageModalProcessor


@pytest.mark.asyncio
async def test_modal_caption_timeout_cancels_stalled_provider(monkeypatch):
    cancelled = asyncio.Event()

    async def stalled_caption(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    processor = object.__new__(BaseModalProcessor)
    processor.modal_caption_func = stalled_caption
    monkeypatch.setattr(base, "_modal_caption_timeout_seconds", lambda: 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await processor._call_modal_caption("describe this")

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_modal_caption_allows_synchronous_provider_result():
    processor = object.__new__(BaseModalProcessor)
    processor.modal_caption_func = lambda *args, **kwargs: "caption"

    assert await processor._call_modal_caption("describe this") == "caption"


@pytest.mark.asyncio
async def test_image_description_timeout_uses_existing_fallback(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "meaningful-image.png"
    image = Image.new("RGB", (32, 32))
    image.putdata([
        ((index * 17) % 255, (index * 29) % 255, (index * 43) % 255)
        for index in range(32 * 32)
    ])
    image.save(image_path)

    cancelled = asyncio.Event()

    async def stalled_caption(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    processor = object.__new__(ImageModalProcessor)
    processor.modal_caption_func = stalled_caption
    processor.content_source = None
    processor._vlm_result_cache = {}
    processor.vision_embed_func = None
    monkeypatch.setattr(base, "_modal_caption_timeout_seconds", lambda: 0.01)

    description, entity = await processor.generate_description_only(
        {"img_path": str(image_path)},
        "image",
        doc_id="doc-timeout",
        file_path="timeout.docx",
    )

    assert image_path.name in description
    assert entity["entity_type"] == "image"
    assert cancelled.is_set()


def test_modal_caption_timeout_is_bounded(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_CAPTION_TIMEOUT", "999")
    assert base._modal_caption_timeout_seconds() == 300.0

    monkeypatch.setenv("MULTIMODAL_CAPTION_TIMEOUT", "not-a-number")
    assert base._modal_caption_timeout_seconds() == 90.0


@pytest.mark.asyncio
async def test_pending_vision_tasks_are_cancelled_after_timeout():
    cancelled = asyncio.Event()

    async def stalled_embedding():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    processor = object.__new__(ImageModalProcessor)
    processor._pending_vision_tasks = [asyncio.create_task(stalled_embedding())]

    completed = await processor.await_pending_vision_tasks(timeout=0.01)

    assert completed == 0
    assert cancelled.is_set()
    assert processor._pending_vision_tasks == []
