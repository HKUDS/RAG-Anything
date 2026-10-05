"""Tests for page_idx provenance on text chunks (#330).

`separate_content()` joins all text blocks into one string before LightRAG
splits it, so the per-block `page_idx` recorded by MinerU never reaches the
text chunks (while multimodal chunks do carry it). The fix keeps the single
concatenated string but carries a block-offset -> page_idx map alongside it
and annotates each chunk after LightRAG's chunking func has split it —
one doc_id, one doc_status row, no change to the ingest contract.
"""

import importlib.util
import sys
import time
import types
from pathlib import Path

import pytest
from lightrag.utils import sanitize_text_for_encoding

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InMemoryJsonStorage:
    def __init__(self):
        self.records = {}

    async def get_by_id(self, key):
        return self.records.get(key)

    async def upsert(self, data):
        for key, value in data.items():
            self.records[key] = value

    async def index_done_callback(self):
        return None


def _load_raganything_module(module_name: str, relative_path: str):
    module_path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def raganything_modules(monkeypatch):
    logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )

    fake_lightrag = types.ModuleType("lightrag")
    fake_lightrag_utils = types.ModuleType("lightrag.utils")
    fake_lightrag_utils.logger = logger
    fake_lightrag_utils.compute_mdhash_id = (
        lambda value, prefix="": f"{prefix}{abs(hash(value))}"
    )
    fake_lightrag_utils.sanitize_text_for_encoding = sanitize_text_for_encoding

    monkeypatch.setitem(sys.modules, "lightrag", fake_lightrag)
    monkeypatch.setitem(sys.modules, "lightrag.utils", fake_lightrag_utils)

    rag_pkg = types.ModuleType("raganything")
    rag_pkg.__path__ = [str(PROJECT_ROOT / "raganything")]
    monkeypatch.setitem(sys.modules, "raganything", rag_pkg)

    base_module = _load_raganything_module("raganything.base", "raganything/base.py")
    _load_raganything_module("raganything.parser", "raganything/parser.py")
    utils_module = _load_raganything_module("raganything.utils", "raganything/utils.py")
    processor_module = _load_raganything_module(
        "raganything.processor", "raganything/processor.py"
    )

    return types.SimpleNamespace(
        base=base_module,
        utils=utils_module,
        processor=processor_module,
    )


class FakeDocStatusStorage(InMemoryJsonStorage):
    pass


class ChunkRecordingLightRAG:
    """Mimics the parts of LightRAG 1.4.x that text ingestion touches.

    Reproduces the pipeline in lightrag/lightrag.py ``apipeline_process_enqueue_documents``:
    ``self.chunking_func(...)`` is called per queued document and every dict it
    returns is spread into the stored chunk row (``{**dp, "full_doc_id": ...}``),
    so extra fields set by the chunking func persist on the chunk.
    """

    def __init__(self, chunking_func):
        self.chunking_func = chunking_func
        self.doc_status = FakeDocStatusStorage()
        self.text_chunks = InMemoryJsonStorage()
        self.inserted_inputs = []

    async def ainsert(
        self,
        *,
        input,
        file_paths=None,
        split_by_character=None,
        split_by_character_only=False,
        ids=None,
        **kwargs,
    ):
        self.inserted_inputs.append(input)
        # LightRAG stores and chunks sanitize_text_for_encoding(input).
        chunking_result = self.chunking_func(
            None,
            sanitize_text_for_encoding(input),
            split_by_character,
            split_by_character_only,
            100,  # chunk_overlap_token_size
            1200,  # chunk_token_size
        )
        if hasattr(chunking_result, "__await__"):
            chunking_result = await chunking_result
        doc_id = ids if isinstance(ids, str) else (ids[0] if ids else "doc-auto")
        for dp in chunking_result:
            chunk_id = f"chunk-{len(self.text_chunks.records)}-{abs(hash(dp['content'])) % 10000}"
            self.text_chunks.records[chunk_id] = {
                **dp,
                "full_doc_id": doc_id,
                "file_path": file_paths,
                "llm_cache_list": [],
            }


