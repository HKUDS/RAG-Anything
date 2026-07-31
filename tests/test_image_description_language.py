import json

import pytest

from raganything.modalprocessors import image as image_module
from raganything.modalprocessors.image import ImageModalProcessor


def _write_meaningful_image(path):
    from PIL import Image

    image = Image.new("RGB", (32, 32))
    image.putdata([
        ((index * 17) % 255, (index * 29) % 255, (index * 43) % 255)
        for index in range(32 * 32)
    ])
    image.save(path)


def _processor(caption_func):
    processor = object.__new__(ImageModalProcessor)
    processor.modal_caption_func = caption_func
    processor.content_source = None
    processor._vlm_result_cache = {}
    processor.vision_embed_func = None
    return processor


@pytest.mark.asyncio
async def test_future_image_descriptions_use_chinese_and_ignore_legacy_cache(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("MULTIMODAL_PROMPT_LANGUAGE", "zh")
    monkeypatch.setenv("VISION_MODEL", "vision-model-a")
    image_path = tmp_path / "diagram.png"
    _write_meaningful_image(image_path)
    calls = []

    async def caption(prompt, **kwargs):
        calls.append((prompt, kwargs.get("system_prompt", "")))
        return json.dumps({
            "detailed_description": "这是一张机械齿轮装配结构图。",
            "entity_info": {
                "entity_name": "机械齿轮装配图",
                "entity_type": "image",
                "summary": "展示齿轮、转轴及其装配关系。",
            },
        }, ensure_ascii=False)

    processor = _processor(caption)
    image_hash = processor._get_image_content_hash(image_path)
    processor._vlm_result_cache[image_hash] = (
        "Old English description",
        {"entity_name": "Old English title", "entity_type": "image"},
    )

    description, entity = await processor.generate_description_only(
        {"img_path": str(image_path)}, "image",
    )

    assert len(calls) == 1
    assert "简体中文" in calls[0][0]
    assert "简体中文" in calls[0][1]
    assert description == "这是一张机械齿轮装配结构图。"
    assert entity["entity_name"] == "机械齿轮装配图（图片）"

    cached_description, _ = await processor.generate_description_only(
        {"img_path": str(image_path)}, "image",
    )
    assert cached_description == description
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_image_description_cache_isolated_by_prompt_context(tmp_path, monkeypatch):
    monkeypatch.setenv("MULTIMODAL_PROMPT_LANGUAGE", "zh")
    image_path = tmp_path / "chart.png"
    _write_meaningful_image(image_path)
    call_count = 0

    async def caption(_prompt, **_kwargs):
        nonlocal call_count
        call_count += 1
        return json.dumps({
            "detailed_description": f"第{call_count}次中文分析",
            "entity_info": {
                "entity_name": f"图表{call_count}",
                "entity_type": "image",
                "summary": "中文摘要",
            },
        }, ensure_ascii=False)

    processor = _processor(caption)
    first = {"img_path": str(image_path), "image_caption": ["第一张图"]}
    second = {"img_path": str(image_path), "image_caption": ["第二张图"]}

    await processor.generate_description_only(first, "image")
    await processor.generate_description_only(second, "image")
    await processor.generate_description_only(second, "image")

    assert call_count == 2


@pytest.mark.asyncio
async def test_vision_embedding_cache_includes_description_and_model(monkeypatch):
    image_module._vision_embed_cache.clear()
    embed_calls = []

    class Adapter:
        model = "vision-embedding-a"

        async def embed_image(self, _path, caption_text=""):
            embed_calls.append(caption_text)
            return [float(len(embed_calls))]

    class Repo:
        async def upsert(self, **_kwargs):
            return None

        async def flush(self):
            return None

    processor = object.__new__(ImageModalProcessor)
    processor.vision_embed_func = Adapter()
    processor.lightrag = type("LightRAG", (), {"image_vision_repo": Repo()})()

    common = {
        "image_path": "future-image.png",
        "entity_name": "机械结构图",
        "image_hash": "abc123",
    }
    await processor._compute_and_store_vision(**common, description="中文描述一")
    await processor._compute_and_store_vision(**common, description="中文描述一")
    await processor._compute_and_store_vision(**common, description="中文描述二")

    assert embed_calls == ["中文描述一", "中文描述二"]
