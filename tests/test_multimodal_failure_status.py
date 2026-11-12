"""Failed multimodal ingestion must remain visible and retryable."""

import asyncio
import atexit
import json
from unittest.mock import AsyncMock
import uuid

import numpy as np
import pytest
from lightrag.utils import EmbeddingFunc, Tokenizer

from raganything import RAGAnything, RAGAnythingConfig
from raganything.base import DocStatus
from raganything.parser import MineruParser


class ByteTokenizer:
    def encode(self, text):
        return list(text.encode("utf-8"))

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace")


async def llm(*args, **kwargs):
    return (
        json.dumps(
            {
                "detailed_description": "Recovered table description.",
                "entity_info": {
                    "entity_name": "Results",
                    "entity_type": "table",
                    "summary": "Results table.",
                },
            }
        )
        if "detailed_description" in str(args[0])
        else ""
    )


@pytest.fixture
def ingestion(monkeypatch, tmp_path):
    monkeypatch.setattr(MineruParser, "check_installation", lambda self: True)
    available = {"value": False, "fail_next": False, "reject": None}

    async def embeddings(texts):
        fail_next = available["fail_next"]
        available["fail_next"] = False
        if (
            not available["value"]
            or fail_next
            or (
                available["reject"]
                and any(available["reject"] in text for text in texts)
            )
        ):
            raise RuntimeError("embedding service unavailable")
        return np.ones((len(texts), 8), dtype=np.float32)

    rag = RAGAnything(
        config=RAGAnythingConfig(
            working_dir=str(tmp_path / "rag"),
            parser_output_dir=str(tmp_path / "out"),
            display_content_stats=False,
        ),
        llm_model_func=llm,
        embedding_func=EmbeddingFunc(
            embedding_dim=8, max_token_size=8192, func=embeddings
        ),
        lightrag_kwargs={
            "workspace": f"failure-{uuid.uuid4().hex}",
            "tokenizer": Tokenizer("bytes", ByteTokenizer()),
            "chunk_token_size": 512,
            "chunk_overlap_token_size": 16,
        },
    )
    return rag, available


async def close(rag):
    await rag.finalize_storages()
    atexit.unregister(rag.close)
    workers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_point", ["insert_content_list", "process_document_complete"]
)
async def test_failed_embedding_is_not_completed_and_can_be_retried(
    ingestion, entry_point
):
    rag, available = ingestion
    try:
        content = [{"type": "table", "table_body": "| A | B |\n|---|---|\n|1|2|"}]
        rag.parse_document = AsyncMock(return_value=(content, "doc-table"))

        async def insert():
            method = getattr(rag, entry_point)
            source = content if entry_point == "insert_content_list" else "report.pdf"
            return await method(source, doc_id="doc-table")

        with pytest.raises(RuntimeError, match="multimodal"):
            await insert()

        record = await rag.lightrag.doc_status.get_by_id("doc-table")
        assert record["status"] == DocStatus.FAILED
        assert not await rag.is_document_fully_processed("doc-table")
        assert record["chunks_list"] == []

        # Only the external embedding service recovers. The actual processors,
        # chunk/vector writes and document bookkeeping run again on retry.
        available["value"] = True
        await insert()

        assert await rag.is_document_fully_processed("doc-table")
        record = await rag.lightrag.doc_status.get_by_id("doc-table")
        chunks = await rag.lightrag.text_chunks.get_by_ids(record["chunks_list"])
        assert any(
            "Recovered table description." in chunk["content"] for chunk in chunks
        )
    finally:
        await close(rag)


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled_image", [False, True])
async def test_successful_individual_fallback_still_completes(
    ingestion, disabled_image
):
    rag, available = ingestion
    available.update(value=True, fail_next=True)
    content = [{"type": "table", "table_body": "A recovered table"}]
    if disabled_image:
        rag.config.enable_image_processing = False
        content.insert(0, {"type": "image", "img_path": "disabled.png"})
    try:
        await rag.insert_content_list(
            content,
            doc_id="doc-fallback",
        )
        assert await rag.is_document_fully_processed("doc-fallback")
        record = await rag.lightrag.doc_status.get_by_id("doc-fallback")
        assert len(record["chunks_list"]) == 1
    finally:
        await close(rag)


