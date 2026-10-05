"""Tests for page_idx provenance on text chunks (#330).

`separate_content()` joins all text blocks into one string before LightRAG
splits it, so the per-block `page_idx` recorded by MinerU never reaches the
text chunks (while multimodal chunks do carry it). The fix keeps the single
concatenated string — one doc_id, one doc_status row, no change to the ingest
contract — and annotates each chunk after LightRAG's chunker has split it.

Chunk positions are never searched for: LightRAG's chunker is deterministic,
so its geometry is replayed. The reference below derives true positions
independently from byte offsets (with a UTF-8 byte tokenizer, token window k
is exactly bytes [k*step, k*step + size) of the text).
"""

import codecs
import random
import types

import pytest
from lightrag.operate import chunking_by_token_size
from lightrag.utils import Tokenizer, compute_mdhash_id, sanitize_text_for_encoding

from raganything.processor import ProcessorMixin
from raganything.utils import (
    annotate_chunks_with_page_idx,
    build_sanitized_page_map,
    replay_chunk_spans,
    separate_content,
    separate_content_with_page_map,
)


class _ByteTokenizer:
    def encode(self, content):
        return list(content.encode("utf-8"))

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace")


BYTES = Tokenizer("bytes", _ByteTokenizer())


def _stripped(text, base):
    lead = len(text) - len(text.lstrip())
    end = len(text.rstrip())
    return (base + lead, base + end) if lead < end else None


def _reference_spans(text, sep, sep_only, overlap, size):
    """True span of every chunk's source text, from byte offsets alone.

    A token window over a UTF-8 byte tokenizer is exactly bytes
    ``[k * step, k * step + size)``; the source text it covers is the
    characters lying wholly inside those bytes (a character cut at either
    end only contributes U+FFFD fragments), minus edge whitespace.
    """

    def windows(piece, base):
        data = piece.encode("utf-8")
        bounds = []  # (first byte, end byte) of each character
        offset = 0
        for char in piece:
            width = len(char.encode("utf-8"))
            bounds.append((offset, offset + width))
            offset += width
        for start in range(0, len(data), size - overlap):
            stop = min(start + size, len(data))
            inside = [i for i, (b, e) in enumerate(bounds) if b >= start and e <= stop]
            if inside:
                yield piece[inside[0] : inside[-1] + 1], base + inside[0]
            else:
                yield "", base

    pieces = [(text, 0)] if not sep else []
    if sep:
        base = 0
        for piece in text.split(sep):
            pieces.append((piece, base))
            base += len(piece) + len(sep)
    spans = []
    for piece, base in pieces:
        whole = sep and (sep_only or len(piece.encode("utf-8")) <= size)
        for covered, start in [(piece, base)] if whole else windows(piece, base):
            spans.append(_stripped(covered, start))
    return spans


def _document(rng, pieces, pages=4):
    return [
        {
            "type": "text",
            "text": "".join(rng.choice(pieces) for _ in range(rng.randint(1, 14))),
            "page_idx": page,
        }
        for page in range(pages)
        for _ in range(rng.randint(1, 3))
    ]


# --------------------------------------------------------------------------
# replay: positions equal an independent byte-level reference
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sep,sep_only",
    [(None, False), ("\n\n", True), ("\n\n", False), (".", False)],
)
def test_replayed_positions_match_byte_reference(sep, sep_only):
    rng = random.Random(7)
    pieces = [
        "Footer. ",
        "ab ",
        "数据 ",
        "😀",
        "𠀀 ",
        "&amp; ",
        "x",
        "�",
        " ",
        "\x00",
        ".",
    ]
    checked = 0
    for _ in range(300):
        # split_by_character_only rejects any piece longer than one chunk
        size = rng.randint(200, 400) if sep_only else rng.randint(1, 24)
        overlap = rng.randint(0, size - 1)
        text, _, intervals = separate_content_with_page_map(_document(rng, pieces))
        sanitized, _ = build_sanitized_page_map(text, intervals)
        if not sanitized:
            continue
        try:
            chunks = chunking_by_token_size(
                BYTES, sanitized, sep, sep_only, overlap, size
            )
        except Exception:  # split_by_character_only piece over the limit
            continue
        spans = replay_chunk_spans(
            BYTES, sanitized, chunks, sep, sep_only, overlap, size
        )
        assert spans is not None
        reference = _reference_spans(sanitized, sep, sep_only, overlap, size)
        assert [c[0] if c else None for c in spans] == reference
        checked += len(chunks)
    assert checked > 500


