import importlib.util
import sys
import types
from pathlib import Path

import pytest


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


@pytest.mark.asyncio
async def test_insert_text_content_with_multimodal_falls_back_for_old_lightrag(
    raganything_modules,
):
    calls = []

    class FakeLightRAG:
        async def ainsert(
            self,
            *,
            input,
            file_paths=None,
            split_by_character=None,
            split_by_character_only=False,
            ids=None,
        ):
            calls.append(
                {
                    "input": input,
                    "file_paths": file_paths,
                    "split_by_character": split_by_character,
                    "split_by_character_only": split_by_character_only,
                    "ids": ids,
                }
            )

    await raganything_modules.utils.insert_text_content_with_multimodal_content(
        FakeLightRAG(),
        input="hello world",
        multimodal_content=[{"type": "image"}],
        file_paths="sample.pdf",
        ids="doc-compat",
        scheme_name="test-scheme",
    )

    assert calls == [
        {
            "input": "hello world",
            "file_paths": "sample.pdf",
            "split_by_character": None,
            "split_by_character_only": False,
            "ids": "doc-compat",
        }
    ]


@pytest.mark.asyncio
async def test_process_document_complete_bootstraps_doc_status(
    raganything_modules,
    tmp_path,
):
    processor_module = raganything_modules.processor
    DocStatus = raganything_modules.base.DocStatus

    class FakeDocStatusStorage:
        def __init__(self):
            self.records = {}

        async def get_by_id(self, key):
            return self.records.get(key)

        async def upsert(self, data):
            for key, value in data.items():
                self.records[key] = value

        async def index_done_callback(self):
            return None

    class FakeLightRAG:
        def __init__(self):
            self.doc_status = FakeDocStatusStorage()

        async def ainsert(self, **kwargs):
            return None

    class DummyProcessor(processor_module.ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.lightrag = FakeLightRAG()
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
        return (
            [{"type": "text", "text": "hello from test", "page_idx": 0}],
            "doc-generated",
        )

    processor._ensure_lightrag_initialized = fake_ensure_lightrag_initialized
    processor.parse_document = fake_parse_document

    await processor.process_document_complete(
        file_path=str(tmp_path / "sample.pdf"),
        doc_id="doc-custom",
        file_name="sample.pdf",
    )

    doc_status = processor.lightrag.doc_status.records["doc-custom"]
    assert doc_status["file_path"] == "sample.pdf"
    assert doc_status["status"] == DocStatus.PROCESSED
    assert doc_status["multimodal_processed"] is True


@pytest.mark.asyncio
async def test_image_only_document_falls_back_when_multimodal_flag_is_unsupported(
    raganything_modules,
    tmp_path,
):
    processor_module = raganything_modules.processor
    DocStatus = raganything_modules.base.DocStatus

    class FakeDocStatusStorage:
        def __init__(self):
            self.records = {}

        async def get_by_id(self, key):
            return self.records.get(key)

        async def upsert(self, data):
            for key, value in data.items():
                if "multimodal_processed" in value:
                    raise ValueError("unknown field: multimodal_processed")
                self.records[key] = value

        async def index_done_callback(self):
            return None

    class FakeLightRAG:
        def __init__(self):
            self.doc_status = FakeDocStatusStorage()

        async def ainsert(self, **kwargs):
            return None

    class DummyProcessor(processor_module.ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.lightrag = FakeLightRAG()
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

    async def fake_process_multimodal_content(multimodal_items, file_name, doc_id):
        await processor._mark_multimodal_processing_complete(doc_id)

    processor._ensure_lightrag_initialized = fake_ensure_lightrag_initialized
    processor.parse_document = fake_parse_document
    processor._process_multimodal_content = fake_process_multimodal_content

    await processor.process_document_complete(
        file_path=str(tmp_path / "figure.png"),
        doc_id="doc-image",
        file_name="figure.png",
    )

    doc_status = processor.lightrag.doc_status.records["doc-image"]
    assert doc_status["file_path"] == "figure.png"
    assert doc_status["status"] == DocStatus.PROCESSED
    assert "multimodal_processed" not in doc_status
    assert processor.multimodal_status_cache.records["doc-image"] == {
        "multimodal_processed": True,
        "updated_at": doc_status["updated_at"],
    }

    processing_status = await processor.get_document_processing_status("doc-image")
    assert processing_status["multimodal_processed"] is True
    assert processing_status["fully_processed"] is True
    assert await processor.is_document_fully_processed("doc-image") is True


@pytest.mark.asyncio
async def test_compatibility_multimodal_cache_prevents_repeat_processing(
    raganything_modules,
):
    processor_module = raganything_modules.processor
    DocStatus = raganything_modules.base.DocStatus

    class FakeDocStatusStorage:
        def __init__(self):
            self.records = {
                "doc-image": {
                    "status": DocStatus.PROCESSED,
                    "file_path": "figure.png",
                }
            }

        async def get_by_id(self, key):
            return self.records.get(key)

    class FakeMultimodalStatusStorage:
        def __init__(self):
            self.records = {
                "doc-image": {
                    "multimodal_processed": True,
                    "updated_at": "2026-04-22T00:00:00+00:00",
                }
            }

        async def get_by_id(self, key):
            return self.records.get(key)

    class FakeLightRAG:
        def __init__(self):
            self.doc_status = FakeDocStatusStorage()

    class DummyProcessor(processor_module.ProcessorMixin):
        pass

    processor = DummyProcessor()
    processor.lightrag = FakeLightRAG()
    processor.multimodal_status_cache = FakeMultimodalStatusStorage()
    processor.logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    processor.callback_manager = None

    async def fake_ensure_lightrag_initialized():
        return {"success": True}

    called = {"batch": 0}

    async def fake_batch_type_aware(*args, **kwargs):
        called["batch"] += 1

    processor._ensure_lightrag_initialized = fake_ensure_lightrag_initialized
    processor._process_multimodal_content_batch_type_aware = fake_batch_type_aware

    await processor._process_multimodal_content(
        [{"type": "image", "img_path": "figure.png"}],
        "figure.png",
        "doc-image",
    )

    assert called["batch"] == 0
