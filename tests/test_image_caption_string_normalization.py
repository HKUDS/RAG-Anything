"""Parsers that emit a plain string caption must not be split per character.

``DoclingParser`` writes ``image_caption``/``image_footnote`` as strings
(``raganything/parser.py``), while MinerU writes lists.  ``normalize_caption_list``
exists to bridge both shapes and is already used by ``TableModalProcessor`` and
``ProcessorMixin._apply_chunk_template``; the image paths had to catch up.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

import raganything.modalprocessors as modalprocessors
from raganything.modalprocessors import ContextConfig, ContextExtractor


class RecordingStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, data):
        self.records.update(data)

    async def get_by_id(self, record_id):
        return self.records.get(record_id)


def _fake_lightrag():
    return SimpleNamespace(
        text_chunks=RecordingStorage(),
        chunks_vdb=RecordingStorage(),
        entities_vdb=RecordingStorage(),
        relationships_vdb=RecordingStorage(),
        chunk_entity_relation_graph=SimpleNamespace(upsert_node=AsyncMock()),
        embedding_func=None,
        llm_model_func=None,
        llm_response_cache=None,
        tokenizer=SimpleNamespace(encode=list),
        full_entities=None,
        full_relations=None,
        entity_chunks=None,
        relation_chunks=None,
        _build_global_config=lambda: {},
        _insert_done=AsyncMock(),
    )


@pytest.fixture
def processor(monkeypatch):
    lightrag = _fake_lightrag()
    monkeypatch.setattr(modalprocessors, "extract_entities", AsyncMock(return_value=[]))
    monkeypatch.setattr(modalprocessors, "merge_nodes_and_edges", AsyncMock())
    monkeypatch.setattr(
        modalprocessors, "get_namespace_data", AsyncMock(return_value={})
    )
    monkeypatch.setattr(modalprocessors, "get_pipeline_status_lock", lambda: None)
    instance = modalprocessors.ImageModalProcessor(lightrag, modal_caption_func=None)
    instance.generate_description_only = AsyncMock(
        return_value=(
            "An ablation curve.",
            {
                "entity_name": "image entity",
                "entity_type": "image",
                "summary": "Ablation curve",
            },
        )
    )
    return instance


@pytest.mark.asyncio
async def test_string_captions_are_not_joined_per_character(processor):
    await processor.process_multimodal_content(
        modal_content={
            "type": "image",
            "img_path": "/tmp/ablation.png",
            "image_caption": "Figure 3.1 ablation curve",
            "image_footnote": "Ablation over retrieval depth",
        },
        content_type="image",
        file_path="report.pdf",
        batch_mode=True,
        doc_id="doc-1",
    )

    assert len(processor.text_chunks_db.records) == 1
    stored_chunk = next(iter(processor.text_chunks_db.records.values()))["content"]

    assert "Captions: Figure 3.1 ablation curve" in stored_chunk
    assert "Footnotes: Ablation over retrieval depth" in stored_chunk
    assert "F, i, g, u, r, e" not in stored_chunk


@pytest.mark.asyncio
async def test_list_captions_keep_working(processor):
    await processor.process_multimodal_content(
        modal_content={
            "type": "image",
            "img_path": "/tmp/ablation.png",
            "img_caption": ["First caption", "Second caption"],
        },
        content_type="image",
        file_path="report.pdf",
        batch_mode=True,
        doc_id="doc-1",
    )

    stored_chunk = next(iter(processor.text_chunks_db.records.values()))["content"]

    assert "Captions: First caption, Second caption" in stored_chunk
    assert "Footnotes: None" in stored_chunk


def test_context_extractor_string_caption_is_not_joined_per_character():
    extractor = ContextExtractor(config=ContextConfig())

    assert (
        extractor._extract_text_from_item(
            {"type": "image", "image_caption": "Figure 3.1 ablation curve"}
        )
        == "[Image: Figure 3.1 ablation curve]"
    )
    assert (
        extractor._extract_text_from_item(
            {"type": "table", "table_caption": "Performance table"}
        )
        == "[Table: Performance table]"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_context", [False, True])
@pytest.mark.parametrize(
    "captions,footnotes,expected_captions,expected_footnotes",
    [
        (["Figure 1", None, " "], [], "Figure 1", "None"),
        (["First", "Second"], ["Note a", "Note b"], "First, Second", "Note a, Note b"),
        (
            "Figure 3.1 ablation curve",
            "Synthetic",
            "Figure 3.1 ablation curve",
            "Synthetic",
        ),
        (None, None, "None", "None"),
    ],
)
async def test_vision_prompt_gets_joined_captions(
    tmp_path,
    captions,
    footnotes,
    expected_captions,
    expected_footnotes,
    with_context,
):
    image_path = tmp_path / "figure.png"
    Image.new("RGB", (4, 4), "red").save(image_path)
    prompts = []

    async def vlm(prompt, image_data=None, system_prompt=None, **kwargs):
        prompts.append(prompt)
        return json.dumps(
            {
                "detailed_description": "A red square.",
                "entity_info": {
                    "entity_name": "Red Square",
                    "entity_type": "image",
                    "summary": "A red square.",
                },
            }
        )

    instance = modalprocessors.ImageModalProcessor(
        _fake_lightrag(), modal_caption_func=vlm
    )
    if with_context:
        instance._get_context_for_item = lambda item_info: "Surrounding text."

    await instance.generate_description_only(
        {
            "type": "image",
            "img_path": str(image_path),
            "image_caption": captions,
            "image_footnote": footnotes,
        },
        "image",
        item_info={"page_idx": 0, "index": 0, "type": "image"},
    )

    (prompt,) = prompts
    assert ("Surrounding text." in prompt) is with_context
    assert f"- Captions: {expected_captions}\n" in prompt
    assert f"- Footnotes: {expected_footnotes}\n" in prompt
    assert "['" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("with_context", [False, True])
@pytest.mark.parametrize(
    "captions,footnotes,expected_captions,expected_footnotes",
    [
        (["Table 1"], ["Note"], "Table 1", "Note"),
        (["First", "Second"], ["Note a", "Note b"], "First, Second", "Note a, Note b"),
        ("Performance table", "Synthetic", "Performance table", "Synthetic"),
        (None, None, "None", "None"),
    ],
)
async def test_table_prompt_gets_joined_captions(
    captions,
    footnotes,
    expected_captions,
    expected_footnotes,
    with_context,
):
    prompts = []

    async def llm(prompt, system_prompt=None, **kwargs):
        prompts.append(prompt)
        return json.dumps(
            {
                "detailed_description": "A one-column table.",
                "entity_info": {
                    "entity_name": "Table One",
                    "entity_type": "table",
                    "summary": "A one-column table.",
                },
            }
        )

    instance = modalprocessors.TableModalProcessor(
        _fake_lightrag(), modal_caption_func=llm
    )
    if with_context:
        instance._get_context_for_item = lambda item_info: "Surrounding text."

    await instance.generate_description_only(
        {
            "type": "table",
            "table_body": "|a|\n|-|\n|1|",
            "table_caption": captions,
            "table_footnote": footnotes,
        },
        "table",
        item_info={"page_idx": 0, "index": 0, "type": "table"},
    )

    (prompt,) = prompts
    assert ("Surrounding text." in prompt) is with_context
    assert f"Caption: {expected_captions}\n" in prompt
    assert f"Footnotes: {expected_footnotes}\n" in prompt
    assert "['" not in prompt