def split_on_blank_lines(
    tokenizer,
    content,
    split_by_character=None,
    split_by_character_only=False,
    chunk_overlap_token_size=100,
    chunk_token_size=1200,
):
    """Deterministic stand-in for chunking_by_token_size: one chunk per block."""
    return [
        {"tokens": 1, "content": part.strip(), "chunk_order_index": index}
        for index, part in enumerate(content.split("\n\n"))
        if part.strip()
    ]


THREE_PAGE_CONTENT_LIST = [
    {"type": "text", "text": "Intro on page zero.", "page_idx": 0},
    {"type": "text", "text": "Body paragraph on page one.", "page_idx": 1},
    {"type": "text", "text": "More body on page one.", "page_idx": 1},
    {"type": "text", "text": "Conclusion on page two.", "page_idx": 2},
]


def _make_processor(raganything_modules, lightrag, tmp_path):
    processor_module = raganything_modules.processor

    class DummyProcessor(processor_module.ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.lightrag = lightrag
    processor.multimodal_status_cache = InMemoryJsonStorage()
    processor.logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    processor.config = types.SimpleNamespace(
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
        content_format="default",
    )

    async def fake_ensure_lightrag_initialized():
        return {"success": True}

    async def fake_parse_document(
        file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return (list(THREE_PAGE_CONTENT_LIST), "doc-generated")

    processor._ensure_lightrag_initialized = fake_ensure_lightrag_initialized
    processor.parse_document = fake_parse_document
    return processor


@pytest.mark.asyncio
async def test_process_document_complete_annotates_text_chunks_with_page_idx(
    raganything_modules, tmp_path
):
    """Regression test for #330: text chunks must carry the page_idx of the
    blocks they were chunked from, like multimodal chunks already do."""
    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)

    await processor.process_document_complete(
        file_path=str(tmp_path / "sample.pdf"),
        doc_id="doc-pages",
        file_name="sample.pdf",
    )

    chunks = lightrag.text_chunks.records
    assert chunks, "expected text chunks to be stored"
    pages_by_content = {row["content"]: row.get("page_idx") for row in chunks.values()}
    assert pages_by_content["Intro on page zero."] == 0
    assert pages_by_content["Body paragraph on page one."] == 1
    assert pages_by_content["More body on page one."] == 1
    assert pages_by_content["Conclusion on page two."] == 2


@pytest.mark.asyncio
async def test_chunk_spanning_pages_gets_page_range(raganything_modules, tmp_path):
    """A chunk covering several pages records first and last page."""
    lightrag = ChunkRecordingLightRAG(
        # Emulate token chunking that merges everything into one chunk.
        lambda tokenizer, content, *a, **k: [
            {"tokens": 1, "content": content.strip(), "chunk_order_index": 0}
        ]
    )
    processor = _make_processor(raganything_modules, lightrag, tmp_path)

    await processor.process_document_complete(
        file_path=str(tmp_path / "sample.pdf"),
        doc_id="doc-span",
        file_name="sample.pdf",
    )

    chunks = list(lightrag.text_chunks.records.values())
    assert len(chunks) == 1
    assert chunks[0]["page_idx"] == 0
    assert chunks[0]["page_idx_end"] == 2


@pytest.mark.asyncio
async def test_chunking_wrapper_is_installed_once_and_delegates(
    raganything_modules, tmp_path
):
    """One persistent wrapper, shared registry, original chunking output."""
    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)

    await processor.process_document_complete(
        file_path=str(tmp_path / "a.pdf"), doc_id="doc-a", file_name="a.pdf"
    )
    wrapper = lightrag.chunking_func
    await processor.process_document_complete(
        file_path=str(tmp_path / "b.pdf"), doc_id="doc-b", file_name="b.pdf"
    )

    assert lightrag.chunking_func is wrapper
    assert wrapper._raganything_page_maps == {}  # consumed when chunked
    contents = sorted(row["content"] for row in lightrag.text_chunks.records.values())
    expected = sorted(
        block["text"] for block in THREE_PAGE_CONTENT_LIST for _ in range(2)
    )
    assert contents == expected


