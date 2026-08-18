from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from lightrag import operate
from lightrag.kg import shared_storage

from raganything.processor import ProcessorMixin


class FakeLogger:
    def debug(self, *args, **kwargs):
        del args, kwargs

    def error(self, *args, **kwargs):
        del args, kwargs

    def info(self, *args, **kwargs):
        del args, kwargs

    def warning(self, *args, **kwargs):
        del args, kwargs


class FakeDocStatus:
    async def get_by_id(self, doc_id):
        del doc_id
        return {"chunks_count": 0}


class FakeModalProcessor:
    async def process_multimodal_content(self, **kwargs):
        del kwargs
        return "caption", {"chunk_id": "chunk-1", "entity_name": "entity"}, [([], {})]


class FakeRuntimeLightRAG:
    def __init__(self):
        self._builder_calls = 0
        self._builder_results = []
        self._llm_cache_identities = {"default": "cache-identity"}
        self._role_llm_funcs = {"default": lambda: "runtime-role"}
        self.chunk_entity_relation_graph = SimpleNamespace()
        self.doc_status = FakeDocStatus()
        self.entities_vdb = SimpleNamespace()
        self.entity_chunks = SimpleNamespace()
        self.full_entities = SimpleNamespace()
        self.full_relations = SimpleNamespace()
        self.llm_response_cache = SimpleNamespace()
        self.relation_chunks = SimpleNamespace()
        self.relationships_vdb = SimpleNamespace()
        self.text_chunks = SimpleNamespace()

    def _build_global_config(self):
        self._builder_calls += 1
        config = {
            "llm_cache_identities": self._llm_cache_identities,
            "role_llm_funcs": self._role_llm_funcs,
        }
        self._builder_results.append(config)
        return config

    async def _insert_done(self):
        return None


class FakeProcessor(ProcessorMixin):
    def __init__(self, lightrag):
        self.config = SimpleNamespace(use_full_path=False)
        self.lightrag = lightrag
        self.logger = FakeLogger()
        self.modal_processors = {"image": FakeModalProcessor()}

    async def _mark_multimodal_processing_complete(self, doc_id):
        del doc_id

    async def _update_doc_status_with_chunks_type_aware(self, doc_id, chunk_ids):
        del doc_id, chunk_ids


async def fake_get_namespace_data(namespace):
    del namespace
    return {"history_messages": []}


def configure_shared_storage(monkeypatch):
    monkeypatch.setattr(shared_storage, "get_namespace_data", fake_get_namespace_data)
    monkeypatch.setattr(shared_storage, "get_pipeline_status_lock", lambda: None)


def assert_builder_config(captured_config, lightrag):
    assert "role_llm_funcs" in captured_config
    assert "llm_cache_identities" in captured_config
    assert "role_llm_funcs" not in lightrag.__dict__
    assert "llm_cache_identities" not in lightrag.__dict__
    assert captured_config is lightrag._builder_results[0]
    assert captured_config is not lightrag.__dict__
    assert captured_config["role_llm_funcs"] is lightrag._role_llm_funcs
    assert captured_config["llm_cache_identities"] is lightrag._llm_cache_identities
    assert lightrag._builder_calls == 1


@pytest.mark.asyncio
async def test_individual_consumer_uses_fresh_runtime_global_config(monkeypatch):
    configure_shared_storage(monkeypatch)
    captured_configs = []

    async def fake_merge_nodes_and_edges(**kwargs):
        captured_configs.append(kwargs["global_config"])

    monkeypatch.setattr(operate, "merge_nodes_and_edges", fake_merge_nodes_and_edges)
    lightrag = FakeRuntimeLightRAG()
    processor = FakeProcessor(lightrag)

    await processor._process_multimodal_content_individual(
        [{"type": "image", "page_idx": 0}], "individual.pdf", "doc-1"
    )

    assert_builder_config(captured_configs[0], lightrag)


@pytest.mark.asyncio
async def test_batch_extract_consumer_uses_fresh_runtime_global_config(monkeypatch):
    configure_shared_storage(monkeypatch)
    captured_configs = []

    async def fake_extract_entities(**kwargs):
        captured_configs.append(kwargs["global_config"])
        return []

    monkeypatch.setattr(operate, "extract_entities", fake_extract_entities)
    lightrag = FakeRuntimeLightRAG()
    processor = FakeProcessor(lightrag)

    result = await processor._batch_extract_entities_lightrag_style_type_aware(
        {"chunk-1": {}}
    )

    assert result == []
    assert_builder_config(captured_configs[0], lightrag)


@pytest.mark.asyncio
async def test_batch_merge_consumer_uses_fresh_runtime_global_config(monkeypatch):
    configure_shared_storage(monkeypatch)
    captured_configs = []

    async def fake_merge_nodes_and_edges(**kwargs):
        captured_configs.append(kwargs["global_config"])

    monkeypatch.setattr(operate, "merge_nodes_and_edges", fake_merge_nodes_and_edges)
    lightrag = FakeRuntimeLightRAG()
    processor = FakeProcessor(lightrag)

    await processor._batch_merge_lightrag_style_type_aware([], "batch.pdf", "doc-1")

    assert_builder_config(captured_configs[0], lightrag)


def test_global_config_builder_returns_a_new_mapping_per_call():
    lightrag = FakeRuntimeLightRAG()
    processor = FakeProcessor(lightrag)

    first_config = processor._get_lightrag_global_config()
    second_config = processor._get_lightrag_global_config()

    assert first_config is not second_config
    assert lightrag._builder_calls == 2


@dataclass
class FallbackLightRAG:
    working_dir: str


def test_global_config_builder_falls_back_to_dataclass_fields():
    processor = FakeProcessor(FallbackLightRAG(working_dir="workdir"))

    config = processor._get_lightrag_global_config()

    assert config == {"working_dir": "workdir"}


class BuilderError(Exception):
    pass


class RaisingLightRAG(FakeRuntimeLightRAG):
    def _build_global_config(self):
        raise BuilderError("sentinel")


def test_global_config_builder_propagates_builder_error():
    processor = FakeProcessor(RaisingLightRAG())

    with pytest.raises(BuilderError, match="sentinel"):
        processor._get_lightrag_global_config()