@pytest.mark.parametrize("cut", [1, 2, 3])
def test_four_byte_character_cut_at_a_window_edge(cut):
    """A 4-byte character cut 1|3, 2|2 or 3|1 at a window boundary: the
    fragments on both sides are excluded and nothing after them shifts."""
    text = "x" * (10 - cut) + "\U0001f600" + "y" * 20
    chunks = chunking_by_token_size(BYTES, text, None, False, 0, 10)

    spans = replay_chunk_spans(BYTES, text, chunks, None, False, 0, 10)

    assert [c[0] if c else None for c in spans] == _reference_spans(
        text, None, False, 0, 10
    )


codecs.register_error(
    "per_byte_replace", lambda error: ("\ufffd" * (error.end - error.start), error.end)
)


class _PerByteReplacementTokenizer(_ByteTokenizer):
    """Replaces every byte of an invalid sequence, so a cut character leaves
    several U+FFFD instead of one."""

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="per_byte_replace")


class _QuestionMarkTokenizer(_ByteTokenizer):
    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace").replace("\ufffd", "?")


class _DroppingTokenizer(_ByteTokenizer):
    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="ignore")


@pytest.mark.parametrize(
    "decoder,text,size,overlap",
    [
        # several U+FFFD for one cut character
        (_PerByteReplacementTokenizer, "a😀", 3, 0),
        (_PerByteReplacementTokenizer, "bb数", 4, 0),
        (_PerByteReplacementTokenizer, "数a", 4, 2),
        # a cut character rendered as something other than U+FFFD
        (_QuestionMarkTokenizer, "abc数", 4, 1),
        # a cut character dropped altogether
        (_DroppingTokenizer, "abc数", 4, 1),
    ],
)
def test_replay_refuses_decoders_that_mark_cuts_differently(
    decoder, text, size, overlap
):
    tokenizer = Tokenizer("t", decoder())
    chunks = chunking_by_token_size(tokenizer, text, None, False, overlap, size)

    assert (
        replay_chunk_spans(tokenizer, text, chunks, None, False, overlap, size) is None
    )


class _WordTokenizer:
    """Decodes by joining words with spaces, like many WordPiece decoders."""

    def __init__(self):
        self.words = []

    def encode(self, content):
        ids = []
        for word in content.split():
            if word not in self.words:
                self.words.append(word)
            ids.append(self.words.index(word))
        return ids

    def decode(self, tokens):
        return " ".join(self.words[t] for t in tokens)


class _LowercasingTokenizer(_ByteTokenizer):
    def decode(self, tokens):
        return super().decode(tokens).lower()


@pytest.mark.parametrize(
    "tokenizer",
    [_WordTokenizer(), _LowercasingTokenizer()],
    ids=["space-joining", "lossy"],
)
def test_replay_refuses_tokenizers_that_are_not_byte_exact(tokenizer):
    """Token-to-character offsets are only exact for byte-level tokenizers;
    anything else must produce no positions rather than drifting ones."""
    tokenizer = Tokenizer("t", tokenizer)
    text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu."
    chunks = chunking_by_token_size(tokenizer, text, None, False, 1, 3)

    assert len(chunks) > 1
    assert replay_chunk_spans(tokenizer, text, chunks, None, False, 1, 3) is None


def test_genuine_replacement_characters_are_source_text():
    """Only U+FFFD produced by cutting a character is dropped from a span; a
    U+FFFD that is in the text itself belongs to its block."""
    blocks = [
        {"type": "text", "text": "x" * 28, "page_idx": 0},
        {"type": "text", "text": "\ufffd\ufffd", "page_idx": 1},
        {"type": "text", "text": "Page two text.", "page_idx": 2},
    ]

    # 30-byte windows: the second one starts exactly at the garbled block
    chunks = _annotate(blocks, size=30, overlap=0)

    assert chunks[1]["content"] == "\ufffd\ufffd\n\nPage two text."
    assert (chunks[1]["page_idx"], chunks[1]["page_idx_end"]) == (1, 2)


def test_replay_refuses_chunks_it_did_not_produce():
    text = "Alpha beta gamma.\n\nDelta epsilon."
    chunks = chunking_by_token_size(BYTES, text, None, False, 2, 8)
    chunks[1]["content"] = "something else"

    assert replay_chunk_spans(BYTES, text, chunks, None, False, 2, 8) is None


# --------------------------------------------------------------------------
# page map and annotation
# --------------------------------------------------------------------------


