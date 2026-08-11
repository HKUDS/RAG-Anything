"""Tests for process_document_complete_lightrag_api doc_status handling (#328).

The method pre-registered the content doc_id before handing the text to
LightRAG, so LightRAG's dedup (filter_keys over doc_status) treated the
fresh insert as a historical duplicate and skipped indexing entirely —
same mechanism as #277, fixed for insert_content_list in #278.

Uses the same fake-LightRAG harness as tests/test_insert_content_list.py,
extended with the pipeline_status shared storage this method touches.
"""

from types import SimpleNamespace
from pathlib import Path
import asyncio
import sys
import types


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

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
    fake_lightrag_utils.logger = FakeLogger()
    sys.modules["lightrag"] = fake_lightrag
    sys.modules["lightrag.utils"] = fake_lightrag_utils

    fake_raganything = types.ModuleType("raganything")
    fake_raganything.__path__ = [
        str(Path(__file__).resolve().parents[1] / "raganything")
    ]
    sys.modules["raganything"] = fake_raganything


try:
    from raganything.base import DocStatus
    from raganything.processor import ProcessorMixin
except ModuleNotFoundError as exc:
    if exc.name != "lightrag":
        raise
    for module_name in list(sys.modules):
        if module_name == "raganything" or module_name.startswith("raganything."):
            sys.modules.pop(module_name, None)
    _install_minimal_lightrag_stubs()
    from raganything.base import DocStatus  # noqa: E402
    from raganything.processor import ProcessorMixin  # noqa: E402


def _install_fake_shared_storage():
    """The method imports pipeline-status helpers inside its body; give it
    an isolated in-memory implementation regardless of what is installed."""
    fake = types.ModuleType("lightrag.kg.shared_storage")
    pipeline_status = {"history_messages": []}

    async def get_namespace_data(namespace):
        assert namespace == "pipeline_status"
        return pipeline_status

    fake.get_namespace_data = get_namespace_data
    fake.get_pipeline_status_lock = lambda: asyncio.Lock()
    fake_kg = types.ModuleType("lightrag.kg")
    fake_kg.shared_storage = fake
    sys.modules["lightrag.kg"] = fake_kg
    sys.modules["lightrag.kg.shared_storage"] = fake


_install_fake_shared_storage()


class FakeDocStatus:
    def __init__(self, events):
        self.records = {}
        self.events = events

    async def get_by_id(self, doc_id):
        return self.records.get(doc_id)

    async def upsert(self, payload):
        for doc_id, record in payload.items():
            self.events.append(("doc_status", doc_id, record.get("status")))
            self.records[doc_id] = record

    async def index_done_callback(self):
        pass


class FakeLightRAG:
    """Emulates LightRAG's duplicate check: an id already present in
    doc_status is treated as a historical duplicate and NOT indexed —
    the mechanism behind #277/#328."""

    def __init__(self, events):
        self.events = events
        self.doc_status = FakeDocStatus(events)

    async def ainsert(self, **kwargs):
        doc_id = kwargs["ids"]
        if await self.doc_status.get_by_id(doc_id):
            self.events.append(("duplicate_skipped", doc_id))
            return

        self.events.append(("ainsert", doc_id, kwargs["input"]))
        await self.doc_status.upsert(
            {
                doc_id: {
                    "status": DocStatus.PROCESSED,
                    "content": kwargs["input"],
                    "content_summary": "",
                    "content_length": len(kwargs["input"]),
                    "error_msg": "",
                    "chunks_count": 1,
                    "chunks_list": ["chunk-1"],
                    "created_at": "",
                    "updated_at": "",
                    "file_path": kwargs["file_paths"],
                }
            }
        )


class DummyProcessor(ProcessorMixin):
    def __init__(self):
        self.events = []
        self.lightrag = FakeLightRAG(self.events)
        self.logger = FakeLogger()
        self.config = SimpleNamespace(
            content_format="mineru",
            display_content_stats=False,
            parse_method="auto",
            parser_output_dir="./output",
            use_full_path=False,
            parser="mineru",
        )
        self.callback_manager = None
        self.parsed_content_list = []

    async def _ensure_lightrag_initialized(self):
        return {"success": True}

    async def parse_document(
        self, file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return self.parsed_content_list, "doc-api"


def test_text_content_is_indexed_not_skipped_as_duplicate():
    processor = DummyProcessor()
    processor.parsed_content_list = [
        {"type": "text", "text": "hello from the lightrag api path", "page_idx": 0}
    ]

    result = asyncio.run(
        processor.process_document_complete_lightrag_api("/tmp/source.pdf")
    )

    assert result is True
    assert ("ainsert", "doc-api", "hello from the lightrag api path") in (
        processor.events
    )
    assert ("duplicate_skipped", "doc-api") not in processor.events
    assert processor.lightrag.doc_status.records["doc-api"]["status"] == (
        DocStatus.PROCESSED
    )


def test_real_doc_id_is_not_registered_before_ainsert():
    processor = DummyProcessor()
    processor.parsed_content_list = [
        {"type": "text", "text": "ordering matters", "page_idx": 0}
    ]

    asyncio.run(processor.process_document_complete_lightrag_api("/tmp/source.pdf"))

    doc_api_events = [
        e
        for e in processor.events
        if e[0] in ("doc_status", "ainsert") and e[1] == "doc-api"
    ]
    assert doc_api_events[0][0] == "ainsert", doc_api_events


def test_multimodal_only_content_still_registers_status_up_front():
    processor = DummyProcessor()
    processor.parsed_content_list = [
        {"type": "image", "img_path": "/tmp/image.png", "page_idx": 0}
    ]

    result = asyncio.run(
        processor.process_document_complete_lightrag_api("/tmp/source.pdf")
    )

    assert result is True
    assert processor.lightrag.doc_status.records["doc-api"]["status"] == (
        DocStatus.HANDLING
    )


def test_doc_pre_record_timestamps_are_never_empty():
    # Backends that map created_at as a date reject "" — and LightRAG's
    # bulk upsert drops the rejected write silently (#328).
    processor = DummyProcessor()
    processor.parsed_content_list = [
        {"type": "text", "text": "timestamps", "page_idx": 0}
    ]

    asyncio.run(processor.process_document_complete_lightrag_api("/tmp/source.pdf"))

    pre_record = processor.lightrag.doc_status.records["doc-pre-source.pdf"]
    assert pre_record["created_at"], "created_at must be a real timestamp"
    assert pre_record["updated_at"], "updated_at must be a real timestamp"


def test_initialization_failure_record_timestamps_are_never_empty():
    processor = DummyProcessor()

    async def failing_init():
        return {"success": False, "error": "boom"}

    processor._ensure_lightrag_initialized = failing_init

    result = asyncio.run(
        processor.process_document_complete_lightrag_api("/tmp/source.pdf")
    )

    assert result is False
    failed = processor.lightrag.doc_status.records["doc-pre-source.pdf"]
    assert failed["status"] == DocStatus.FAILED
    assert failed["created_at"], "created_at must be a real timestamp"
