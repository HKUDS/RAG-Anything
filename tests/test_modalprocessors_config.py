import importlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path

# Import the real modules up front so every sys.modules key this file
# manipulates has a genuine cached entry for monkeypatch to record and
# restore — otherwise a key first imported inside the stubbed fixture
# would leak a stub-derived module into the rest of the session.
import raganything.modalprocessors  # noqa: F401  (imports .prompt and .utils too)


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

    def __post_init__(self):
        self.role_llm_funcs = {"default": object()}

    def _build_global_config(self):
        return {
            "working_dir": self.working_dir,
            "role_llm_funcs": self.role_llm_funcs,
        }


def _import_modalprocessors_with_lightrag_stubs(monkeypatch):
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

    # Remove cached modules THROUGH monkeypatch so teardown restores the
    # real entries. A bare sys.modules.pop() before setitem() made
    # monkeypatch record "absent" as the original value: its LIFO undo then
    # deleted the keys instead of restoring the real package, and every
    # test module imported afterwards got a fresh, stub-derived
    # `raganything` — which is why unrelated monkeypatch.setattr targets
    # (e.g. raganything.modalprocessors_video) vanished mid-session.
    for module_name in [
        "raganything",
        "raganything.prompt",
        "raganything.utils",
        "raganything.modalprocessors",
    ]:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    monkeypatch.setitem(sys.modules, "raganything", raganything_package)
    monkeypatch.setitem(sys.modules, "lightrag", lightrag_package)
    monkeypatch.setitem(sys.modules, "lightrag.utils", utils_module)
    monkeypatch.setitem(sys.modules, "lightrag.lightrag", lightrag_module)
    monkeypatch.setitem(sys.modules, "lightrag.kg", kg_package)
    monkeypatch.setitem(
        sys.modules, "lightrag.kg.shared_storage", shared_storage_module
    )
    monkeypatch.setitem(sys.modules, "lightrag.operate", operate_module)

    return importlib.import_module("raganything.modalprocessors")


def test_base_modal_processor_uses_lightrag_runtime_global_config(monkeypatch):
    # No manual cleanup: the fixture registers every sys.modules mutation
    # with monkeypatch, whose LIFO teardown restores the real modules.
    modalprocessors = _import_modalprocessors_with_lightrag_stubs(monkeypatch)
    lightrag = FakeLightRAG()

    processor = modalprocessors.BaseModalProcessor(
        lightrag=lightrag,
        modal_caption_func=lambda *args, **kwargs: "",
    )

    assert processor.global_config["working_dir"] == "workdir"
    assert processor.global_config["role_llm_funcs"] is lightrag.role_llm_funcs
