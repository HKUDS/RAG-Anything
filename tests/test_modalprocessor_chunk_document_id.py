"""Document associations must survive multimodal entity extraction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import raganything.modalprocessors as modalprocessors


class RecordingStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, data):
        self.records.update(data)

    async def get_by_id(self, record_id):
        return self.records.get(record_id)


@pytest.fixture
def processor(monkeypatch):
    text_chunks = RecordingStorage()
    chunks_vdb = RecordingStorage()
    lightrag = SimpleNamespace(
        text_chunks=text_chunks,
        chunks_vdb=chunks_vdb,
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
    return modalprocessors.BaseModalProcessor(lightrag, modal_caption_func=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("doc_id", ["doc-original", None])
@pytest.mark.parametrize("batch_mode", [True, False])
async def test_chunk_extraction_preserves_document_id(processor, doc_id, batch_mode):
    _, entity, _ = await processor._create_entity_and_chunk(
        modal_chunk="A table describing quarterly revenue.",
        entity_info={
            "entity_name": "Revenue table",
            "entity_type": "table",
            "summary": "Quarterly revenue",
        },
        file_path="report.pdf",
        batch_mode=batch_mode,
        doc_id=doc_id,
        chunk_order_index=3,
    )

    chunk_id = entity["chunk_id"]
    expected_doc_id = doc_id if doc_id else chunk_id
    stored_chunk = processor.text_chunks_db.records[chunk_id]
    assert stored_chunk["full_doc_id"] == expected_doc_id
    assert processor.chunks_vdb.records[chunk_id] == stored_chunk


@pytest.mark.asyncio
async def test_chunk_without_document_id_keeps_legacy_fallback(processor):
    chunk_id = "chunk-legacy"
    await processor.text_chunks_db.upsert(
        {
            chunk_id: {
                "content": "Legacy table description",
                "tokens": 3,
                "chunk_order_index": 0,
                "file_path": "legacy.pdf",
            }
        }
    )

    await processor._process_chunk_for_extraction(
        chunk_id, "Legacy table", batch_mode=True
    )

    assert processor.chunks_vdb.records[chunk_id]["full_doc_id"] == chunk_id
