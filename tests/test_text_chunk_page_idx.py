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

import random
import types

import pytest
from lightrag.operate import chunking_by_token_size
from lightrag.utils import Tokenizer, sanitize_text_for_encoding

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


def _trim(text):
    while True:
        trimmed = text.strip().strip("�")
        if trimmed == text:
            return text
        text = trimmed


def _reference_spans(text, sep, sep_only, overlap, size):
    """True start of every chunk's trimmed content, from byte offsets alone."""

    def leading_trim(raw):
        index = 0
        while index < len(raw) and (raw[index].isspace() or raw[index] == "\ufffd"):
            index += 1
        return index

    def windows(piece, base):
        data = piece.encode("utf-8")
        char_starts = []  # byte offset at which each character starts
        offset = 0
        for char in piece:
            char_starts.append(offset)
            offset += len(char.encode("utf-8"))
        for start in range(0, len(data), size - overlap):
            raw = data[start : start + size].decode("utf-8", errors="replace")
            # first character that starts inside the window
            first = next(
                (i for i, b in enumerate(char_starts) if b >= start), len(piece)
            )
            stray = (char_starts[first] if first < len(piece) else len(data)) - start
            # each stray continuation byte decodes to one U+FFFD before `first`
            yield raw, base + first - stray

    starts = []
    pieces = [(text, 0)] if not sep else []
    if sep:
        base = 0
        for piece in text.split(sep):
            pieces.append((piece, base))
            base += len(piece) + len(sep)
    for piece, base in pieces:
        whole = sep and (sep_only or len(piece.encode("utf-8")) <= size)
        for raw, raw_start in [(piece, base)] if whole else windows(piece, base):
            if not _trim(raw):
                starts.append(None)
            else:
                starts.append(raw_start + leading_trim(raw))
    return starts


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
    pieces = ["Footer. ", "ab ", "数据 ", "&amp; ", "x", "�", " ", "\x00", "."]
    checked = 0
    for _ in range(300):
        # split_by_character_only rejects any piece longer than one chunk
        size = rng.randint(200, 400) if sep_only else rng.randint(2, 24)
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
        assert [c[0][0] if c else None for c in spans] == reference
        checked += len(chunks)
    assert checked > 500


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
# processor: wrapper and registry around LightRAG's chunker
# --------------------------------------------------------------------------


class _DocStatus:
    def __init__(self):
        self.records = {}

    async def get_by_id(self, doc_id):
        return self.records.get(doc_id)


class _FakeLightRAG:
    """Calls chunking_func the way LightRAG 1.4.x does: on the sanitized text,
    with positional split/overlap/size arguments."""

    def __init__(self, chunking_func=chunking_by_token_size):
        self.chunking_func = chunking_func
        self.doc_status = _DocStatus()

    def chunk(self, text, split_by_character=None, overlap=8, size=48):
        return self.chunking_func(
            BYTES,
            sanitize_text_for_encoding(text),
            split_by_character,
            False,
            overlap,
            size,
        )


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


async def _register(processor, content_list, doc_id=None, file_path=None):
    text, _, intervals = separate_content_with_page_map(content_list)
    await processor._register_page_map(text, intervals, doc_id, file_path)
    return text


@pytest.mark.asyncio
async def test_registered_document_is_annotated_and_map_consumed():
    lightrag = _FakeLightRAG()
    processor = _processor(lightrag)

    text = await _register(processor, THREE_PAGES)
    chunks = lightrag.chunk(text, "\n\n")

    assert [c["page_idx"] for c in chunks] == [0, 1, 2]
    assert lightrag.chunking_func._raganything_page_maps == {}


@pytest.mark.asyncio
async def test_wrapper_is_installed_once_and_does_not_change_chunks():
    lightrag = _FakeLightRAG()
    processor = _processor(lightrag)
    text = await _register(processor, THREE_PAGES)
    wrapper = lightrag.chunking_func
    await _register(processor, THREE_PAGES[:2])

    assert lightrag.chunking_func is wrapper
    assert wrapper.__wrapped__ is chunking_by_token_size
    expected = chunking_by_token_size(
        BYTES, sanitize_text_for_encoding(text), None, False, 8, 48
    )
    produced = [
        {k: v for k, v in c.items() if k not in ("page_idx", "page_idx_end")}
        for c in lightrag.chunk(text)
    ]
    assert produced == expected


@pytest.mark.asyncio
async def test_custom_chunker_is_left_alone():
    """Only LightRAG's own chunker can be replayed; any other is untouched."""

    def custom(tokenizer, content, *args):
        return [{"tokens": 1, "content": content, "chunk_order_index": 0}]

    lightrag = _FakeLightRAG(custom)
    processor = _processor(lightrag)

    text = await _register(processor, THREE_PAGES)

    assert lightrag.chunking_func is custom
    assert "page_idx" not in lightrag.chunk(text)[0]


@pytest.mark.asyncio
async def test_page_map_registry_is_bounded():
    lightrag = _FakeLightRAG()
    processor = _processor(lightrag)
    limit = processor._PAGE_MAP_REGISTRY_LIMIT

    for index in range(limit + 5):
        await processor._register_page_map(f"doc {index} text", [(0, 10, 0)])

    assert len(lightrag.chunking_func._raganything_page_maps) == limit


@pytest.mark.asyncio
async def test_identical_text_with_different_pages_is_not_annotated():
    lightrag = _FakeLightRAG()
    processor = _processor(lightrag)
    text = await _register(processor, THREE_PAGES)
    await _register(
        processor,
        [dict(block, page_idx=block["page_idx"] + 5) for block in THREE_PAGES],
    )

    assert all("page_idx" not in c for c in lightrag.chunk(text, "\n\n"))


@pytest.mark.asyncio
async def test_same_text_without_pages_invalidates_a_pending_map():
    lightrag = _FakeLightRAG()
    processor = _processor(lightrag)
    text = await _register(processor, THREE_PAGES)
    await _register(processor, [dict(block, page_idx=None) for block in THREE_PAGES])

    assert all("page_idx" not in c for c in lightrag.chunk(text, "\n\n"))


@pytest.mark.asyncio
async def test_known_doc_id_from_another_file_is_not_registered():
    """LightRAG drops an insert whose doc_id it already knows."""
    lightrag = _FakeLightRAG()
    lightrag.doc_status.records["doc-1"] = {"status": "failed", "file_path": "old.pdf"}
    processor = _processor(lightrag)

    await _register(processor, THREE_PAGES, "doc-1", "new.pdf")

    assert lightrag.chunking_func is chunking_by_token_size


@pytest.mark.asyncio
async def test_failed_retry_of_the_same_file_is_registered():
    """LightRAG re-chunks a FAILED document's stored text, which is this
    file's text when the record came from the same file."""
    lightrag = _FakeLightRAG()
    lightrag.doc_status.records["doc-1"] = {"status": "failed", "file_path": "a.pdf"}
    processor = _processor(lightrag)

    text = await _register(processor, THREE_PAGES, "doc-1", "a.pdf")

    assert [c["page_idx"] for c in lightrag.chunk(text, "\n\n")] == [0, 1, 2]


@pytest.mark.asyncio
async def test_blocks_without_page_idx_install_nothing():
    lightrag = _FakeLightRAG()
    processor = _processor(lightrag)

    await _register(processor, [dict(block, page_idx=None) for block in THREE_PAGES])

    assert lightrag.chunking_func is chunking_by_token_size
