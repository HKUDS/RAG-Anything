"""Rendered MinerU charts must reach the VLM without changing document IDs."""

import base64
import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from raganything.modalprocessors import ImageModalProcessor
from raganything.processor import ProcessorMixin
from raganything.query import QueryMixin
from raganything.utils import get_processor_for_type, separate_content


@pytest.fixture
def chart(tmp_path):
    path = tmp_path / "revenue.png"
    Image.new("RGB", (4, 4), "blue").save(path)
    return {
        "type": "chart",
        "img_path": str(path),
        "chart_caption": ["Quarterly revenue"],
        "chart_footnote": ["USD millions"],
        "content": "Q1 20; Q2 35",
        "page_idx": 2,
        "bbox": [10, 20, 100, 200],
        "_mineru_v2_type": "chart",
    }


@pytest.fixture
def image_processor():
    calls = []

    async def vlm(prompt, image_data=None, **kwargs):
        calls.append((prompt, image_data))
        return json.dumps(
            {
                "detailed_description": "Revenue rose from 20 to 35 million.",
                "entity_info": {
                    "entity_name": "Quarterly revenue",
                    "entity_type": "image",
                    "summary": "Q1 20; Q2 35",
                },
            }
        )

    rag = SimpleNamespace(
        text_chunks=None,
        chunks_vdb=None,
        entities_vdb=None,
        relationships_vdb=None,
        chunk_entity_relation_graph=None,
        embedding_func=None,
        llm_model_func=None,
        llm_response_cache=None,
        tokenizer=None,
        _build_global_config=lambda: {},
    )
    return ImageModalProcessor(rag, vlm), calls


def test_chart_normalization_preserves_source_and_document_id(chart):
    source = [{"type": "text", "text": "Report", "text_level": 1}, chart]
    before = copy.deepcopy(source)
    doc_id = ProcessorMixin()._generate_content_based_doc_id(source)

    _, [image] = separate_content(source)

    assert source == before
    assert ProcessorMixin()._generate_content_based_doc_id(source) == doc_id
    assert image["type"] == "image"
    assert image["_mineru_v2_type"] == "chart"
    assert image["image_caption"] == ["Quarterly revenue", "Q1 20; Q2 35"]
    assert image["image_footnote"] == ["USD millions"]
    assert image["page_idx"] == 2
    assert image["bbox"] == chart["bbox"]
    assert image["_section_path"] == "Report"


@pytest.mark.asyncio
async def test_chart_reaches_image_model_and_chunk_template(chart, image_processor):
    processor, calls = image_processor
    _, [item] = separate_content([chart])
    selected = get_processor_for_type({"image": processor}, item["type"])
    sections = await selected.generate_chunk_sections(item, item["type"])
    chunk = ProcessorMixin()._apply_chunk_template(
        item["type"], item, sections[0]["description"]
    )

    assert len(calls) == 1
    prompt, encoded = calls[0]
    assert base64.b64decode(encoded) == Path(chart["img_path"]).read_bytes()
    assert "Quarterly revenue" in prompt
    assert "Q1 20; Q2 35" in prompt
    assert "USD millions" in prompt
    assert "Revenue rose from 20 to 35 million." in chunk
    assert chart["img_path"] in chunk
    assert "Q1 20; Q2 35" in chunk


@pytest.mark.asyncio
async def test_chart_query_uses_the_image_path(chart, image_processor):
    processor, calls = image_processor
    query = QueryMixin()
    query.logger = logging.getLogger(__name__)
    query.modal_processors = {"image": processor}
    before = copy.deepcopy(chart)

    answer = await query._process_multimodal_query_content(
        "How much was Q2 revenue?", [chart]
    )

    assert len(calls) == 1
    assert calls[0][1]
    assert "35" in answer
    assert chart == before


def test_text_only_chart_keeps_generic_processing():
    chart = {"type": "chart", "content": "Revenue: 20, 35", "page_idx": 0}
    _, [item] = separate_content([chart])
    generic = object()
    assert item["type"] == "chart"
    assert item["content"] == chart["content"]
    assert get_processor_for_type({"generic": generic}, item["type"]) is generic


@pytest.mark.asyncio
async def test_chart_does_not_bypass_image_validation(chart, image_processor, tmp_path):
    processor, calls = image_processor
    non_image = tmp_path / "not-an-image.png"
    non_image.write_text("ordinary text disguised as a chart")
    chart["img_path"] = str(non_image)
    _, [item] = separate_content([chart])

    await processor.generate_description_only(item, item["type"])

    assert calls == []
