"""Multimodal processing failures must keep the caller's 3-value contract.

``ProcessorMixin._process_multimodal_content`` unpacks three values from
``process_multimodal_content`` (``raganything/processor.py``).  When a
processor swallowed an error and returned only the fallback pair, the
unpacking raised ``ValueError: not enough values to unpack`` in the caller,
which hid the real failure and dropped the item.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import raganything.modalprocessors as modalprocessors

CONTENT_TYPES = {
    "image": modalprocessors.ImageModalProcessor,
    "table": modalprocessors.TableModalProcessor,
    "equation": modalprocessors.EquationModalProcessor,
    "generic": modalprocessors.GenericModalProcessor,
}


class FailingVectorStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, data):
        raise ConnectionError("vector store is unreachable")

    async def get_by_id(self, record_id):
        return self.records.get(record_id)


class RecordingStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, data):
        self.records.update(data)

    async def get_by_id(self, record_id):
        return self.records.get(record_id)


@pytest.fixture
def lightrag():
    return SimpleNamespace(
        text_chunks=RecordingStorage(),
        chunks_vdb=FailingVectorStorage(),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", sorted(CONTENT_TYPES))
async def test_fallback_returns_chunk_results(lightrag, content_type):
    processor_class = CONTENT_TYPES[content_type]
    processor = processor_class(lightrag, modal_caption_func=None)
    processor.generate_description_only = AsyncMock(
        return_value=(
            "A generated description.",
            {
                "entity_name": f"{content_type} entity",
                "entity_type": content_type,
                "summary": "A generated summary.",
            },
        )
    )
    modal_content = {"type": content_type, "img_path": "/tmp/missing.png"}

    summary, entity_info, chunk_results = await processor.process_multimodal_content(
        modal_content=modal_content,
        content_type=content_type,
        file_path="report.pdf",
        batch_mode=True,
        doc_id="doc-1",
        chunk_order_index=0,
    )

    assert chunk_results == []
    assert summary == str(modal_content)
    assert entity_info["entity_type"] == content_type
