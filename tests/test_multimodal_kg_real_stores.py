import atexit
import json
import tempfile
import pytest
from datetime import datetime, timezone
import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc, Tokenizer
from lightrag.kg.shared_storage import initialize_pipeline_status
from raganything import RAGAnything
from raganything.config import RAGAnythingConfig


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
