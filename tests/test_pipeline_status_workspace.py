"""Multimodal steps must use the pipeline status of their own LightRAG workspace.

Without an explicit workspace, LightRAG's shared storage resolves to its
process-wide default workspace (the first instance initialized), so a second
workspace's multimodal progress, cancellation and lock went to the first one.
"""

import atexit
import contextlib
import uuid

import numpy as np
import pytest
from lightrag import LightRAG
from lightrag.exceptions import PipelineCancelledException
from lightrag.kg import shared_storage
from lightrag.utils import EmbeddingFunc

from raganything import RAGAnything, RAGAnythingConfig
from raganything import modalprocessors
from raganything.parser import MineruParser


async def llm(*args, **kwargs):
    return ""


async def embed(texts):
    return np.ones((len(texts), 8), dtype=np.float32)


EMBEDDING = EmbeddingFunc(embedding_dim=8, max_token_size=8192, func=embed)

CHUNKS = {
    "chunk-mm": {
        "content": "Figure 1 shows revenue by region.",
        "tokens": 8,
        "chunk_order_index": 0,
        "full_doc_id": "doc-b",
        "file_path": "b.pdf",
    }
}


@contextlib.asynccontextmanager
async def workspaces(monkeypatch, tmp_path):
    monkeypatch.setattr(MineruParser, "check_installation", lambda self: True)
    # Make workspace A the process default, as the first LightRAG instance would.
    ws_a, ws_b = (f"ws-{label}-{uuid.uuid4().hex}" for label in "ab")
    monkeypatch.setattr(shared_storage, "_default_workspace", ws_a)

    rags = []
    for ws in (ws_a, ws_b):
        rag = LightRAG(
            working_dir=str(tmp_path / ws),
            workspace=ws,
            llm_model_func=llm,
            embedding_func=EMBEDDING,
        )
        await rag.initialize_storages()
        rags.append(rag)

    rag_b = RAGAnything(
        lightrag=rags[1],
        config=RAGAnythingConfig(
            working_dir=str(tmp_path / ws_b),
            parser_output_dir=str(tmp_path / "out"),
        ),
        llm_model_func=llm,
        vision_model_func=llm,
        embedding_func=EMBEDDING,
    )
    assert (await rag_b._ensure_lightrag_initialized())["success"]

    status_a = await shared_storage.get_namespace_data(
        "pipeline_status", workspace=ws_a
    )
    status_b = await shared_storage.get_namespace_data(
        "pipeline_status", workspace=ws_b
    )
    for status in (status_a, status_b):
        status["history_messages"].clear()
        status["cancellation_requested"] = False

    try:
        yield rag_b, status_a, status_b
    finally:
        atexit.unregister(rag_b.close)
        for rag in rags:
            await rag.finalize_storages()


@pytest.mark.asyncio
async def test_progress_goes_to_own_workspace(monkeypatch, tmp_path):
    async with workspaces(monkeypatch, tmp_path) as (rag_b, status_a, status_b):
        await rag_b._batch_extract_entities_lightrag_style_type_aware(CHUNKS)

    assert list(status_a["history_messages"]) == []
    assert any("chunk-mm" in msg for msg in status_b["history_messages"])


@pytest.mark.asyncio
async def test_cancellation_follows_own_workspace(monkeypatch, tmp_path):
    async with workspaces(monkeypatch, tmp_path) as (rag_b, status_a, status_b):
        status_a["cancellation_requested"] = True
        await rag_b._batch_extract_entities_lightrag_style_type_aware(CHUNKS)

        status_a["cancellation_requested"] = False
        status_b["cancellation_requested"] = True
        with pytest.raises(PipelineCancelledException):
            await rag_b._batch_extract_entities_lightrag_style_type_aware(CHUNKS)


@pytest.mark.asyncio
async def test_modal_processor_uses_own_workspace(monkeypatch, tmp_path):
    seen = {}

    async def capture(*args, pipeline_status=None, **kwargs):
        seen["status"] = pipeline_status
        return []

    monkeypatch.setattr(modalprocessors, "extract_entities", capture)
    async with workspaces(monkeypatch, tmp_path) as (rag_b, status_a, status_b):
        processor = modalprocessors.BaseModalProcessor(
            rag_b.lightrag, modal_caption_func=llm
        )
        await rag_b.lightrag.text_chunks.upsert(CHUNKS)
        await processor._process_chunk_for_extraction("chunk-mm", "Figure 1")

    assert seen["status"] is status_b
