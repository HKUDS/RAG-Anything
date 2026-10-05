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


_LLM = {"fail": False}


async def _no_entities(prompt, system_prompt=None, history_messages=None, **kwargs):
    if _LLM["fail"]:
        raise RuntimeError("LLM unavailable")
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
    monkeypatch.setitem(_LLM, "fail", False)

    def build(chunk_token_size=48, chunk_overlap_token_size=8):
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
                "chunk_token_size": chunk_token_size,
                "chunk_overlap_token_size": chunk_overlap_token_size,
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


def _all_chunks(rag):
    paths = Path(rag.config.working_dir).glob("**/kv_store_text_chunks.json")
    return [
        row
        for path in paths
        for row in json.loads(path.read_text(encoding="utf-8")).values()
    ]


def _chunks(rag, doc_id):
    return [row for row in _all_chunks(rag) if row.get("full_doc_id") == doc_id]


def _assert_pages_cover_markers(chunks, markers, every_chunk=True):
    assert chunks, "expected text chunks"
    for chunk in chunks:
        if chunk.get("page_idx") is None:
            assert not every_chunk, f"chunk not annotated: {chunk['content']!r}"
            continue
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
async def test_real_pipeline_concurrent_inserts_never_get_wrong_pages(make_rag):
    """Concurrent inserts: LightRAG may chunk a queued document in the first
    caller's pipeline run, after the queued caller's insert returned. That
    document is left without pages rather than annotated from a guess."""
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

    sheets = [m.replace("PAGE", "SHEET") for m in MARKERS]
    a, b = _chunks(rag, "doc-a"), _chunks(rag, "doc-b")
    _assert_pages_cover_markers(a, MARKERS, every_chunk=False)
    _assert_pages_cover_markers(b, sheets, every_chunk=False)
    # whoever ran the pipeline saw its document processed and annotated it
    assert any(all("page_idx" in c for c in chunks) for chunks in (a, b))


@pytest.mark.asyncio
async def test_real_pipeline_document_paths_annotate_chunks(make_rag, monkeypatch):
    """process_document_complete and the LightRAG-API variant run the same
    annotation after their text insert."""
    rag = make_rag()
    parsed = {}

    async def parse_document(file_path, *args, **kwargs):
        return parsed[file_path], f"doc-{Path(file_path).stem}"

    monkeypatch.setattr(rag, "parse_document", parse_document)
    parsed["/in/one.pdf"] = _content_list("PAGE")
    parsed["/in/two.pdf"] = _content_list("SHEET")
    try:
        await rag.process_document_complete("/in/one.pdf")
        await rag.process_document_complete_lightrag_api("/in/two.pdf")
    finally:
        await _close(rag)

    _assert_pages_cover_markers(_chunks(rag, "doc-one"), MARKERS)
    _assert_pages_cover_markers(
        _chunks(rag, "doc-two"), [m.replace("PAGE", "SHEET") for m in MARKERS]
    )


@pytest.mark.asyncio
async def test_real_pipeline_identical_text_takes_the_owning_documents_pages(
    make_rag,
):
    """LightRAG stores one row per chunk content, so two documents with the
    same text share rows: a row's pages must be those of the document its
    full_doc_id names."""
    rag = make_rag()
    shifted = [dict(item, page_idx=item["page_idx"] + 5) for item in _content_list()]
    try:
        await rag.insert_content_list(
            _content_list(), file_path="a.pdf", doc_id="doc-a"
        )
        await rag.insert_content_list(shifted, file_path="b.pdf", doc_id="doc-b")
    finally:
        await _close(rag)

    offsets = {"doc-a": 0, "doc-b": 5}
    rows = _all_chunks(rag)
    assert rows
    for row in rows:
        if row.get("page_idx") is None:
            continue
        offset = offsets[row["full_doc_id"]]
        _assert_pages_cover_markers(
            [
                dict(
                    row,
                    page_idx=row["page_idx"] - offset,
                    page_idx_end=row.get("page_idx_end", row["page_idx"]) - offset,
                )
            ],
            MARKERS,
        )


@pytest.mark.asyncio
async def test_real_pipeline_lightrag_retry_of_same_text_gets_no_foreign_pages(
    make_rag,
):
    """A document LightRAG failed earlier is retried in the next pipeline run
    alongside a RAG-Anything insert of the same text; only rows owned by the
    RAG-Anything document may carry its pages."""
    rag = make_rag()
    text = "\n\n".join(item["text"] for item in _content_list())
    shifted = [dict(item, page_idx=item["page_idx"] + 10) for item in _content_list()]
    try:
        await rag._ensure_lightrag_initialized()
        _LLM["fail"] = True
        await rag.lightrag.ainsert(text, ids="doc-plain", file_paths="plain.txt")
        _LLM["fail"] = False
        await rag.insert_content_list(shifted, file_path="b.pdf", doc_id="doc-b")
    finally:
        await _close(rag)

    for row in _all_chunks(rag):
        if row.get("page_idx") is not None:
            assert row["full_doc_id"] == "doc-b"
            assert row["page_idx"] >= 10


