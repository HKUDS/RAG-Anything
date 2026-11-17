import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from raganything.modalprocessors import ImageModalProcessor
from raganything.utils import resolve_image_path


def test_resolve_image_path_absolute(tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    # Absolute path
    assert resolve_image_path(str(img)) == img.resolve()
    assert resolve_image_path(img) == img.resolve()

    # None and empty
    assert resolve_image_path(None) is None
    assert resolve_image_path("") is None
    assert resolve_image_path("   ") is None


def test_resolve_image_path_relative_search_roots(tmp_path):
    doc_dir = tmp_path / "doc_output"
    images_dir = doc_dir / "images"
    auto_images_dir = doc_dir / "auto" / "images"
    images_dir.mkdir(parents=True)
    auto_images_dir.mkdir(parents=True)

    img1 = images_dir / "fig1.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    img2 = auto_images_dir / "fig2.jpg"
    img2.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    # Relative path matching images/fig1.png
    resolved = resolve_image_path("images/fig1.png", search_roots=[doc_dir])
    assert resolved == img1.resolve()

    # Relative path matching filename fig1.png directly
    resolved = resolve_image_path("fig1.png", search_roots=[doc_dir])
    assert resolved == img1.resolve()

    # Out-of-date path pointing to /other/host/fig2.jpg probed under auto/images/
    resolved = resolve_image_path("/other/host/fig2.jpg", search_roots=[doc_dir])
    assert resolved == img2.resolve()

    # Nonexistent file returns None
    assert resolve_image_path("nonexistent.png", search_roots=[doc_dir]) is None


def _fake_lightrag(working_dir=None):
    lr = MagicMock()
    lr.working_dir = working_dir or "/tmp/fake_lightrag"
    lr.text_chunks = MagicMock()
    lr.text_chunks.upsert = AsyncMock()
    lr.text_chunks.get_by_id = AsyncMock(
        return_value={
            "content": "test chunk content",
            "tokens": 10,
            "chunk_order_index": 0,
        }
    )
    lr.chunks_vdb = MagicMock()
    lr.chunks_vdb.upsert = AsyncMock()
    lr.entities_vdb = MagicMock()
    lr.entities_vdb.upsert = AsyncMock()
    lr.relationships_vdb = MagicMock()
    lr.relationships_vdb.upsert = AsyncMock()
    lr.chunk_entity_relation_graph = MagicMock()
    lr.chunk_entity_relation_graph.upsert_node = AsyncMock()
    lr.chunk_entity_relation_graph.upsert_edge = AsyncMock()
    lr.embedding_func = AsyncMock()
    lr.llm_model_func = AsyncMock()
    lr.llm_response_cache = MagicMock()
    mock_tok = MagicMock()
    mock_tok.encode = lambda text: [1] * max(1, len(str(text).split()))
    lr.tokenizer = mock_tok
    return lr


@pytest.mark.asyncio
async def test_image_processor_resolves_relative_path(tmp_path):
    output_dir = tmp_path / "parsed_doc"
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True)

    test_img = images_dir / "chart.png"
    test_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    called_kwargs = {}

    async def mock_vlm(prompt, image_data=None, system_prompt=None, **kwargs):
        called_kwargs["image_data"] = image_data
        called_kwargs["prompt"] = prompt
        return json.dumps(
            {
                "detailed_description": "A bar chart showing revenue growth.",
                "entity_info": {
                    "entity_name": "Revenue Chart",
                    "entity_type": "image",
                    "summary": "Revenue growth chart.",
                },
            }
        )

    processor = ImageModalProcessor(
        lightrag=_fake_lightrag(str(tmp_path)),
        modal_caption_func=mock_vlm,
    )

    modal_item = {
        "type": "image",
        "img_path": "images/chart.png",
        "image_caption": ["Q3 Revenue"],
    }

    _desc, entity_info = await processor.generate_description_only(
        modal_item,
        content_type="image",
        item_info={"output_dir": str(output_dir)},
    )

    assert "Revenue growth chart" in entity_info["summary"]
    assert called_kwargs["image_data"] != ""
    assert called_kwargs["image_data"] is not None


@pytest.mark.asyncio
async def test_image_processor_fallback_on_missing_image_with_captions(tmp_path):
    called_prompts = []

    async def mock_caption_func(prompt, system_prompt=None, **kwargs):
        called_prompts.append(prompt)
        return json.dumps(
            {
                "detailed_description": "A schematic diagram of the transformer architecture.",
                "entity_info": {
                    "entity_name": "Transformer Architecture",
                    "entity_type": "image",
                    "summary": "Schematic diagram of transformer.",
                },
            }
        )

    processor = ImageModalProcessor(
        lightrag=_fake_lightrag(str(tmp_path)),
        modal_caption_func=mock_caption_func,
    )

    # Missing image file with rich textual metadata
    modal_item = {
        "type": "image",
        "img_path": "missing_diagram.png",
        "image_caption": ["Figure 1: The Transformer model architecture."],
        "image_footnote": ["Self-attention mechanisms shown on the left."],
        "_section_path": "Model Architecture",
    }

    _desc, entity_info = await processor.generate_description_only(
        modal_item,
        content_type="image",
        item_info={"page_idx": 2},
    )

    assert "Transformer Architecture" in entity_info["entity_name"]
    assert len(called_prompts) == 1
    assert "Figure 1: The Transformer model architecture." in called_prompts[0]


@pytest.mark.asyncio
async def test_image_processor_empty_image_path_and_zero_metadata(tmp_path):
    processor = ImageModalProcessor(
        lightrag=_fake_lightrag(str(tmp_path)),
        modal_caption_func=AsyncMock(),
    )

    # Completely empty image item (decorative divider or uncaptioned figure)
    modal_item = {
        "type": "image",
        "img_path": "",
    }

    desc, entity_info = await processor.generate_description_only(
        modal_item,
        content_type="image",
        entity_name="divider_icon",
    )

    assert "divider_icon" in entity_info["entity_name"]
    assert entity_info["entity_type"] == "image"
    assert "Decorative or uncaptioned" in desc


@pytest.mark.asyncio
async def test_image_processor_process_multimodal_content_full(tmp_path):
    async def mock_caption_func(prompt, system_prompt=None, **kwargs):
        return json.dumps(
            {
                "detailed_description": "Network diagram with client and server nodes.",
                "entity_info": {
                    "entity_name": "Client Server Network",
                    "entity_type": "image",
                    "summary": "Network topology.",
                },
            }
        )

    processor = ImageModalProcessor(
        lightrag=_fake_lightrag(str(tmp_path)),
        modal_caption_func=mock_caption_func,
    )
    processor._process_chunk_for_extraction = AsyncMock(return_value=[])

    modal_item = {
        "type": "image",
        "img_path": "network.png",
        "image_caption": ["Figure 4: Client-server interaction."],
    }

    summary, entity_info, relations = await processor.process_multimodal_content(
        modal_content=modal_item,
        content_type="image",
        file_path="doc.pdf",
        batch_mode=True,
        doc_id="doc-123",
    )

    assert summary == "Network topology."
    assert "Client Server Network" in entity_info["entity_name"]
    assert isinstance(relations, list)
