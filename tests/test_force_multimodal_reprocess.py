"""Tests for the opt-in force_multimodal_reprocess feature.

This flag lets callers explicitly re-run multimodal (image/table/equation)
processing for a document that was already marked complete, which is useful
after swapping the underlying graph/vector storage backend (see
https://github.com/HKUDS/RAG-Anything/issues/154). It defaults to False, so
existing callers see no behavior change.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InMemoryJsonStorage:
    def __init__(self, records=None):
        self.records = records or {}

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
    fake_lightrag_utils.compute_mdhash_id = lambda value, prefix="": (
        f"{prefix}{abs(hash(value))}"
    )

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


def _make_processor(processor_module, doc_status_records):
    class FakeDocStatusStorage:
        def __init__(self, records):
            self.records = records

        async def get_by_id(self, key):
            return self.records.get(key)

        async def upsert(self, data):
            for key, value in data.items():
                self.records[key] = value

        async def index_done_callback(self):
            return None

    class FakeLightRAG:
        def __init__(self, records):
            self.doc_status = FakeDocStatusStorage(records)

    class DummyProcessor(processor_module.ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.lightrag = FakeLightRAG(doc_status_records)
    processor.multimodal_status_cache = InMemoryJsonStorage()
    processor.logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    processor.callback_manager = None

    async def fake_ensure_lightrag_initialized():
        return {"success": True}

    processor._ensure_lightrag_initialized = fake_ensure_lightrag_initialized
    return processor


@pytest.mark.asyncio
async def test_default_behavior_still_skips_already_processed_document(
    raganything_modules,
):
    """Regression guard: without the new flag, nothing changes."""
    processor_module = raganything_modules.processor
    DocStatus = raganything_modules.base.DocStatus

    processor = _make_processor(
        processor_module,
        {
            "doc-image": {
                "status": DocStatus.PROCESSED,
                "multimodal_processed": True,
                "file_path": "figure.png",
            }
        },
    )

    called = {"batch": 0}

    async def fake_batch_type_aware(*args, **kwargs):
        called["batch"] += 1

    processor._process_multimodal_content_batch_type_aware = fake_batch_type_aware

    await processor._process_multimodal_content(
        [{"type": "image", "img_path": "figure.png"}],
        "figure.png",
        "doc-image",
    )

    assert called["batch"] == 0


@pytest.mark.asyncio
async def test_force_reprocess_bypasses_already_processed_check(raganything_modules):
    processor_module = raganything_modules.processor
    DocStatus = raganything_modules.base.DocStatus

    processor = _make_processor(
        processor_module,
        {
            "doc-image": {
                "status": DocStatus.PROCESSED,
                "multimodal_processed": True,
                "file_path": "figure.png",
            }
        },
    )

    called = {"batch": 0}

    async def fake_batch_type_aware(*args, **kwargs):
        called["batch"] += 1

    processor._process_multimodal_content_batch_type_aware = fake_batch_type_aware

    await processor._process_multimodal_content(
        [{"type": "image", "img_path": "figure.png"}],
        "figure.png",
        "doc-image",
        force_reprocess=True,
    )

    assert called["batch"] == 1
    # Reprocessing still (re)marks the document as complete.
    assert processor.lightrag.doc_status.records["doc-image"]["multimodal_processed"]


@pytest.mark.asyncio
async def test_process_document_complete_forwards_force_flag(
    raganything_modules, tmp_path
):
    processor_module = raganything_modules.processor

    processor = _make_processor(processor_module, {})
    processor.config = types.SimpleNamespace(
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
        content_format="default",
    )

    async def fake_parse_document(
        file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return (
            [
                {
                    "type": "image",
                    "img_path": str(tmp_path / "figure.png"),
                    "page_idx": 0,
                }
            ],
            "doc-image",
        )

    seen_kwargs = {}

    async def fake_process_multimodal_content(
        multimodal_items, file_name, doc_id, **kwargs
    ):
        seen_kwargs.update(kwargs)

    processor.parse_document = fake_parse_document
    processor._process_multimodal_content = fake_process_multimodal_content

    await processor.process_document_complete(
        file_path=str(tmp_path / "figure.png"),
        doc_id="doc-image",
        file_name="figure.png",
        force_multimodal_reprocess=True,
    )

    assert seen_kwargs == {"force_reprocess": True}


@pytest.mark.asyncio
async def test_process_document_complete_defaults_force_flag_to_false(
    raganything_modules, tmp_path
):
    processor_module = raganything_modules.processor

    processor = _make_processor(processor_module, {})
    processor.config = types.SimpleNamespace(
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
        content_format="default",
    )

    async def fake_parse_document(
        file_path, output_dir, parse_method, display_stats, **kwargs
    ):
        return (
            [
                {
                    "type": "image",
                    "img_path": str(tmp_path / "figure.png"),
                    "page_idx": 0,
                }
            ],
            "doc-image",
        )

    seen_kwargs = {}

    async def fake_process_multimodal_content(
        multimodal_items, file_name, doc_id, **kwargs
    ):
        seen_kwargs.update(kwargs)

    processor.parse_document = fake_parse_document
    processor._process_multimodal_content = fake_process_multimodal_content

    # force_multimodal_reprocess intentionally omitted here to prove the default
    # keeps callers that predate this feature working exactly as before.
    await processor.process_document_complete(
        file_path=str(tmp_path / "figure.png"),
        doc_id="doc-image",
        file_name="figure.png",
    )

    assert seen_kwargs == {"force_reprocess": False}


@pytest.mark.asyncio
async def test_insert_content_list_forwards_force_flag(raganything_modules, tmp_path):
    processor_module = raganything_modules.processor

    processor = _make_processor(processor_module, {})
    processor.config = types.SimpleNamespace(
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
        content_format="default",
    )

    seen_kwargs = {}

    async def fake_process_multimodal_content(
        multimodal_items, file_name, doc_id, **kwargs
    ):
        seen_kwargs.update(kwargs)

    processor._process_multimodal_content = fake_process_multimodal_content

    await processor.insert_content_list(
        content_list=[
            {
                "type": "image",
                "img_path": str(tmp_path / "figure.png"),
                "page_idx": 0,
            }
        ],
        file_path="figure.png",
        doc_id="doc-image",
        force_multimodal_reprocess=True,
    )

    assert seen_kwargs == {"force_reprocess": True}


@pytest.mark.asyncio
async def test_update_doc_status_with_chunks_deduplicates_ids(raganything_modules):
    """Re-running processing for the same doc must not duplicate chunk ids
    in chunks_list/chunks_count, since chunk ids are content-derived and
    therefore identical across a force_reprocess run."""
    processor_module = raganything_modules.processor

    processor = _make_processor(
        processor_module,
        {
            "doc-1": {
                "chunks_list": ["chunk-a", "chunk-b"],
                "chunks_count": 2,
            }
        },
    )

    # First-time-like call with a brand new chunk id: appended normally.
    await processor._update_doc_status_with_chunks_type_aware("doc-1", ["chunk-c"])
    record = processor.lightrag.doc_status.records["doc-1"]
    assert record["chunks_list"] == ["chunk-a", "chunk-b", "chunk-c"]
    assert record["chunks_count"] == 3

    # Re-running with the same (deterministic) chunk ids must not duplicate them.
    await processor._update_doc_status_with_chunks_type_aware(
        "doc-1", ["chunk-a", "chunk-b", "chunk-c"]
    )
    record = processor.lightrag.doc_status.records["doc-1"]
    assert record["chunks_list"] == ["chunk-a", "chunk-b", "chunk-c"]
    assert record["chunks_count"] == 3
