"""page_idx on text chunks through the real LightRAG ingestion pipeline (#330).

Unlike tests/test_text_chunk_page_idx.py, nothing here fakes LightRAG: real
storages, sanitize_text_for_encoding, chunking_by_token_size and the busy
pipeline queue. Only the model calls are stubbed (the LLM extracts nothing,
embeddings are constant), plus a UTF-8 byte tokenizer that decodes with
errors="replace" — the same U+FFFD-at-slice-edge behaviour as tiktoken — so
the suite needs no network.
"""

import asyncio
import atexit
import json
import uuid
from pathlib import Path

import numpy as np
import pytest
from lightrag.utils import EmbeddingFunc, Tokenizer

from raganything import RAGAnything, RAGAnythingConfig
from raganything.parser import MineruParser

MARKERS = ["PAGE-ZERO", "PAGE-ONE", "PAGE-TWO", "PAGE-THREE"]
FOOTER = "Confidential &amp; internal - do not distribute."


class _ByteTokenizer:
    def encode(self, content):
        return list(content.encode("utf-8"))

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace")


async def _no_entities(prompt, system_prompt=None, history_messages=None, **kwargs):
    return ""


async def _constant_embeddings(texts):
    return np.ones((len(texts), 8), dtype=np.float32)


def _content_list(marker_prefix="PAGE"):
    # A NUL and an HTML entity make LightRAG's sanitized text differ from the
    # raw text; CJK makes byte-sliced chunks start/end on U+FFFD; the footer
    # repeats on every page.
    bodies = [
        "-ZERO intro. The\x00 Meridian survey began in Reykjavik.",
        "-ONE 数据经过归一化后由分析引擎进行异常检测。 Results &amp; methods.",
        "-TWO the vent field named Ember Garden hosted shrimp colonies.",
        "-THREE the expedition returned with six terabytes of data.",
    ]
    items = []
    for page, body in enumerate(bodies):
        items.append({"type": "text", "text": marker_prefix + body, "page_idx": page})
        items.append({"type": "text", "text": FOOTER, "page_idx": page})
    return items


@pytest.fixture
def make_rag(monkeypatch, tmp_path):
    # insert_content_list never runs MinerU; only the init-time check would.
    monkeypatch.setattr(MineruParser, "check_installation", lambda self: True)

    def build():
        config = RAGAnythingConfig(
            working_dir=str(tmp_path / uuid.uuid4().hex), display_content_stats=False
        )
        return RAGAnything(
            config=config,
            llm_model_func=_no_entities,
            embedding_func=EmbeddingFunc(
                embedding_dim=8, max_token_size=8192, func=_constant_embeddings
            ),
            lightrag_kwargs={
                "tokenizer": Tokenizer("bytes", _ByteTokenizer()),
                "chunk_token_size": 48,
                "chunk_overlap_token_size": 8,
                # shared storage is keyed by workspace, not working_dir
                "workspace": f"t{uuid.uuid4().hex[:8]}",
            },
        )

    return build


async def _close(rag):
    # Finalize inside the test's event loop; otherwise RAGAnything's atexit
    # hook tries again after pytest has closed the loop and log streams.
    await rag.finalize_storages()
    atexit.unregister(rag.close)
    # LightRAG's rate-limit workers wait on queues forever; cancel them while
    # the loop is still open.
    workers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


def _chunks(rag, doc_id):
    path = next(Path(rag.config.working_dir).glob("**/kv_store_text_chunks.json"))
    rows = json.loads(path.read_text(encoding="utf-8")).values()
    return [row for row in rows if row.get("full_doc_id") == doc_id]


def _assert_pages_cover_markers(chunks, markers):
    assert chunks, "expected text chunks"
    for chunk in chunks:
        assert "page_idx" in chunk, f"chunk not annotated: {chunk['content']!r}"
        low = chunk["page_idx"]
        high = chunk.get("page_idx_end", low)
        for page, marker in enumerate(markers):
            if marker in chunk["content"]:
                assert low <= page <= high, (marker, low, high, chunk["content"])


@pytest.mark.asyncio
async def test_real_pipeline_annotates_every_text_chunk(make_rag):
    rag = make_rag()
    try:
        await rag.insert_content_list(
            _content_list(), file_path="survey.pdf", doc_id="doc-survey"
        )
    finally:
        await _close(rag)

    chunks = _chunks(rag, "doc-survey")
    assert len(chunks) > 4
    assert any("�" in c["content"] for c in chunks), "expected split CJK"
    _assert_pages_cover_markers(chunks, MARKERS)


@pytest.mark.asyncio
async def test_real_pipeline_annotates_documents_queued_behind_a_busy_pipeline(
    make_rag,
):
    """Concurrent inserts: LightRAG queues the second document and chunks it
    in the first caller's pipeline run, after the second ainsert returned."""
    rag = make_rag()
    try:
        await asyncio.gather(
            rag.insert_content_list(
                _content_list("PAGE"), file_path="a.pdf", doc_id="doc-a"
            ),
            rag.insert_content_list(
                _content_list("SHEET"), file_path="b.pdf", doc_id="doc-b"
            ),
        )
    finally:
        await _close(rag)

    _assert_pages_cover_markers(_chunks(rag, "doc-a"), MARKERS)
    _assert_pages_cover_markers(
        _chunks(rag, "doc-b"), [m.replace("PAGE", "SHEET") for m in MARKERS]
    )
