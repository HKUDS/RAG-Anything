import math
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_embedding_preflight_calls_raw_provider_and_validates_vector(monkeypatch):
    import process_worker

    calls = []

    async def raw_provider(texts, **_kwargs):
        calls.append(texts)
        return [[0.5] * process_worker.EMB_DIM]

    async def cached_provider(*_args, **_kwargs):
        raise AssertionError("preflight must bypass the cache")

    rag = SimpleNamespace(
        _raw_embedding_provider=raw_provider,
        embedding_func=SimpleNamespace(func=cached_provider),
    )
    monkeypatch.setenv("MODEL_PREFLIGHT_ENABLED", "true")
    await process_worker._preflight_embedding_service(rag)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vector,error",
    [
        ([1.0], "dimension mismatch"),
        ([float("nan")] * 1024, "non-finite"),
        ([0.0] * 1024, "zero-norm"),
    ],
)
async def test_embedding_preflight_rejects_invalid_vectors(monkeypatch, vector, error):
    import process_worker

    async def raw_provider(_texts, **_kwargs):
        return [vector]

    monkeypatch.setenv("MODEL_PREFLIGHT_ENABLED", "true")
    rag = SimpleNamespace(_raw_embedding_provider=raw_provider)
    with pytest.raises(RuntimeError, match=error):
        await process_worker._preflight_embedding_service(rag)


def test_structured_worker_error_wins_over_finalize_noise():
    from raganything.services.kb_service import _parse_worker_error

    lines = [
        'WORKER_ERROR_JSON {"stage":"model_preflight","root_type":"APIConnectionError",'
        '"retryable":true,"message":"connection failed","secondary":["finalize failed"]}',
        "Failed to finalize doc_status: NoneType.send",
    ]
    result = _parse_worker_error(lines, 4)
    assert result["message"] == "connection failed"
    assert result["stage"] == "model_preflight"
    assert result["retryable"] is True


@pytest.mark.parametrize("returncode", [3221225477, -1073741819])
def test_native_access_violation_is_classified(returncode):
    from raganything.services.kb_service import _parse_worker_error

    result = _parse_worker_error([], returncode)
    assert result["stage"] == "native_crash"
    assert "0xC0000005" in result["message"]


def test_retry_backoff_defaults():
    from raganything.services.upload_retry import retry_delay_seconds

    assert [retry_delay_seconds(i, jitter=1.0) for i in range(1, 6)] == [
        30.0, 120.0, 600.0, 1800.0, 7200.0,
    ]


@pytest.mark.asyncio
async def test_content_readiness_requires_vectors_and_non_path_text(monkeypatch):
    from raganything.services import document_quality, pg_state_repo

    class Pool:
        async def fetch(self, _sql, _workspace, ids):
            return [{"id": value} for value in ids]

    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: Pool())
    ready = await document_quality.evaluate_content_readiness(
        "default", ["chunk-1"], {"chunk-1": {"content": "底盘制动系统检修说明"}},
    )
    assert ready["ready"] is True

    invalid = await document_quality.evaluate_content_readiness(
        "default", ["chunk-1"], {"chunk-1": {"content": r"C:\output\page-1.png"}},
    )
    assert invalid["ready"] is False
    assert invalid["invalid_content_ids"] == ["chunk-1"]


@pytest.mark.asyncio
async def test_content_readiness_reads_local_nanovector_ids_without_pg(monkeypatch, tmp_path):
    from raganything.services import document_quality, pg_state_repo

    def unavailable_pool():
        raise RuntimeError("PG is not configured")

    monkeypatch.setattr(pg_state_repo, "get_pg_pool", unavailable_pool)
    monkeypatch.setenv("WORKING_DIR", str(tmp_path))
    (tmp_path / "vdb_chunks.json").write_text(
        '{"data":[{"__id__":"chunk-1"}]}',
        encoding="utf-8",
    )

    result = await document_quality.evaluate_content_readiness(
        "default", ["chunk-1"], {"chunk-1": {"content": "有效文本"}},
    )

    assert result["ready"] is True
    assert result["vector_count"] == 1


def test_worker_async_flow_contains_no_sys_exit():
    import inspect
    import process_worker

    assert "sys.exit(" not in inspect.getsource(process_worker.process_file)
    assert "os._exit(int(worker_exit_code))" in inspect.getsource(process_worker)


@pytest.mark.asyncio
async def test_rag_finalization_order_and_idempotency():
    import asyncio
    import logging
    from raganything.raganything import RAGAnything

    events = []

    class Processor:
        async def await_pending_vision_tasks(self):
            events.append("vision_tasks")

    class Repository:
        async def flush(self):
            events.append("vision_flush")

    class Store:
        async def index_done_callback(self):
            events.append("persist")

    class Cache:
        def __init__(self, name):
            self.name = name

        async def finalize(self):
            events.append(self.name)

    class LightRAG:
        image_vision_repo = Repository()
        text_chunks = Store()

        async def finalize_storages(self):
            events.append("lightrag")

    rag = object.__new__(RAGAnything)
    rag._finalized = False
    rag._finalize_lock = None
    rag._finalize_components = {}
    rag.modal_processors = {"image": Processor()}
    rag.lightrag = LightRAG()
    rag.parse_cache = Cache("parse_cache")
    rag.multimodal_status_cache = Cache("multimodal_cache")
    rag.logger = logging.getLogger("test.finalize")

    await rag.finalize_storages()
    await rag.finalize_storages()
    assert events == [
        "vision_tasks", "vision_flush", "persist", "parse_cache",
        "multimodal_cache", "lightrag",
    ]