def _annotate(content_list, sep=None, sep_only=False, overlap=8, size=48):
    text, _, intervals = separate_content_with_page_map(content_list)
    sanitized, mapped = build_sanitized_page_map(text, intervals)
    chunks = chunking_by_token_size(BYTES, sanitized, sep, sep_only, overlap, size)
    spans = replay_chunk_spans(BYTES, sanitized, chunks, sep, sep_only, overlap, size)
    return annotate_chunks_with_page_idx(chunks, spans, mapped)


def test_repeated_footer_maps_to_its_own_page():
    blocks = [
        {"type": "text", "text": text, "page_idx": page}
        for page in range(3)
        for text in (f"Body {page}.", "Confidential.")
    ]

    chunks = _annotate(blocks, sep="\n\n", sep_only=True, size=1200)

    assert [c["page_idx"] for c in chunks] == [0, 0, 1, 1, 2, 2]


def test_short_final_token_chunk_keeps_its_own_page():
    footer = "Confidential."
    blocks = [
        {"type": "text", "text": "x" * 10, "page_idx": 0},
        {"type": "text", "text": "Body of page two." + "y" * 36, "page_idx": 2},
        {"type": "text", "text": footer, "page_idx": 2},
        {"type": "text", "text": footer, "page_idx": 3},
    ]

    chunks = _annotate(blocks)

    assert chunks[-1]["content"] == footer
    assert chunks[-1]["page_idx"] == 3


def test_chunk_spanning_pages_records_first_and_last_page():
    blocks = [
        {"type": "text", "text": "Intro on page zero.", "page_idx": 0},
        {"type": "text", "text": "Body on page one.", "page_idx": 1},
        {"type": "text", "text": "Conclusion on page two.", "page_idx": 2},
    ]

    (chunk,) = _annotate(blocks, size=1200, overlap=100)

    assert (chunk["page_idx"], chunk["page_idx_end"]) == (0, 2)


def test_pages_out_of_order_give_lowest_and_highest():
    blocks = [
        {"type": "text", "text": "Appendix on page three.", "page_idx": 3},
        {"type": "text", "text": "Note on page one.", "page_idx": 1},
        {"type": "text", "text": "Remark on page two.", "page_idx": 2},
    ]

    (chunk,) = _annotate(blocks, size=1200, overlap=100)

    assert (chunk["page_idx"], chunk["page_idx_end"]) == (1, 3)


def test_text_changed_by_sanitizing_is_still_annotated():
    """LightRAG chunks sanitized text (control chars removed, entities
    unescaped, ends stripped), so offsets into the raw text would be wrong."""
    blocks = [
        {"type": "text", "text": "  Page zero\x00 with a NUL.  ", "page_idx": 0},
        {"type": "text", "text": "Page one &amp; an entity.", "page_idx": 1},
        {"type": "text", "text": "Page two tail.", "page_idx": 2},
    ]

    chunks = _annotate(blocks, sep="\n\n", sep_only=True, size=1200)

    assert {c["content"]: c["page_idx"] for c in chunks} == {
        "Page zero with a NUL.": 0,
        "Page one & an entity.": 1,
        "Page two tail.": 2,
    }


def test_unpaginated_blocks_get_no_page_and_capture_nothing():
    """A block without page_idx is stepped over: it neither gets a page nor
    takes the position of a later block that repeats its text."""
    blocks = [
        {"type": "text", "text": "Cover page.", "page_idx": 0},
        {"type": "text", "text": "Key finding: Ember Garden hosted shrimp."},
        {"type": "text", "text": "Ember Garden hosted shrimp.", "page_idx": 4},
    ]
    text, _, intervals = separate_content_with_page_map(blocks)
    sanitized, mapped = build_sanitized_page_map(text, intervals)

    assert [page for _, _, page in intervals] == [0, None, 4]
    assert [page for _, _, page in mapped] == [0, 4]
    assert mapped[1][0] == sanitized.rindex("Ember Garden hosted shrimp.")

    chunks = _annotate(blocks, sep="\n\n", sep_only=True, size=1200)
    assert [c.get("page_idx") for c in chunks] == [0, None, 4]


def test_conflicting_candidate_positions_leave_the_chunk_unannotated():
    chunks = [{"content": "a"}]
    intervals = [(0, 5, 0), (5, 10, 1)]

    annotate_chunks_with_page_idx(chunks, [[(1, 2), (6, 7)]], intervals)

    assert "page_idx" not in chunks[0]


def test_separate_content_backcompat_returns_two_values():
    text_content, multimodal_items = separate_content(
        [
            {"type": "text", "text": "Intro.", "page_idx": 0},
            {"type": "image", "img_path": "/x.png", "page_idx": 0},
        ]
    )
    assert text_content == "Intro."
    assert [item["type"] for item in multimodal_items] == ["image"]


