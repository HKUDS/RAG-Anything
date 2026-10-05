"""Parsers that emit a plain string caption must not be split per character.

``DoclingParser`` writes ``image_caption``/``image_footnote`` as strings
(``raganything/parser.py``), while MinerU writes lists.  ``normalize_caption_list``
exists to bridge both shapes and is already used by ``TableModalProcessor`` and
``ProcessorMixin._apply_chunk_template``; the image paths had to catch up.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import raganything.modalprocessors as modalprocessors
from raganything.modalprocessors import ContextConfig, ContextExtractor


class RecordingStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, data):
        self.records.update(data)

    async def get_by_id(self, record_id):
        return self.records.get(record_id)


@pytest.fixture
def processor(monkeypatch):
    lightrag = SimpleNamespace(
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