@pytest.mark.parametrize("first_insert_fails", [False, True])
@pytest.mark.asyncio
async def test_real_pipeline_known_doc_id_keeps_its_pages(make_rag, first_insert_fails):
    """LightRAG drops an insert whose doc_id it already knows (it retries a
    failed one from the text it stored then), so a re-insert's pages are not
    applied."""
    rag = make_rag()
    shifted = [dict(item, page_idx=item["page_idx"] + 5) for item in _content_list()]
    try:
        _LLM["fail"] = first_insert_fails
        await rag.insert_content_list(
            _content_list(), file_path="a.pdf", doc_id="doc-a"
        )
        _LLM["fail"] = False
        await rag.insert_content_list(shifted, file_path="a.pdf", doc_id="doc-a")
    finally:
        await _close(rag)

    chunks = _chunks(rag, "doc-a")
    if first_insert_fails:
        assert all(c.get("page_idx") is None for c in chunks)
    else:
        _assert_pages_cover_markers(chunks, MARKERS)


@pytest.mark.asyncio
async def test_real_pipeline_split_heading_keeps_its_own_page(make_rag):
    """split_by_character pieces do not overlap: a heading whose word also
    occurs in the previous paragraph must not take that paragraph's page."""
    rag = make_rag(chunk_token_size=1200, chunk_overlap_token_size=100)
    try:
        await rag.insert_content_list(
            [
                {
                    "type": "text",
                    "text": "The setup is described here; Results follow later.",
                    "page_idx": 2,
                },
                {"type": "text", "text": "Results", "page_idx": 3},
                {"type": "text", "text": "Yield rose by 4%.", "page_idx": 3},
            ],
            file_path="split.pdf",
            doc_id="doc-split",
            split_by_character="\n\n",
        )
    finally:
        await _close(rag)

    pages = {c["content"]: c.get("page_idx") for c in _chunks(rag, "doc-split")}
    assert pages == {
        "The setup is described here; Results follow later.": 2,
        "Results": 3,
        "Yield rose by 4%.": 3,
    }


@pytest.mark.asyncio
async def test_real_pipeline_short_final_chunk_keeps_its_own_page(make_rag):
    """The token chunker's short final chunk (here a repeated footer) must not
    match an earlier copy of its text inside the previous window."""
    rag = make_rag()
    footer = "Confidential."
    try:
        await rag.insert_content_list(
            [
                {"type": "text", "text": "x" * 10, "page_idx": 0},
                {
                    "type": "text",
                    "text": "Body of page two." + "y" * 36,
                    "page_idx": 2,
                },
                {"type": "text", "text": footer, "page_idx": 2},
                {"type": "text", "text": footer, "page_idx": 3},
            ],
            file_path="tail.pdf",
            doc_id="doc-tail",
        )
    finally:
        await _close(rag)

    chunks = sorted(_chunks(rag, "doc-tail"), key=lambda c: c["chunk_order_index"])
    assert chunks[-1]["content"] == footer
    assert chunks[-1]["page_idx"] == 3
    assert "page_idx_end" not in chunks[-1]


@pytest.mark.asyncio
async def test_real_pipeline_oversized_piece_tail_keeps_its_own_page(make_rag):
    """With split_by_character (and not _only), a piece longer than one chunk
    is re-split into overlapping token windows; its short last window must
    not be matched to a copy of its text in the next block."""
    rag = make_rag(chunk_token_size=48, chunk_overlap_token_size=8)
    try:
        await rag.insert_content_list(
            [
                {"type": "text", "text": "A" * 80 + ".", "page_idx": 0},
                {
                    "type": "text",
                    "text": "Results. Mean density peaked.",
                    "page_idx": 1,
                },
            ],
            file_path="oversized.pdf",
            doc_id="doc-oversized",
            split_by_character="\n\n",
        )
    finally:
        await _close(rag)

    chunks = sorted(_chunks(rag, "doc-oversized"), key=lambda c: c["chunk_order_index"])
    assert [(c["content"][-8:], c.get("page_idx")) for c in chunks] == [
        ("AAAAAAAA", 0),
        ("AAAAAAA.", 0),
        (".", 0),
        (" peaked.", 1),
    ]


@pytest.mark.asyncio
async def test_real_pipeline_unlocatable_gap_does_not_shift_pages(make_rag):
    """A garbled block between pieces (U+FFFD survives sanitizing) must not
    push the next heading onto the previous paragraph's page."""
    rag = make_rag(chunk_token_size=1200, chunk_overlap_token_size=100)
    try:
        await rag.insert_content_list(
            [
                {
                    "type": "text",
                    "text": "The sampling design is described under Methods.",
                    "page_idx": 0,
                },
                {"type": "text", "text": "�" * 80, "page_idx": 1},
                {"type": "text", "text": "Methods", "page_idx": 1},
                {"type": "text", "text": "Cores were taken every 10 m.", "page_idx": 1},
            ],
            file_path="gap.pdf",
            doc_id="doc-gap",
            split_by_character="\n\n",
            split_by_character_only=True,
        )
    finally:
        await _close(rag)

    pages = {c["content"]: c.get("page_idx") for c in _chunks(rag, "doc-gap")}
    assert pages["The sampling design is described under Methods."] == 0
    assert pages["Methods"] == 1
    assert pages["Cores were taken every 10 m."] == 1