# --------------------------------------------------------------------------
# processor: annotating the rows LightRAG stored for one document
# --------------------------------------------------------------------------


class _KV:
    def __init__(self):
        self.rows = {}
        self.flushed = 0

    async def get_by_id(self, key):
        return self.rows.get(key)

    async def get_by_ids(self, keys):
        return [self.rows.get(key) for key in keys]

    async def upsert(self, data):
        self.rows.update({key: dict(value) for key, value in data.items()})

    async def index_done_callback(self):
        self.flushed += 1


class _FakeLightRAG:
    """Stores a document the way LightRAG 1.4.x does: the sanitized text in
    full_docs, one row per distinct chunk content (keyed by its hash) in
    text_chunks, and the chunk ids in doc_status."""

    chunk_token_size = 48
    chunk_overlap_token_size = 8
    tokenizer = BYTES

    def __init__(self):
        self.chunking_func = chunking_by_token_size
        self.doc_status, self.full_docs, self.text_chunks = _KV(), _KV(), _KV()

    def store(self, doc_id, text, split_by_character=None, status="processed"):
        content = sanitize_text_for_encoding(text)
        chunks = self.chunking_func(
            self.tokenizer,
            content,
            split_by_character,
            False,
            self.chunk_overlap_token_size,
            self.chunk_token_size,
        )
        ids = [compute_mdhash_id(c["content"], prefix="chunk-") for c in chunks]
        for chunk_id, chunk in zip(ids, chunks):
            self.text_chunks.rows[chunk_id] = {**chunk, "full_doc_id": doc_id}
        self.full_docs.rows[doc_id] = {"content": content}
        self.doc_status.rows[doc_id] = {"status": status, "chunks_list": list(ids)}
        return ids


def _processor(lightrag):
    processor = ProcessorMixin()
    processor.lightrag = lightrag
    processor.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    return processor


THREE_PAGES = [
    {"type": "text", "text": "Intro on page zero.", "page_idx": 0},
    {"type": "text", "text": "Body paragraph on page one.", "page_idx": 1},
    {"type": "text", "text": "Conclusion on page two.", "page_idx": 2},
]


async def _ingest(lightrag, content_list, doc_id, split_by_character="\n\n"):
    """Store like LightRAG, then run the post-insert annotation."""
    text, _, intervals = separate_content_with_page_map(content_list)
    ids = lightrag.store(doc_id, text, split_by_character)
    await _processor(lightrag)._annotate_text_chunk_pages(
        doc_id, text, intervals, split_by_character, False
    )
    return [lightrag.text_chunks.rows[chunk_id] for chunk_id in ids]


@pytest.mark.asyncio
async def test_rows_of_the_document_get_their_pages():
    lightrag = _FakeLightRAG()

    rows = await _ingest(lightrag, THREE_PAGES, "doc-1")

    assert [r["page_idx"] for r in rows] == [0, 1, 2]
    assert lightrag.text_chunks.flushed == 1


@pytest.mark.asyncio
async def test_token_windows_are_annotated_too():
    lightrag = _FakeLightRAG()

    rows = await _ingest(lightrag, THREE_PAGES, "doc-1", split_by_character=None)

    assert len(rows) > 1
    assert all("page_idx" in r for r in rows)
    assert rows[0]["page_idx"] == 0 and rows[-1].get("page_idx_end", 2) == 2


@pytest.mark.asyncio
async def test_rows_now_owned_by_another_document_are_left_alone():
    """LightRAG keys chunk rows by content: a row another document re-stored
    must not get this document's pages."""
    lightrag = _FakeLightRAG()
    text, _, intervals = separate_content_with_page_map(THREE_PAGES)
    ids = lightrag.store("doc-1", text, "\n\n")
    lightrag.text_chunks.rows[ids[1]]["full_doc_id"] = "doc-2"

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    rows = [lightrag.text_chunks.rows[i] for i in ids]
    assert [r.get("page_idx") for r in rows] == [0, None, 2]


@pytest.mark.asyncio
async def test_document_chunked_with_other_settings_is_not_annotated():
    """A queued document can be chunked in another caller's pipeline run,
    with that caller's split settings; the replay would not match."""
    lightrag = _FakeLightRAG()
    text, _, intervals = separate_content_with_page_map(THREE_PAGES)
    ids = lightrag.store("doc-1", text, split_by_character=None)

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    assert all("page_idx" not in lightrag.text_chunks.rows[i] for i in ids)


