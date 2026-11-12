import atexit
import json
import tempfile
import pytest
from datetime import datetime, timezone
import numpy as np
import asyncio
import uuid
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc, Tokenizer
from lightrag.kg.shared_storage import initialize_pipeline_status
from raganything import RAGAnything
from raganything.config import RAGAnythingConfig
from raganything.parser import MineruParser


@pytest.fixture
def frontdoor_rag(tmp_path, monkeypatch):
    monkeypatch.setattr(MineruParser, "check_installation", lambda self: True)
    return RAGAnything(
        config=RAGAnythingConfig(
            working_dir=str(tmp_path / "rag"),
            parser_output_dir=str(tmp_path / "output"),
            display_content_stats=False,
        ),
        llm_model_func=llm,
        embedding_func=EmbeddingFunc(embedding_dim=8, max_token_size=8192, func=embed),
        lightrag_kwargs={
            "workspace": f"frontdoor-{uuid.uuid4().hex}",
            "tokenizer": Tokenizer("synthetic", Codec()),
            "entity_extract_max_gleaning": 0,
        },
    )


async def close_frontdoor(rag):
    await rag.finalize_storages()
    atexit.unregister(rag.close)
    workers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


TABLE = {
    "type": "table",
    "table_body": "Company | Sales\nACME | 10",
    "table_caption": ["Sales"],
    "page_idx": 0,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "packed", "per_item", "skip"])
async def test_public_insertion_tracks_and_deletes_all_mode_chunks(frontdoor_rag, mode):
    rag = frontdoor_rag
    rag.config.multimodal_kg_extraction_mode = mode
    try:
        await rag.insert_content_list(
            [TABLE], file_path="sales.pdf", doc_id="doc-sales"
        )
        assert await rag.is_document_fully_processed("doc-sales")
        status = await rag.lightrag.doc_status.get_by_id("doc-sales")
        ids = status["chunks_list"]
        chunks = await rag.lightrag.text_chunks.get_by_ids(ids)
        assert ids and all(chunks)
        assert any(c.get("is_multimodal_extraction_pack") for c in chunks) == (
            mode == "packed"
        )
        node = await rag.lightrag.chunk_entity_relation_graph.get_node("ACME")
        if mode == "skip":
            assert node is None
        else:
            assert node
            assert set(node["source_id"].split("<SEP>")).issubset(ids)
        result = await rag.lightrag.adelete_by_doc_id("doc-sales")
        assert result.status == "success"
        assert not any(await rag.lightrag.text_chunks.get_by_ids(ids))
    finally:
        await close_frontdoor(rag)


@pytest.mark.asyncio
async def test_packed_batch_failure_keeps_pack_chunks_tracked_for_deletion(
    frontdoor_rag, monkeypatch
):
    rag = frontdoor_rag
    rag.config.multimodal_kg_extraction_mode = "packed"
    packs = []

    async def fail_batch_extract(chunks):
        packs.extend(chunks)
        assert all(await rag.lightrag.text_chunks.get_by_ids(packs))
        raise RuntimeError("batch extraction temporarily unavailable")

    monkeypatch.setattr(
        rag, "_batch_extract_entities_lightrag_style_type_aware", fail_batch_extract
    )
    try:
        await rag.insert_content_list(
            [TABLE], file_path="sales.pdf", doc_id="doc-sales"
        )
        assert await rag.is_document_fully_processed("doc-sales")
        status = await rag.lightrag.doc_status.get_by_id("doc-sales")
        assert packs and set(packs).issubset(status["chunks_list"])
        deleted = await rag.lightrag.adelete_by_doc_id("doc-sales")
        assert deleted.status == "success"
        assert not any(await rag.lightrag.text_chunks.get_by_ids(packs))
    finally:
        await close_frontdoor(rag)


class Codec:
    def encode(self, text):
        return list(text.encode())

    def decode(self, tokens):
        return bytes(tokens).decode(errors="replace")


async def embed(texts):
    return np.ones((len(texts), 8), dtype=np.float32)


async def llm(prompt, system_prompt=None, **kwargs):
    if "high_level_keywords" in prompt or kwargs.get("keyword_extraction"):
        return '{"high_level_keywords": ["sales"], "low_level_keywords": ["ACME"]}'
    if "entity_info" in prompt:
        return json.dumps(
            {
                "detailed_description": "ACME sells widgets. Sales are 10.",
                "entity_info": {
                    "entity_name": "Sales",
                    "entity_type": "table",
                    "summary": "ACME sales table",
                },
            }
        )
    return "entity<|#|>ACME<|#|>organization<|#|>ACME sells widgets.\n<|COMPLETE|>"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("mode", ["legacy", "packed", "per_item"])
async def test_multimodal_graph_sources_resolve_and_delete(mode):
    with tempfile.TemporaryDirectory() as directory:
        lr = LightRAG(
            working_dir=directory,
            workspace=f"test-{mode}",
            embedding_func=EmbeddingFunc(
                embedding_dim=8, max_token_size=8192, func=embed
            ),
            llm_model_func=llm,
            entity_extract_max_gleaning=0,
            tokenizer=Tokenizer("synthetic", Codec()),
        )
        await lr.initialize_storages()
        await initialize_pipeline_status()
        rag = RAGAnything(
            lightrag=lr,
            llm_model_func=llm,
            config=RAGAnythingConfig(
                working_dir=directory, multimodal_kg_extraction_mode=mode
            ),
        )
        atexit.unregister(rag.close)
        rag._initialize_processors()
        doc = "synthetic-doc"
        stamp = datetime.now(timezone.utc).isoformat()
        await lr.full_docs.upsert(
            {doc: {"content": "ACME sales", "file_path": "synthetic.txt"}}
        )
        await lr.doc_status.upsert(
            {
                doc: {
                    "status": "processed",
                    "content_summary": "ACME sales",
                    "content_length": 10,
                    "chunks_count": 0,
                    "chunks_list": [],
                    "created_at": stamp,
                    "updated_at": stamp,
                    "file_path": "synthetic.txt",
                }
            }
        )
        await rag._process_multimodal_content_batch_type_aware(
            [
                {
                    "type": "table",
                    "table_body": "Company | Sales\nACME | 10",
                    "table_caption": ["Sales"],
                    "page_idx": 0,
                }
            ],
            "synthetic.txt",
            doc,
        )
        node = await lr.chunk_entity_relation_graph.get_node("ACME")
        status = await lr.doc_status.get_by_id(doc)
        assert node, "No ACME node produced"
        ids = node["source_id"].split("<SEP>")
        resolved = [await lr.text_chunks.get_by_id(cid) for cid in ids]
        assert all(resolved)
        assert set(ids).issubset(status["chunks_list"])
        if mode == "legacy":
            assert await lr.chunk_entity_relation_graph.has_edge(
                "ACME", "Sales (table)"
            )
        query = await lr.aquery_data(
            "ACME",
            QueryParam(
                mode="local",
                hl_keywords=["sales"],
                ll_keywords=["ACME"],
                enable_rerank=False,
            ),
        )
        assert query["status"] == "success"
        retrieved = {chunk["chunk_id"] for chunk in query["data"]["chunks"]}
        assert set(ids).issubset(retrieved)
        deleted = await lr.adelete_by_doc_id(doc)
        assert deleted.status == "success"
        assert await lr.chunk_entity_relation_graph.get_node("ACME") is None
        assert not any(await lr.text_chunks.get_by_ids(ids))
        await lr.finalize_storages()
