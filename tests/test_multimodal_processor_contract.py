import importlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


@dataclass
class FakeLightRAG:
    text_chunks: object = None
    chunks_vdb: object = None
    entities_vdb: object = None
    relationships_vdb: object = None
    chunk_entity_relation_graph: object = None
    embedding_func: object = None
    llm_model_func: object = None
    llm_response_cache: object = None
    tokenizer: object = None
    working_dir: str = "workdir"

    def _build_global_config(self):
        return {"working_dir": self.working_dir}


@pytest.fixture
def modalprocessors(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]

    raganything_package = types.ModuleType("raganything")
    raganything_package.__path__ = [str(repo_root / "raganything")]

    lightrag_package = types.ModuleType("lightrag")

    utils_module = types.ModuleType("lightrag.utils")
    utils_module.logger = FakeLogger()
    utils_module.compute_mdhash_id = lambda value, prefix="": f"{prefix}hash"

    lightrag_module = types.ModuleType("lightrag.lightrag")
    lightrag_module.LightRAG = FakeLightRAG

    kg_package = types.ModuleType("lightrag.kg")
    shared_storage_module = types.ModuleType("lightrag.kg.shared_storage")
    shared_storage_module.get_namespace_data = lambda *args, **kwargs: {}
    shared_storage_module.get_pipeline_status_lock = lambda *args, **kwargs: None

    operate_module = types.ModuleType("lightrag.operate")
    operate_module.extract_entities = None
    operate_module.merge_nodes_and_edges = None

    for module_name in [
        "raganything",
        "raganything.prompt",
        "raganything.utils",
        "raganything.modalprocessors",
    ]:
        sys.modules.pop(module_name, None)

    monkeypatch.setitem(sys.modules, "raganything", raganything_package)
    monkeypatch.setitem(sys.modules, "lightrag", lightrag_package)
    monkeypatch.setitem(sys.modules, "lightrag.utils", utils_module)
    monkeypatch.setitem(sys.modules, "lightrag.lightrag", lightrag_module)
    monkeypatch.setitem(sys.modules, "lightrag.kg", kg_package)
    monkeypatch.setitem(
        sys.modules, "lightrag.kg.shared_storage", shared_storage_module
    )
    monkeypatch.setitem(sys.modules, "lightrag.operate", operate_module)

    module = importlib.import_module("raganything.modalprocessors")
    yield module

    for module_name in [
        "raganything.prompt",
        "raganything.utils",
        "raganything.modalprocessors",
    ]:
        sys.modules.pop(module_name, None)


PROCESSOR_CASES = [
    (
        "ImageModalProcessor",
        "image",
        {"img_path": "image.png", "image_caption": ["caption"]},
    ),
    (
        "TableModalProcessor",
        "table",
        {"table_body": "| a | b |", "table_caption": ["caption"]},
    ),
    (
        "EquationModalProcessor",
        "equation",
        {"text": "x + y = 1", "text_format": "latex"},
    ),
    ("GenericModalProcessor", "chart", {"content": "chart data"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processor_name", "content_type", "modal_content"), PROCESSOR_CASES
)
async def test_public_processor_success_returns_three_values(
    modalprocessors,
    processor_name,
    content_type,
    modal_content,
):
    processor_class = getattr(modalprocessors, processor_name)
    processor = processor_class.__new__(processor_class)

    entity_info = {
        "entity_name": "entity",
        "entity_type": content_type,
        "summary": "summary",
    }
    expected = (
        "stored content",
        {"entity_name": "entity", "entity_type": content_type},
        [("nodes", "edges")],
    )

    async def generate_description_only(*args, **kwargs):
        return "enhanced caption", entity_info

    async def create_entity_and_chunk(*args, **kwargs):
        return expected

    processor.generate_description_only = generate_description_only
    processor._create_entity_and_chunk = create_entity_and_chunk

    result = await processor.process_multimodal_content(
        modal_content=modal_content,
        content_type=content_type,
    )

    assert len(result) == 3
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processor_name", "content_type", "modal_content"), PROCESSOR_CASES
)
async def test_public_processor_fallback_returns_three_values(
    modalprocessors,
    processor_name,
    content_type,
    modal_content,
):
    processor_class = getattr(modalprocessors, processor_name)
    processor = processor_class.__new__(processor_class)

    async def fail_description(*args, **kwargs):
        raise RuntimeError("forced public fallback")

    processor.generate_description_only = fail_description

    result = await processor.process_multimodal_content(
        modal_content=modal_content,
        content_type=content_type,
    )

    assert len(result) == 3
    assert result[0] == str(modal_content)
    assert result[1]["entity_type"] == content_type
    assert result[2] is None
