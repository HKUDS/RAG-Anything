"""Tests for sidecar-backed text insertion (page provenance, issue #330).

The real ``write_sidecar``/``MinerUIRBuilder`` from lightrag are exercised
(skipped when the installed lightrag lacks the sidecar subsystem); LightRAG
itself is a recording fake so the enqueue/merge contract is pinned without a
live pipeline.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.sidecar_ingest import (  # noqa: E402
    insert_text_with_sidecar,
    sidecar_available,
    text_only_content_list,
)

requires_sidecar = pytest.mark.skipif(
    not sidecar_available(),
    reason="installed lightrag lacks the sidecar subsystem",
)


CONTENT_LIST = [
    {"type": "text", "text": "# Report Title", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "First page prose.", "page_idx": 0},
    {"type": "image", "img_path": "images/x.jpg", "page_idx": 1},
    {"type": "table", "table_body": "<table></table>", "page_idx": 1},
    {"type": "text", "text": "Second page prose.", "page_idx": 1},
    {"type": "text", "text": "   ", "page_idx": 1},
]


def test_text_only_filter_mirrors_separate_content():
    kept = text_only_content_list(CONTENT_LIST)
    assert [i["text"] for i in kept] == [
        "# Report Title",
        "First page prose.",
        "Second page prose.",
    ]
    assert all(i["type"] == "text" for i in kept)
    # page_idx survives the filter — it is the whole point.
    assert [i["page_idx"] for i in kept] == [0, 0, 1]


class FakeKV:
    def __init__(self):
        self.records = {}

    async def get_by_id(self, key):
        return self.records.get(key)

    async def upsert(self, payload):
        self.records.update(payload)

    async def index_done_callback(self):
        pass


class FakeLightRAG:
    """Records the enqueue/process calls and simulates what enqueue persists
    (full_docs row carrying process_options, plus a doc_status row)."""

    def __init__(self, duplicate: bool = False):
        self.duplicate = duplicate
        self.enqueue_calls = []
        self.process_calls = 0
        self.full_docs = FakeKV()
        self.doc_status = FakeKV()

    async def apipeline_enqueue_documents(self, **kwargs):
        self.enqueue_calls.append(kwargs)
        if self.duplicate:
            return "track-dup"
        doc_id = kwargs["ids"][0]
        await self.full_docs.upsert(
            {
                doc_id: {
                    "content": kwargs["input"][0],
                    "file_path": kwargs["file_paths"][0],
                    "process_options": kwargs["process_options"][0],
                }
            }
        )
        await self.doc_status.upsert({doc_id: {"status": "pending"}})
        return "track-1"

    async def apipeline_process_enqueue_documents(self):
        self.process_calls += 1


DOC_ID = "doc-0123456789abcdef0123456789abcdef"


@requires_sidecar
def test_insert_writes_sidecar_and_merges_full_docs(tmp_path):
    rag = FakeLightRAG()

    result = asyncio.run(
        insert_text_with_sidecar(
            rag,
            content_list=CONTENT_LIST,
            doc_id=DOC_ID,
            file_name="report.pdf",
            document_name="report.pdf",
            sidecar_parent_dir=tmp_path,
        )
    )

    assert result == "inserted"
    assert rag.process_calls == 1

    # Enqueue selected the paragraph-semantic chunker.
    (enqueue,) = rag.enqueue_calls
    assert enqueue["ids"] == [DOC_ID]
    assert enqueue["process_options"] == ["P"]

    # The sidecar exists and its blocks carry page positions.
    blocks_file = next((tmp_path / "report.parsed").glob("*.blocks.jsonl"))
    rows = [json.loads(line) for line in blocks_file.open(encoding="utf-8")]
    pages = {
        pos.get("anchor")
        for row in rows
        for pos in row.get("positions") or []
        if pos.get("type") == "bbox"
    }
    assert pages, "sidecar blocks carry no page positions"
    block_rows = [r for r in rows if r.get("blockid")]
    assert block_rows, "sidecar has no blockid rows"

    # full_docs was MERGED: enqueue's process_options survives alongside the
    # forged lightrag-format fields.
    row = rag.full_docs.records[DOC_ID]
    assert row["process_options"] == "P"
    assert row["parse_format"] == "lightrag"
    assert row["sidecar_location"].startswith("file://")
    assert row["sidecar_location"].endswith(".parsed/")
    assert row["content"].startswith("{{LRdoc}}")


@requires_sidecar
def test_duplicate_content_is_skipped_without_forging_state(tmp_path):
    rag = FakeLightRAG(duplicate=True)

    result = asyncio.run(
        insert_text_with_sidecar(
            rag,
            content_list=CONTENT_LIST,
            doc_id=DOC_ID,
            file_name="report.pdf",
            document_name="report.pdf",
            sidecar_parent_dir=tmp_path,
        )
    )

    assert result == "duplicate"
    assert rag.full_docs.records == {}
    assert rag.process_calls == 0


# ---------------------------------------------------------------------------
# Processor wiring: opt-in flag routes to the sidecar helper, and every
# non-happy path falls back to plain insertion.
# ---------------------------------------------------------------------------

from raganything.processor import ProcessorMixin  # noqa: E402


class RecordingLightRAG(FakeKV):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.doc_status = FakeKV()

    async def ainsert(self, **kwargs):
        self.events.append(("ainsert", kwargs["ids"]))
        await self.doc_status.upsert(
            {
                kwargs["ids"]: {
                    "status": "processed",
                    "file_path": kwargs["file_paths"],
                }
            }
        )


class DummyProcessor(ProcessorMixin):
    def __init__(self, *, provenance: bool):
        self.events = []
        self.lightrag = RecordingLightRAG(self.events)
        self.logger = SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            debug=lambda *a, **k: None,
        )
        self.config = SimpleNamespace(
            content_format="mineru",
            display_content_stats=False,
            parse_method="auto",
            parser_output_dir="./output",
            use_full_path=False,
            preserve_page_provenance=provenance,
        )
        self.callback_manager = None

    async def _ensure_lightrag_initialized(self):
        return {"success": True}

    async def parse_document(
        self, file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return (
            [{"type": "text", "text": "prose on page three", "page_idx": 3}],
            DOC_ID,
        )

    async def _process_multimodal_content(self, multimodal_items, file_ref, doc_id):
        self.events.append(("multimodal", doc_id))


def _run(processor, **kwargs):
    return asyncio.run(processor.process_document_complete("/tmp/report.pdf", **kwargs))


def test_processor_routes_to_sidecar_when_opted_in(monkeypatch, tmp_path):
    import raganything.sidecar_ingest as si

    calls = []

    async def fake_insert(lightrag, **kwargs):
        calls.append(kwargs)
        await lightrag.doc_status.upsert({kwargs["doc_id"]: {"status": "processed"}})
        return "inserted"

    monkeypatch.setattr(si, "insert_text_with_sidecar", fake_insert)
    monkeypatch.setattr(si, "sidecar_available", lambda: True)

    processor = DummyProcessor(provenance=True)
    _run(processor, output_dir=str(tmp_path))

    assert len(calls) == 1
    assert calls[0]["doc_id"] == DOC_ID
    assert calls[0]["document_name"] == "report.pdf"
    assert ("ainsert", DOC_ID) not in processor.events


def test_processor_falls_back_when_sidecar_raises(monkeypatch, tmp_path):
    import raganything.sidecar_ingest as si

    async def broken_insert(lightrag, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(si, "insert_text_with_sidecar", broken_insert)
    monkeypatch.setattr(si, "sidecar_available", lambda: True)

    processor = DummyProcessor(provenance=True)
    _run(processor, output_dir=str(tmp_path))

    assert ("ainsert", DOC_ID) in processor.events


def test_processor_falls_back_when_sidecar_unavailable(monkeypatch, tmp_path):
    import raganything.sidecar_ingest as si

    monkeypatch.setattr(si, "sidecar_available", lambda: False)

    processor = DummyProcessor(provenance=True)
    _run(processor, output_dir=str(tmp_path))

    assert ("ainsert", DOC_ID) in processor.events


def test_custom_split_bypasses_sidecar(monkeypatch, tmp_path):
    import raganything.sidecar_ingest as si

    async def fake_insert(lightrag, **kwargs):
        raise AssertionError("sidecar path must not run with a custom split")

    monkeypatch.setattr(si, "insert_text_with_sidecar", fake_insert)
    monkeypatch.setattr(si, "sidecar_available", lambda: True)

    processor = DummyProcessor(provenance=True)
    _run(processor, output_dir=str(tmp_path), split_by_character="\n")

    assert ("ainsert", DOC_ID) in processor.events


def test_flag_off_keeps_plain_insertion(monkeypatch, tmp_path):
    import raganything.sidecar_ingest as si

    async def fake_insert(lightrag, **kwargs):
        raise AssertionError("sidecar path must not run when flag is off")

    monkeypatch.setattr(si, "insert_text_with_sidecar", fake_insert)

    processor = DummyProcessor(provenance=False)
    _run(processor, output_dir=str(tmp_path))

    assert ("ainsert", DOC_ID) in processor.events
