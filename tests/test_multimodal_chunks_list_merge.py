"""Tests for merging multimodal chunk ids into doc_status chunks_list (#332).

The merge helper must tolerate reprocessing (content-hashed chunk ids come
back identical, so a blind append duplicates them) and must surface — not
silently swallow — the case where the doc_status record is absent.
"""

from types import SimpleNamespace
from pathlib import Path
import asyncio
import sys
import types


class RecordingLogger:
    def __init__(self):
        self.warnings = []

    def info(self, *args, **kwargs):
        pass

    def warning(self, message, *args, **kwargs):
        self.warnings.append(message)

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _install_minimal_lightrag_stubs():
    fake_lightrag = types.ModuleType("lightrag")
    fake_lightrag.LightRAG = object
    fake_lightrag_utils = types.ModuleType("lightrag.utils")
    fake_lightrag_utils.compute_mdhash_id = lambda content, prefix="": f"{prefix}fake"
    fake_lightrag_utils.get_env_value = (
        lambda key, default=None, value_type=str: default
    )
    fake_lightrag_utils.logger = RecordingLogger()
    sys.modules["lightrag"] = fake_lightrag
    sys.modules["lightrag.utils"] = fake_lightrag_utils

    fake_raganything = types.ModuleType("raganything")
    fake_raganything.__path__ = [
        str(Path(__file__).resolve().parents[1] / "raganything")
    ]
    sys.modules["raganything"] = fake_raganything


try:
    from raganything.processor import ProcessorMixin
except ModuleNotFoundError as exc:
    if exc.name != "lightrag":
        raise
    for module_name in list(sys.modules):
        if module_name == "raganything" or module_name.startswith("raganything."):
            sys.modules.pop(module_name, None)
    _install_minimal_lightrag_stubs()
    from raganything.processor import ProcessorMixin  # noqa: E402


class FakeDocStatus:
    def __init__(self):
        self.records = {}

    async def get_by_id(self, doc_id):
        return self.records.get(doc_id)

    async def upsert(self, payload):
        self.records.update(payload)

    async def index_done_callback(self):
        pass


class DummyProcessor(ProcessorMixin):
    def __init__(self):
        self.lightrag = SimpleNamespace(doc_status=FakeDocStatus())
        self.logger = RecordingLogger()
        self.config = SimpleNamespace(use_full_path=False)


def _record(chunks_list, chunks_count=None):
    return {
        "status": "processed",
        "chunks_list": list(chunks_list),
        "chunks_count": len(chunks_list) if chunks_count is None else chunks_count,
        "file_path": "doc.pdf",
    }


def test_merge_appends_new_chunk_ids_and_updates_count():
    processor = DummyProcessor()
    processor.lightrag.doc_status.records["doc-1"] = _record(["chunk-a", "chunk-b"])

    asyncio.run(
        processor._update_doc_status_with_chunks_type_aware(
            "doc-1", ["chunk-m1", "chunk-m2"]
        )
    )

    record = processor.lightrag.doc_status.records["doc-1"]
    assert record["chunks_list"] == ["chunk-a", "chunk-b", "chunk-m1", "chunk-m2"]
    assert record["chunks_count"] == 4


def test_reprocessing_same_ids_does_not_duplicate():
    processor = DummyProcessor()
    processor.lightrag.doc_status.records["doc-1"] = _record(["chunk-a"])

    for _ in range(3):
        asyncio.run(
            processor._update_doc_status_with_chunks_type_aware("doc-1", ["chunk-m1"])
        )

    record = processor.lightrag.doc_status.records["doc-1"]
    assert record["chunks_list"] == ["chunk-a", "chunk-m1"]
    assert record["chunks_count"] == 2


def test_partial_overlap_appends_only_missing_ids():
    processor = DummyProcessor()
    processor.lightrag.doc_status.records["doc-1"] = _record(["chunk-a", "chunk-m1"])

    asyncio.run(
        processor._update_doc_status_with_chunks_type_aware(
            "doc-1", ["chunk-m1", "chunk-m2"]
        )
    )

    record = processor.lightrag.doc_status.records["doc-1"]
    assert record["chunks_list"] == ["chunk-a", "chunk-m1", "chunk-m2"]
    assert record["chunks_count"] == 3


def test_missing_record_warns_instead_of_silently_skipping():
    processor = DummyProcessor()

    asyncio.run(
        processor._update_doc_status_with_chunks_type_aware("doc-absent", ["chunk-m1"])
    )

    assert processor.lightrag.doc_status.records == {}
    assert any(
        "doc-absent" in message for message in processor.logger.warnings
    ), processor.logger.warnings