@pytest.mark.asyncio
async def test_chunks_lightrag_did_not_record_are_not_annotated():
    """The recomputed chunks must be exactly the ones LightRAG recorded for
    the document."""
    lightrag = _FakeLightRAG()
    text, _, intervals = separate_content_with_page_map(THREE_PAGES)
    ids = lightrag.store("doc-1", text, "\n\n")
    lightrag.doc_status.rows["doc-1"]["chunks_list"].append("chunk-other")

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    assert all("page_idx" not in lightrag.text_chunks.rows[i] for i in ids)


@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
@pytest.mark.asyncio
async def test_document_not_processed_yet_is_not_annotated(status):
    lightrag = _FakeLightRAG()
    text, _, intervals = separate_content_with_page_map(THREE_PAGES)
    ids = lightrag.store("doc-1", text, "\n\n", status=status)

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    assert all("page_idx" not in lightrag.text_chunks.rows[i] for i in ids)


@pytest.mark.asyncio
async def test_stored_text_from_another_insert_is_not_annotated():
    lightrag = _FakeLightRAG()
    text, _, intervals = separate_content_with_page_map(THREE_PAGES)
    ids = lightrag.store("doc-1", text, "\n\n")
    lightrag.full_docs.rows["doc-1"]["content"] = text.replace("zero", "nil")

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    assert all("page_idx" not in lightrag.text_chunks.rows[i] for i in ids)


@pytest.mark.asyncio
async def test_repeated_chunk_on_different_pages_gets_no_page():
    """Identical chunks of one document share a row; it is labelled only if
    every occurrence is on the same pages."""
    lightrag = _FakeLightRAG()
    blocks = [
        {"type": "text", "text": text, "page_idx": page}
        for page in range(2)
        for text in (f"Body {page}.", "Confidential.")
    ]

    rows = await _ingest(lightrag, blocks, "doc-1")

    by_content = {r["content"]: r.get("page_idx") for r in rows}
    assert by_content == {"Body 0.": 0, "Confidential.": None, "Body 1.": 1}


@pytest.mark.asyncio
async def test_stale_pages_are_overwritten_explicitly():
    """Backends that merge updates (MongoDB $set) keep fields the new row
    lacks, so a stale page_idx_end must be cleared with an explicit None."""
    lightrag = _FakeLightRAG()
    text, _, intervals = separate_content_with_page_map(THREE_PAGES)
    ids = lightrag.store("doc-1", text, "\n\n")
    for chunk_id in ids:
        lightrag.text_chunks.rows[chunk_id].update(page_idx=7, page_idx_end=9)

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    rows = [lightrag.text_chunks.rows[i] for i in ids]
    assert [(r["page_idx"], r["page_idx_end"]) for r in rows] == [
        (0, None),
        (1, None),
        (2, None),
    ]


@pytest.mark.asyncio
async def test_rows_the_document_cannot_label_lose_stale_pages():
    """A document without pages (or that cannot be replayed) now owning a
    row that still carries a previous owner's pages clears them."""
    lightrag = _FakeLightRAG()
    blocks = [dict(block, page_idx=None) for block in THREE_PAGES]
    text, _, intervals = separate_content_with_page_map(blocks)
    ids = lightrag.store("doc-1", text, "\n\n")
    lightrag.text_chunks.rows[ids[0]].update(page_idx=4, page_idx_end=6)
    lightrag.text_chunks.rows[ids[1]].update(full_doc_id="doc-2", page_idx=4)

    await _processor(lightrag)._annotate_text_chunk_pages(
        "doc-1", text, intervals, "\n\n", False
    )

    rows = lightrag.text_chunks.rows
    assert (rows[ids[0]]["page_idx"], rows[ids[0]]["page_idx_end"]) == (None, None)
    assert rows[ids[1]]["page_idx"] == 4  # another document's row


@pytest.mark.asyncio
async def test_custom_chunker_is_left_alone():
    """Only LightRAG's own chunker can be replayed."""

    def custom(tokenizer, content, *args):
        return [{"tokens": 1, "content": content, "chunk_order_index": 0}]

    lightrag = _FakeLightRAG()
    lightrag.chunking_func = custom

    rows = await _ingest(lightrag, THREE_PAGES, "doc-1")

    assert "page_idx" not in rows[0]
    assert lightrag.text_chunks.flushed == 0


@pytest.mark.asyncio
async def test_blocks_without_page_idx_write_nothing():
    lightrag = _FakeLightRAG()

    rows = await _ingest(
        lightrag, [dict(block, page_idx=None) for block in THREE_PAGES], "doc-1"
    )

    assert all("page_idx" not in r for r in rows)
    assert lightrag.text_chunks.flushed == 0
