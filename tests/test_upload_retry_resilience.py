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
async def test_embedding_preflight_accepts_the_factory_provider_without_legacy_attribute(monkeypatch):
    import process_worker

    calls = []

    async def preflight_provider(texts, *, timeout):
        calls.append((texts, timeout))
        return [[0.5] * process_worker.EMB_DIM]

    monkeypatch.setenv("MODEL_PREFLIGHT_ENABLED", "true")
    rag = SimpleNamespace(_raw_embedding_preflight_provider=preflight_provider)
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


def test_structured_quota_lease_failure_remains_retryable():
    from raganything.services.kb_service import _parse_worker_error

    lines = [
        'WORKER_ERROR_JSON {"stage":"quota","root_type":"QuotaLeaseLost",'
        '"failure_code":"quota_lease_lost","retryable":true,'
        '"message":"The upload processing quota lease was reclaimed","secondary":[]}',
    ]

    result = _parse_worker_error(lines, 4)

    assert result["stage"] == "quota"
    assert result["failure_code"] == "quota_lease_lost"
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
        async def fetchrow(self, sql, _workspace):
            if "pg_catalog.pg_class" in sql:
                return {"relname": "lightrag_vdb_chunks"}
            return None

        async def fetchval(self, _sql, *_args):
            return True

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

    assert document_quality.is_path_placeholder(
        "Image Path: C:\\output\\page-1.png\n[Image: C:\\output\\page-1.png]"
    ) is True


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


@pytest.mark.asyncio
async def test_content_readiness_reads_non_default_nanovector_workspace(monkeypatch, tmp_path):
    from raganything.services import document_quality, pg_state_repo

    def unavailable_pool():
        raise RuntimeError("PG vector storage is unavailable")

    default_dir = tmp_path / "rag_storage"
    kb_dir = tmp_path / "rag_storage_1"
    kb_dir.mkdir()
    (kb_dir / "vdb_chunks.json").write_text(
        '{"data":[{"__id__":"chunk-1"}]}', encoding="utf-8",
    )
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", unavailable_pool)
    monkeypatch.setenv("WORKING_DIR", str(default_dir))

    result = await document_quality.evaluate_content_readiness(
        "1", ["chunk-1"], {"chunk-1": {"content": "有效文本"}},
    )

    assert result["ready"] is True
    assert result["vector_count"] == 1


@pytest.mark.asyncio
async def test_content_readiness_reads_legacy_nested_nanovector_workspace(monkeypatch, tmp_path):
    from raganything.services import document_quality, pg_state_repo

    default_dir = tmp_path / "rag_storage"
    nested_dir = tmp_path / "rag_storage_1" / "rag_storage_1"
    nested_dir.mkdir(parents=True)
    (nested_dir / "vdb_chunks.json").write_text(
        '{"data":[{"__id__":"chunk-1"}]}', encoding="utf-8",
    )
    monkeypatch.setattr(
        pg_state_repo, "get_pg_pool", lambda: (_ for _ in ()).throw(
            RuntimeError("PG vector storage is unavailable")
        )
    )
    monkeypatch.setenv("WORKING_DIR", str(default_dir))

    result = await document_quality.evaluate_content_readiness(
        "1", ["chunk-1"], {"chunk-1": {"content": "有效文本"}},
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
        def __init__(self, result=True, updated=False):
            self.result = result
            self.storage_updated = type("Flag", (), {"value": updated})()

        async def index_done_callback(self):
            events.append("persist")
            return self.result

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


@pytest.mark.asyncio
async def test_worker_vdb_persistence_clears_stale_flag_and_checks_callback():
    import logging
    from raganything.raganything import RAGAnything

    class VDB:
        def __init__(self, result=True):
            self.storage_updated = type("Flag", (), {"value": True})()
            self.result = result

        async def index_done_callback(self):
            assert self.storage_updated.value is False
            return self.result

    class LightRAG:
        chunks_vdb = VDB()

    rag = object.__new__(RAGAnything)
    rag._finalized = False
    rag._finalize_lock = None
    rag._finalize_components = {}
    rag.modal_processors = {}
    rag.lightrag = LightRAG()
    rag.parse_cache = None
    rag.multimodal_status_cache = None
    rag.logger = logging.getLogger("test.worker-vdb")

    await rag.finalize_storages(worker_vdb_persistence=True)
    assert LightRAG.chunks_vdb.storage_updated.value is False


@pytest.mark.asyncio
async def test_worker_vdb_persistence_raises_on_false_callback():
    import logging
    from raganything.raganything import RAGAnything

    class VDB:
        storage_updated = type("Flag", (), {"value": True})()

        async def index_done_callback(self):
            return False

    class LightRAG:
        chunks_vdb = VDB()

    rag = object.__new__(RAGAnything)
    rag.lightrag = LightRAG()
    rag.logger = logging.getLogger("test.worker-vdb-failure")

    with pytest.raises(RuntimeError, match="nanovectordb_persist_failed:chunks_vdb"):
        await rag._persist_lightrag_stores(worker_vdb_persistence=True)


@pytest.mark.asyncio
async def test_worker_vdb_persistence_propagates_callback_exception():
    import logging
    from raganything.raganything import RAGAnything

    class VDB:
        storage_updated = type("Flag", (), {"value": True})()

        async def index_done_callback(self):
            raise OSError("disk full")

    class LightRAG:
        chunks_vdb = VDB()

    rag = object.__new__(RAGAnything)
    rag.lightrag = LightRAG()
    rag.logger = logging.getLogger("test.worker-vdb-exception")

    with pytest.raises(OSError, match="disk full"):
        await rag._persist_lightrag_stores(worker_vdb_persistence=True)


@pytest.mark.asyncio
async def test_regular_vdb_persistence_keeps_update_flag_behavior():
    import logging
    from raganything.raganything import RAGAnything

    class VDB:
        storage_updated = type("Flag", (), {"value": True})()

        async def index_done_callback(self):
            return True

    class LightRAG:
        chunks_vdb = VDB()

    rag = object.__new__(RAGAnything)
    rag.lightrag = LightRAG()
    rag.logger = logging.getLogger("test.regular-vdb")

    await rag._persist_lightrag_stores()
    assert LightRAG.chunks_vdb.storage_updated.value is True


@pytest.mark.asyncio
async def test_post_worker_cache_retirement_skips_file_backed_vector_stores():
    import logging
    from raganything.raganything import RAGAnything

    events = []

    class Store:
        async def index_done_callback(self):
            events.append("store")
            return True

    class LightRAG:
        chunks_vdb = Store()
        text_chunks = Store()

    rag = object.__new__(RAGAnything)
    rag._finalized = False
    rag._finalize_lock = None
    rag._finalize_components = {}
    rag.modal_processors = {}
    rag.lightrag = LightRAG()
    rag.parse_cache = None
    rag.multimodal_status_cache = None
    rag.logger = logging.getLogger("test.post-worker-retire")

    await rag.finalize_storages(persist_vector_stores=False)

    # Text/KV stores stay durable; the stale server-side VDB must not overwrite
    # the snapshot already written by the independent Worker.
    assert events == ["store"]


@pytest.mark.asyncio
async def test_content_readiness_queries_identity_suffixed_vector_table(monkeypatch):
    from raganything.services import document_quality, pg_state_repo

    class Pool:
        def __init__(self):
            self.queries = []

        async def fetchrow(self, sql, _workspace):
            if "kb_text_embedding_identities" in sql:
                self.queries.append(("fetchrow_identity", _workspace))
                return {"identity": {"model_name": "openai_compa_639985a6e4b87473", "dimension": 1024}}
            if "pg_catalog.pg_class" in sql:
                self.queries.append(("fetchrow_pg_class", _workspace))
                return {"relname": "lightrag_vdb_chunks_openai_compa_639985a6e4b87473_1024d"}
            raise AssertionError(sql)

        async def fetchval(self, _sql, *_args):
            return True

        async def fetch(self, sql, _workspace, ids):
            self.queries.append(("fetch", sql))
            return [{"id": value} for value in ids]

    pool = Pool()
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: pool)
    result = await document_quality.evaluate_content_readiness(
        "default", ["chunk-1"], {"chunk-1": {"content": "有效文本"}},
    )

    assert result["ready"] is True
    assert result["vector_count"] == 1
    assert any(
        "lightrag_vdb_chunks_openai_compa_639985a6e4b87473_1024d" in sql
        for name, sql in pool.queries
        if name == "fetch"
    )
