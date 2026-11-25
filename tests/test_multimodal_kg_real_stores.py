import atexit
import json
import tempfile
import pytest
from datetime import datetime, timezone
import numpy as np
import asyncio
import uuid
from lightrag import LightRAG, QueryParam, operate
from lightrag.utils import EmbeddingFunc, Tokenizer
from lightrag.kg.shared_storage import initialize_pipeline_status
from raganything import RAGAnything, modalprocessors
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
        assert (
            "Sales (table)"
            in (await rag.lightrag.full_entities.get_by_id("doc-sales"))["entity_names"]
        )
        result = await rag.lightrag.adelete_by_doc_id("doc-sales")
        assert result.status == "success"
        assert not await rag.lightrag.chunk_entity_relation_graph.has_node(
            "Sales (table)"
        )
        assert not any(await rag.lightrag.text_chunks.get_by_ids(ids))
    finally:
        await close_frontdoor(rag)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "fail_batch", "expected_extract_calls"),
    [
        pytest.param("skip", False, 0, id="skip-batch"),
        pytest.param("skip", True, 0, id="skip-fallback"),
        pytest.param(" SKIP ", True, 0, id="normalized-skip-fallback"),
        pytest.param("legacy", True, 1, id="legacy-fallback"),
    ],
)
async def test_individual_fallback_respects_kg_extraction_mode(
    frontdoor_rag, monkeypatch, mode, fail_batch, expected_extract_calls
):
    rag = frontdoor_rag
    rag.config.multimodal_kg_extraction_mode = mode
    extraction_calls = []
    extract = operate.extract_entities

    async def record_extract(*args, **kwargs):
        extraction_calls.append(True)
        return await extract(*args, **kwargs)

    monkeypatch.setattr(operate, "extract_entities", record_extract)
    monkeypatch.setattr(modalprocessors, "extract_entities", record_extract)
    if fail_batch:

        async def fail_batch_storage(chunks):
            raise RuntimeError("simulated transient batch-storage failure")

        monkeypatch.setattr(
            rag, "_store_chunks_to_lightrag_storage_type_aware", fail_batch_storage
        )

    try:
        doc_id = "doc-sales"
        await rag.insert_content_list([TABLE], file_path="sales.pdf", doc_id=doc_id)
        assert await rag.is_document_fully_processed(doc_id)

        lr = rag.lightrag
        status = await lr.doc_status.get_by_id(doc_id)
        (chunk_id,) = status["chunks_list"]
        chunk = await lr.text_chunks.get_by_id(chunk_id)
        assert chunk["full_doc_id"] == doc_id
        assert "ACME | 10" in chunk["content"]
        assert await lr.chunks_vdb.get_by_id(chunk_id)

        caption = await lr.chunk_entity_relation_graph.get_node("Sales (table)")
        assert caption["source_id"] == chunk_id
        entities = await lr.full_entities.get_by_id(doc_id)
        assert "Sales (table)" in entities["entity_names"]

        acme = await lr.chunk_entity_relation_graph.get_node("ACME")
        assert len(extraction_calls) == expected_extract_calls, (
            f"{mode!r} made {len(extraction_calls)} extraction calls, "
            f"ACME node present: {acme is not None}"
        )
        assert (acme is not None) == bool(expected_extract_calls)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "packed", "per_item", "skip"])
@pytest.mark.parametrize("first", ["a", "b"])
@pytest.mark.parametrize("identical", [False, True])
async def test_deleting_one_owner_keeps_shared_modal_entity(
    frontdoor_rag, mode, first, identical
):
    rag = frontdoor_rag
    rag.config.multimodal_kg_extraction_mode = mode
    try:
        ids = {}
        for doc, amount in [("a", 10), ("b", 10 if identical else 42)]:
            await rag.insert_content_list(
                [{**TABLE, "table_body": f"Company | Sales\\nACME | {amount}"}],
                file_path=f"{doc}.pdf",
                doc_id=doc,
            )
            ids[doc] = (await rag.lightrag.doc_status.get_by_id(doc))["chunks_list"]

        assert set(ids["a"]).isdisjoint(ids["b"])
        other = "b" if first == "a" else "a"
        graph = rag.lightrag.chunk_entity_relation_graph
        assert (await rag.adelete_by_doc_id(first))["status"] == "success"
        node = await graph.get_node("Sales (table)")
        assert node and set(node["source_id"].split("<SEP>")) <= set(ids[other])
        assert node["file_path"] == f"{other}.pdf"
        from lightrag.utils import compute_mdhash_id

        entity_id = compute_mdhash_id("Sales (table)", prefix="ent-")
        vector = await rag.lightrag.entities_vdb.get_by_id(entity_id)
        assert vector["file_path"] == f"{other}.pdf"
        assert set(vector["source_id"].split("<SEP>")) <= set(ids[other])
        assert all(await rag.lightrag.text_chunks.get_by_ids(ids[other]))
        assert (
            "Sales (table)"
            in (await rag.lightrag.full_entities.get_by_id(other))["entity_names"]
        )
        result = await rag.lightrag.aquery_data(
            "sales",
            QueryParam(
                mode="local",
                ll_keywords=["Sales (table)"],
                hl_keywords=["sales"],
                enable_rerank=False,
            ),
        )
        assert any(
            row["file_path"] == f"{other}.pdf" for row in result["data"]["chunks"]
        )
        assert (await rag.adelete_by_doc_id(other))["status"] == "success"
        assert not await graph.has_node("Sales (table)")
        assert await rag.lightrag.entities_vdb.get_by_id(entity_id) is None
    finally:
        await close_frontdoor(rag)