@pytest.mark.asyncio
@pytest.mark.parametrize("compatibility_cache", [False, True])
async def test_failed_force_reprocess_invalidates_old_completion(
    ingestion, compatibility_cache
):
    rag, available = ingestion
    available["value"] = True
    content = [{"type": "table", "table_body": "A previously completed table"}]
    try:
        assert (await rag._ensure_lightrag_initialized())["success"]
        if compatibility_cache:
            upsert = rag.lightrag.doc_status.upsert

            async def schema_compatible_upsert(data):
                if any("multimodal_processed" in record for record in data.values()):
                    raise ValueError("unsupported multimodal_processed field")
                await upsert(data)

            rag.lightrag.doc_status.upsert = schema_compatible_upsert

        await rag.insert_content_list(content, doc_id="doc-force")
        assert await rag.is_document_fully_processed("doc-force")

        available["value"] = False
        with pytest.raises(RuntimeError, match="multimodal"):
            await rag.insert_content_list(
                content, doc_id="doc-force", force_multimodal_reprocess=True
            )
        assert not await rag.is_document_fully_processed("doc-force")
        record = await rag.lightrag.doc_status.get_by_id("doc-force")
        assert record["status"] == DocStatus.FAILED
        assert not (await rag.get_document_processing_status("doc-force"))[
            "multimodal_processed"
        ]

        available["value"] = True
        # A normal retry must not trust completion from before the failed force.
        await rag.insert_content_list(content, doc_id="doc-force")
        assert await rag.is_document_fully_processed("doc-force")
        record = await rag.lightrag.doc_status.get_by_id("doc-force")
        assert record["error_msg"] == ""
    finally:
        await close(rag)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_text", [False, True])
@pytest.mark.parametrize(
    "entry_point", ["insert_content_list", "process_document_complete"]
)
async def test_partial_fallback_keeps_stored_chunks_but_does_not_complete(
    ingestion, with_text, entry_point
):
    rag, available = ingestion
    available.update(value=True, reject="UNAVAILABLE")
    content = [
        {"type": "table", "table_body": "An available table"},
        {"type": "table", "table_body": "An UNAVAILABLE table"},
    ]
    if with_text:
        content.insert(0, {"type": "text", "text": "The report text."})
    rag.parse_document = AsyncMock(return_value=(content, "doc-partial"))

    async def insert():
        method = getattr(rag, entry_point)
        source = content if entry_point == "insert_content_list" else "report.pdf"
        return await method(source, doc_id="doc-partial")

    try:
        with pytest.raises(RuntimeError, match="1/2 multimodal items"):
            await insert()

        record = await rag.lightrag.doc_status.get_by_id("doc-partial")
        assert record["status"] == DocStatus.FAILED
        assert not await rag.is_document_fully_processed("doc-partial")
        chunks = await rag.lightrag.text_chunks.get_by_ids(record["chunks_list"])
        stored_before_retry = {
            chunk_id
            for chunk_id, chunk in zip(record["chunks_list"], chunks)
            if "An available table" in chunk["content"]
        }
        assert len(stored_before_retry) == 1
        assert any("An available table" in chunk["content"] for chunk in chunks)

        available["reject"] = None
        await insert()
        assert await rag.is_document_fully_processed("doc-partial")
        record = await rag.lightrag.doc_status.get_by_id("doc-partial")
        assert stored_before_retry <= set(record["chunks_list"])
        chunks = await rag.lightrag.text_chunks.get_by_ids(record["chunks_list"])
        assert any("An available table" in chunk["content"] for chunk in chunks)
        assert any("An UNAVAILABLE table" in chunk["content"] for chunk in chunks)
    finally:
        await close(rag)
