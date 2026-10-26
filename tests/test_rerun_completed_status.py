"""Re-ingesting a fully processed document must leave it PROCESSED.

The text stage writes HANDLING (multimodal-only content gets it up front),
and the multimodal stage used to return early as "already processed"
without restoring PROCESSED, so a rerun left the document HANDLING.

These run the real LightRAG pipeline offline; only the model calls are
stubbed.
"""

import asyncio
import atexit
import json
import uuid

import numpy as np
import pytest
from lightrag.utils import EmbeddingFunc, Tokenizer
from PIL import Image

from raganything import RAGAnything, RAGAnythingConfig
from raganything.base import DocStatus
from raganything.parser import MineruParser


class _ByteTokenizer:
    def encode(self, content):
        return list(content.encode("utf-8"))

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace")


_MODAL_CALLS = []


def _modal_answer(name, kind):
    return json.dumps(
        {
            "detailed_description": f"The {kind} described.",
            "entity_info": {
                "entity_name": name,
                "entity_type": kind,
                "summary": f"A {kind}.",
            },
        }
    )


async def _llm(prompt, system_prompt=None, history_messages=None, **kwargs):
    if "detailed_description" in (prompt or ""):
        _MODAL_CALLS.append(prompt)
        return _modal_answer("Results Table", "table")
    return ""  # LightRAG entity extraction finds nothing


async def _vlm(prompt, system_prompt=None, history_messages=None, **kwargs):
    _MODAL_CALLS.append(prompt)
    return _modal_answer("Red Square Figure", "image")


async def _constant_embeddings(texts):
    return np.ones((len(texts), 8), dtype=np.float32)


@pytest.fixture
def rag(monkeypatch, tmp_path):
    monkeypatch.setattr(MineruParser, "check_installation", lambda self: True)
    _MODAL_CALLS.clear()
    config = RAGAnythingConfig(
        working_dir=str(tmp_path / "rag"),
        parser_output_dir=str(tmp_path / "out"),
        display_content_stats=False,
    )
    return RAGAnything(
        config=config,
        llm_model_func=_llm,
        vision_model_func=_vlm,
        embedding_func=EmbeddingFunc(
            embedding_dim=8, max_token_size=8192, func=_constant_embeddings
        ),
        lightrag_kwargs={
            "tokenizer": Tokenizer("bytes", _ByteTokenizer()),
            "chunk_token_size": 64,
            "chunk_overlap_token_size": 8,
            # shared storage is keyed by workspace, not working_dir
            "workspace": f"s{uuid.uuid4().hex[:8]}",
        },
    )


async def _close(rag):
    await rag.finalize_storages()
    atexit.unregister(rag.close)
    workers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


async def _assert_completed(rag, doc_id):
    record = await rag.lightrag.doc_status.get_by_id(doc_id)
    assert record["status"] == DocStatus.PROCESSED
    assert record["multimodal_processed"] is True
    assert await rag.is_document_fully_processed(doc_id)


_TABLE = {
    "type": "table",
    "table_body": "| a | b |\n|---|---|\n| 1 | 2 |",
    "table_caption": ["Table 1"],
    "page_idx": 0,
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text", "text": "Alpha findings.", "page_idx": 0}, _TABLE],
        [_TABLE],  # multimodal-only: HANDLING is written before the stage
    ],
    ids=["text-and-table", "table-only"],
)
async def test_insert_content_list_rerun_stays_processed(rag, content):
    try:
        await rag.insert_content_list(content, file_path="a.pdf", doc_id="doc-a")
        await _assert_completed(rag, "doc-a")
        calls = len(_MODAL_CALLS)

        await rag.insert_content_list(content, file_path="a.pdf", doc_id="doc-a")

        await _assert_completed(rag, "doc-a")
        assert len(_MODAL_CALLS) == calls  # completed work is not repeated
    finally:
        await _close(rag)


@pytest.mark.asyncio
async def test_batch_and_complete_rerun_of_a_file_stay_processed(rag, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    Image.new("RGB", (8, 8), "red").save(source / "fig.png")
    document = source / "report.md"
    document.write_text(
        "Gamma findings in the body.\n\n![Figure 1](fig.png)\n", encoding="utf-8"
    )
    try:
        first = await rag.process_documents_with_rag_batch(
            [str(document)], show_progress=False, incremental=False
        )
        assert first["successful_rag_files"] == 1
        _, doc_id = await rag.parse_document(str(document), display_stats=False)
        await _assert_completed(rag, doc_id)
        calls = len(_MODAL_CALLS)

        second = await rag.process_documents_with_rag_batch(
            [str(document)], show_progress=False, incremental=False
        )
        assert second["successful_rag_files"] == 1
        await _assert_completed(rag, doc_id)

        await rag.process_document_complete(str(document))
        await _assert_completed(rag, doc_id)
        assert len(_MODAL_CALLS) == calls
    finally:
        await _close(rag)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DocStatus.PENDING, DocStatus.FAILED])
async def test_skipped_stage_only_finishes_handling(rag, status):
    # Only the HANDLING the caller wrote is finished: a status LightRAG still
    # owns (queued or failed text) must not be turned into PROCESSED.
    try:
        await rag.insert_content_list([_TABLE], file_path="a.pdf", doc_id="doc-a")
        record = await rag.lightrag.doc_status.get_by_id("doc-a")
        await rag.lightrag.doc_status.upsert({"doc-a": {**record, "status": status}})

        await rag._process_multimodal_content([_TABLE], "a.pdf", "doc-a")

        record = await rag.lightrag.doc_status.get_by_id("doc-a")
        assert record["status"] == status
        assert record["multimodal_processed"] is True
    finally:
        await _close(rag)