@pytest.mark.asyncio
async def test_retry_shared_caption_refresh_after_core_deletion(
    frontdoor_rag, monkeypatch
):
    from raganything import processor_deletion

    rag = frontdoor_rag
    rag.config.multimodal_kg_extraction_mode = "skip"
    try:
        for doc in ("a", "b"):
            await rag.insert_content_list([TABLE], file_path=f"{doc}.pdf", doc_id=doc)
        real_refresh = processor_deletion.refresh_surviving_captions

        async def fail_refresh(*args):
            raise RuntimeError("vector store offline")

        with monkeypatch.context() as patch:
            patch.setattr(
                processor_deletion, "refresh_surviving_captions", fail_refresh
            )
            failed = await rag.adelete_by_doc_id("b")
        assert failed["status"] == "failed"
        assert await rag.lightrag.doc_status.get_by_id("b") is None
        assert (await rag.multimodal_status_cache.get_by_id("b"))[
            "pending_caption_refresh"
        ] == ["Sales (table)"]
        assert processor_deletion.refresh_surviving_captions is real_refresh
        assert (await rag.adelete_by_doc_id("b"))["status"] == "success"
        assert await rag.multimodal_status_cache.get_by_id("b") is None
        node = await rag.lightrag.chunk_entity_relation_graph.get_node("Sales (table)")
        assert node["file_path"] == "a.pdf"
    finally:
        await close_frontdoor(rag)


@pytest.mark.asyncio
@pytest.mark.parametrize("same_legacy_id", [False, True])
async def test_legacy_caption_without_document_or_reverse_index(
    frontdoor_rag, same_legacy_id
):
    rag = frontdoor_rag
    rag.config.multimodal_kg_extraction_mode = "skip"
    try:
        legacy_ids = {}
        for doc in ("a", "b"):
            await rag.insert_content_list([TABLE], doc_id=doc, file_path=f"{doc}.pdf")
            status = await rag.lightrag.doc_status.get_by_id(doc)
            (key,) = status["chunks_list"]
            chunk = await rag.lightrag.text_chunks.get_by_id(key)
            chunk.pop("modal_entity_summary")
            chunk.pop("modal_entity_type")
            await rag.lightrag.text_chunks.upsert({key: chunk})
            legacy_ids[doc] = key
            await rag.lightrag.full_entities.delete([doc])

        if same_legacy_id:
            status["chunks_list"] = [legacy_ids["a"]]
            await rag.lightrag.doc_status.upsert({"b": status})
        await rag.lightrag.entity_chunks.delete(["Sales (table)"])
        result = await rag.adelete_by_doc_id("a")
        if same_legacy_id:
            assert result["status"] == "failed"
            assert "share chunk IDs" in result["message"]
            assert await rag.lightrag.doc_status.get_by_id("a")
            assert await rag.lightrag.doc_status.get_by_id("b")
            assert await rag.lightrag.text_chunks.get_by_id(legacy_ids["a"])
        else:
            assert result["status"] == "success"
            node = await rag.lightrag.chunk_entity_relation_graph.get_node(
                "Sales (table)"
            )
            assert node["source_id"] == legacy_ids["b"]
            assert node["file_path"] == "b.pdf"
            assert (await rag.adelete_by_doc_id("b"))["status"] == "success"
            assert not await rag.lightrag.chunk_entity_relation_graph.has_node(
                "Sales (table)"
            )
    finally:
        await close_frontdoor(rag)
