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
    def __init__(self, events):
        self.events = events
        self.doc_status = FakeDocStatus(events)

    async def ainsert(self, **kwargs):
        doc_id = kwargs["ids"]
        if await self.doc_status.get_by_id(doc_id):
            raise AssertionError("doc_status existed before LightRAG insertion")

        self.events.append(("ainsert", doc_id, kwargs["input"]))
        await self.doc_status.upsert(
            {
                doc_id: {
                    "status": DocStatus.PROCESSED,
                    "content": kwargs["input"],
                    "content_summary": "",
                    "content_length": len(kwargs["input"]),
                    "error_msg": "",
                    "chunks_count": 0,
                    "chunks_list": [],
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
        )
        self.callback_manager = None
        self.parsed_content_list = []

    async def _ensure_lightrag_initialized(self):
        return {"success": True}

    async def parse_document(
        self, file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return self.parsed_content_list, "doc-complete"

    def _generate_content_based_doc_id(self, content_list):
        return "doc-content-list"

    async def _process_multimodal_content(self, multimodal_items, file_ref, doc_id):
        self.events.append(("multimodal", doc_id, file_ref))


def test_insert_content_list_defers_status_until_after_text_insert():
    processor = DummyProcessor()

    asyncio.run(
        processor.insert_content_list(
            [{"type": "text", "text": "hello from content list", "page_idx": 0}],
            file_path="/tmp/source.pdf",
        )
    )

    assert processor.events[0] == (
        "ainsert",
        "doc-content-list",
        "hello from content list",
    )
    assert processor.lightrag.doc_status.records["doc-content-list"]["status"] == (
        DocStatus.PROCESSED
    )
    assert (
        processor.lightrag.doc_status.records["doc-content-list"][
            "multimodal_processed"
        ]
        is True
    )


def test_process_document_complete_defers_status_until_after_text_insert():
    processor = DummyProcessor()
    processor.parsed_content_list = [
        {"type": "text", "text": "hello from parsed document", "page_idx": 0}
    ]

    asyncio.run(processor.process_document_complete("/tmp/source.pdf"))

    assert processor.events[0] == (
        "ainsert",
        "doc-complete",
        "hello from parsed document",
    )
    assert processor.lightrag.doc_status.records["doc-complete"]["status"] == (
        DocStatus.PROCESSED
    )
    assert (
        processor.lightrag.doc_status.records["doc-complete"]["multimodal_processed"]
        is True
    )


def test_process_document_complete_keeps_status_for_multimodal_only_content():
    processor = DummyProcessor()
    processor.parsed_content_list = [
        {"type": "image", "img_path": "/tmp/image.png", "page_idx": 0}
    ]

    asyncio.run(processor.process_document_complete("/tmp/source.pdf"))

    assert processor.events[0] == ("doc_status", "doc-complete", DocStatus.READY)
    assert processor.events[1] == (
        "doc_status",
        "doc-complete",
        DocStatus.HANDLING,
    )
    assert processor.events[2] == ("multimodal", "doc-complete", "source.pdf")


def test_insert_content_list_keeps_status_for_multimodal_only_content():
    processor = DummyProcessor()

    asyncio.run(
        processor.insert_content_list(
            [{"type": "image", "img_path": "/tmp/image.png", "page_idx": 0}],
            file_path="/tmp/source.pdf",
        )
    )

    assert processor.events[0] == (
        "doc_status",
        "doc-content-list",
        DocStatus.READY,
    )
    assert processor.events[1] == (
        "doc_status",
        "doc-content-list",
        DocStatus.HANDLING,
    )
    # When an event loop is available, multimodal processing is scheduled as a
    # background task and doc_status transitions to PROCESSED immediately so
    # text chunks are searchable without waiting for VLM/LLM calls.
    assert processor.events[2] == (
        "doc_status",
        "doc-content-list",
        DocStatus.PROCESSED,
    )