@pytest.mark.asyncio
async def test_cleanup_failed_invalid_residue_uses_suffixed_vector_table(monkeypatch):
    from contextlib import asynccontextmanager

    from raganything.services import document_quality, pg_state_repo

    class Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Conn:
        def __init__(self, vector_count=0):
            self.vector_count = vector_count
            self.executed = []

        async def fetchrow(self, sql, *args):
            if "LIGHTRAG_DOC_STATUS" in sql:
                return {"id": "doc-1", "file_path": r"C:\output\doc.md",
                        "status": "failed", "chunks_count": 1}
            if "pg_catalog.pg_class" in sql:
                return {"relname": "lightrag_vdb_chunks_openai_compa_639985a6e4b87473_1024d"}
            if "kb_text_embedding_identities" in sql:
                return {"identity": {"model_name": "openai_compa_639985a6e4b87473",
                                     "dimension": 1024}}
            raise AssertionError(sql)

        async def fetchval(self, sql, *args):
            if sql.startswith("SELECT EXISTS"):
                return False
            if sql.startswith("SELECT COUNT(*) FROM"):
                return self.vector_count
            raise AssertionError(sql)

        async def fetch(self, sql, *args):
            if "LIGHTRAG_DOC_CHUNKS" in sql:
                return [{"id": "chunk-1", "content": r"C:\output\page-1.png"}]
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            self.executed.append((sql, args))
            return "DELETE 1"

        def transaction(self):
            return Tx()

    class Pool:
        def __init__(self, conn):
            self.conn = conn

        @asynccontextmanager
        async def acquire(self):
            yield self.conn

    conn = Conn(vector_count=0)
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: Pool(conn))
    result = await document_quality.cleanup_failed_invalid_residue(
        "./rag_storage_kb-a", "doc-1", expected_filename="doc.md",
    )
    assert result["counts"]["vdb_chunks"] == 1
    assert any(
        sql.startswith("DELETE FROM") and "lightrag_vdb_chunks_openai_compa_639985a6e4b87473_1024d" in sql
        for sql, _args in conn.executed
    )

    conn_with_vectors = Conn(vector_count=1)
    monkeypatch.setattr(pg_state_repo, "get_pg_pool", lambda: Pool(conn_with_vectors))
    with pytest.raises(ValueError, match="has chunk vectors"):
        await document_quality.cleanup_failed_invalid_residue(
            "./rag_storage_kb-a", "doc-1", expected_filename="doc.md",
        )