@pytest.mark.asyncio
async def test_text_changed_by_sanitizing_is_still_annotated(
    raganything_modules, tmp_path
):
    """LightRAG chunks sanitized text (control chars removed, entities
    unescaped, ends stripped), so offsets into the raw text are wrong."""
    content_list = [
        {"type": "text", "text": "  Page zero\x00 with a NUL.  ", "page_idx": 0},
        {"type": "text", "text": "Page one &amp; an entity.", "page_idx": 1},
        {"type": "text", "text": "Page two tail.", "page_idx": 2},
    ]

    async def fake_parse_document(
        file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return (list(content_list), "doc-generated")

    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)
    processor.parse_document = fake_parse_document

    await processor.process_document_complete(
        file_path=str(tmp_path / "s.pdf"), doc_id="doc-s", file_name="s.pdf"
    )

    pages = {
        r["content"]: r.get("page_idx") for r in lightrag.text_chunks.records.values()
    }
    assert pages == {
        "Page zero with a NUL.": 0,
        "Page one & an entity.": 1,
        "Page two tail.": 2,
    }


def test_repeated_text_maps_to_its_own_occurrence(raganything_modules):
    """A footer repeated on every page must not all map to its first page."""
    utils = raganything_modules.utils
    footer = "Confidential."
    blocks = [
        {"type": "text", "text": text, "page_idx": page}
        for page in range(3)
        for text in (f"Body {page}.", footer)
    ]
    text, _, intervals = utils.separate_content_with_page_map(blocks)
    sanitized, mapped = utils.build_sanitized_page_map(text, intervals)
    chunks = [{"content": part} for part in sanitized.split("\n\n")]

    utils.annotate_chunks_with_page_idx(chunks, sanitized, mapped, mode="split")

    assert [c["page_idx"] for c in chunks] == [0, 0, 1, 1, 2, 2]


def test_unknown_chunker_leaves_ambiguous_chunks_unannotated(raganything_modules):
    """Without knowing how a custom chunker works, a chunk whose text occurs
    more than once nearby is skipped rather than guessed."""
    utils = raganything_modules.utils
    blocks = [
        {"type": "text", "text": text, "page_idx": page}
        for page in range(3)
        for text in (f"Body {page}.", "Confidential.")
    ]
    text, _, intervals = utils.separate_content_with_page_map(blocks)
    sanitized, mapped = utils.build_sanitized_page_map(text, intervals)
    chunks = [{"content": part} for part in sanitized.split("\n\n")]

    utils.annotate_chunks_with_page_idx(chunks, sanitized, mapped)

    for chunk in chunks:
        if chunk["content"].startswith("Body"):
            assert chunk["page_idx"] == int(chunk["content"][5])
        else:
            assert chunk.get("page_idx") in (None, *range(3))
    footers = [c for c in chunks if c["content"] == "Confidential." and "page_idx" in c]
    for footer in footers:  # whatever is annotated must be its own page
        position = chunks.index(footer)
        assert footer["page_idx"] == position // 2


def test_unpaginated_block_does_not_capture_a_later_interval(raganything_modules):
    """A paginated block whose text also occurs inside an earlier
    unpaginated block must be placed at its own position."""
    utils = raganything_modules.utils
    blocks = [
        {"type": "text", "text": "Cover page.", "page_idx": 0},
        {"type": "text", "text": "Key finding: Ember Garden hosted shrimp."},
        {"type": "text", "text": "Ember Garden hosted shrimp.", "page_idx": 4},
    ]
    text, _, intervals = utils.separate_content_with_page_map(blocks)
    sanitized, mapped = utils.build_sanitized_page_map(text, intervals)

    assert [page for _, _, page in mapped] == [0, 4]
    start, end, _ = mapped[1]
    assert start == sanitized.rindex("Ember Garden hosted shrimp.")
    assert sanitized[start:end] == "Ember Garden hosted shrimp."


def test_replacement_chars_at_chunk_edges_are_trimmed(raganything_modules):
    """Token slices that split a multi-byte character decode to U+FFFD."""
    utils = raganything_modules.utils
    blocks = [
        {"type": "text", "text": "数据经过归一化", "page_idx": 4},
        {"type": "text", "text": "由分析引擎检测", "page_idx": 5},
    ]
    text, _, intervals = utils.separate_content_with_page_map(blocks)
    sanitized, mapped = utils.build_sanitized_page_map(text, intervals)
    chunks = [{"content": "\ufffd经过归一\ufffd"}, {"content": "\ufffd分析引擎\ufffd"}]

    utils.annotate_chunks_with_page_idx(chunks, sanitized, mapped)

    assert [c.get("page_idx") for c in chunks] == [4, 5]


@pytest.mark.asyncio
async def test_page_map_registry_is_bounded(raganything_modules, tmp_path):
    """Maps whose document is never chunked (dedup, failure) cannot pile up."""
    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)
    limit = processor._PAGE_MAP_REGISTRY_LIMIT

    for index in range(limit + 5):
        await processor._register_page_map(f"doc {index} text", [(0, 4, 0)])

    assert len(lightrag.chunking_func._raganything_page_maps) == limit


@pytest.mark.asyncio
async def test_identical_text_with_different_pages_is_not_annotated(
    raganything_modules, tmp_path
):
    """Two pending documents with the same text but different pagination:
    annotating either could use the other's pages, so neither is."""
    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)
    text = "Alpha.\n\nBeta."

    await processor._register_page_map(text, [(0, 6, 0), (8, 13, 1)])
    await processor._register_page_map(text, [(0, 6, 3), (8, 13, 4)])
    chunks = lightrag.chunking_func(None, text, None, False, 100, 1200)

    assert all("page_idx" not in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_already_processed_document_is_not_registered(
    raganything_modules, tmp_path
):
    """LightRAG skips a doc_id it has processed; its map would never be used."""
    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    lightrag.doc_status.records["doc-done"] = {"status": "processed"}
    processor = _make_processor(raganything_modules, lightrag, tmp_path)

    await processor._register_page_map("Some text.", [(0, 10, 0)], "doc-done")

    assert not hasattr(lightrag.chunking_func, "_raganything_page_maps")


@pytest.mark.asyncio
async def test_wrapper_exposes_the_wrapped_chunker(raganything_modules, tmp_path):
    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)

    await processor._register_page_map("Some text.", [(0, 10, 0)])

    assert lightrag.chunking_func.__wrapped__ is split_on_blank_lines


def test_chunker_that_does_not_emit_source_text_stays_linear(raganything_modules):
    """A chunker that decorates its chunks is never located; the search must
    give up instead of rescanning the document for every chunk."""
    utils = raganything_modules.utils
    text = "word " * 400_000
    chunks = [{"content": f"[section {i}] word word"} for i in range(5_000)]

    started = time.perf_counter()
    utils.annotate_chunks_with_page_idx(chunks, text, [(0, len(text), 0)])

    assert time.perf_counter() - started < 1.0
    assert all("page_idx" not in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_blocks_without_page_idx_leave_chunks_unannotated(
    raganything_modules, tmp_path, monkeypatch
):
    """Blocks lacking page_idx (or with junk values) must never yield a wrong page."""
    content_list = [
        {"type": "text", "text": "No page metadata here."},
        {"type": "text", "text": "Still no page.", "page_idx": "zero"},
    ]

    async def fake_parse_document(
        file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return (list(content_list), "doc-generated")

    lightrag = ChunkRecordingLightRAG(split_on_blank_lines)
    processor = _make_processor(raganything_modules, lightrag, tmp_path)
    processor.parse_document = fake_parse_document

    await processor.process_document_complete(
        file_path=str(tmp_path / "sample.pdf"),
        doc_id="doc-nopage",
        file_name="sample.pdf",
    )

    chunks = lightrag.text_chunks.records
    assert chunks
    for row in chunks.values():
        assert "page_idx" not in row
        assert "page_idx_end" not in row


@pytest.mark.asyncio
async def test_separate_content_backcompat_returns_two_values(raganything_modules):
    """separate_content keeps its historical two-value contract."""
    utils = raganything_modules.utils
    text_content, multimodal_items = utils.separate_content(THREE_PAGE_CONTENT_LIST)
    assert text_content == (
        "Intro on page zero.\n\n"
        "Body paragraph on page one.\n\n"
        "More body on page one.\n\n"
        "Conclusion on page two."
    )
    assert multimodal_items == []
