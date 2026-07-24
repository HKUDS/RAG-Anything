from types import SimpleNamespace

import pytest


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_prepare_repair_requires_all_pg_chunks_and_tracks_uncached_chunk(
    monkeypatch,
):
    from raganything.services import document_repair, kb_chunk_repo, kb_service
    from raganything.services import document_quality

    persisted = {}

    class DocStatus:
        async def upsert(self, records):
            persisted.update(records)

        async def index_done_callback(self):
            return None

    statuses = {
        "doc-abcdef": {
            "status": "failed",
            "chunks_count": 2,
            "chunks_list": ["chunk-1", "chunk-2"],
            "error_msg": "request timed out",
            "metadata": {},
        }
    }

    async def load_statuses(_kb):
        return statuses

    async def get_kb(_kb):
        return SimpleNamespace(lightrag=SimpleNamespace(doc_status=DocStatus()))

    async def query_chunks(_lightrag, _doc_id):
        return [
            {"id": "chunk-1", "llm_cache_list": ["cache-1"]},
            {"id": "chunk-2", "llm_cache_list": []},
        ]

    async def enqueue(kb_name, doc_id, **_kwargs):
        return {"id": 7, "kb_name": kb_name, "doc_id": doc_id}

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load_statuses)
    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", query_chunks)
    monkeypatch.setattr(document_repair, "enqueue_repair", enqueue)
    async def ready_quality(*_args, **_kwargs):
        return {"ready": True}
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", ready_quality)

    result = await document_repair.prepare_document_repair("demo", "doc-ab")

    metadata = persisted["doc-abcdef"]["metadata"]
    assert result["status"] == "degraded"
    assert metadata["content_ready"] is True
    assert metadata["graph_status"] == "pending"
    assert metadata["failed_chunk_ids"] == ["chunk-2"]


@pytest.mark.asyncio
async def test_prepare_repair_rejects_incomplete_pg_chunks(monkeypatch):
    from raganything.services import document_repair, kb_chunk_repo, kb_service

    async def load_statuses(_kb):
        return {
            "doc-1": {
                "status": "failed",
                "chunks_count": 2,
                "chunks_list": ["chunk-1", "chunk-2"],
            }
        }

    async def get_kb(_kb):
        return SimpleNamespace(lightrag=SimpleNamespace(doc_status=object()))

    async def query_chunks(_lightrag, _doc_id):
        return [{"id": "chunk-1", "llm_cache_list": []}]

    monkeypatch.setattr(kb_service, "_load_doc_status_json", load_statuses)
    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", query_chunks)

    with pytest.raises(ValueError, match="incomplete"):
        await document_repair.prepare_document_repair("demo", "doc-1")


@pytest.mark.asyncio
async def test_doc_status_allowlist_filters_both_status_queries():
    from raganything.services.document_repair import _DocStatusAllowList

    class Backend:
        async def get_docs_by_statuses(self, _statuses):
            return {"doc-target": {"status": "failed"}, "doc-other": {}}

        async def get_docs_by_status(self, _status):
            return {"doc-target": {"status": "failed"}, "doc-other": {}}

    proxy = _DocStatusAllowList(Backend(), "doc-target")

    assert list((await proxy.get_docs_by_statuses(["failed"]))) == ["doc-target"]
    assert list((await proxy.get_docs_by_status("failed"))) == ["doc-target"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Worker execution timeout after 360s", True),
        ("HTTP 429 rate limit", True),
        ("HTTP 500 internal server error", True),
        ("connection reset by peer", True),
        ("HTTP 429 insufficient_quota", False),
        ("401 invalid api key", False),
        ("400 invalid parameter", False),
        ("model not found", False),
    ],
)
def test_retryable_error_classification(message, expected):
    from raganything.services.document_repair import _is_retryable_error

    assert _is_retryable_error(RuntimeError(message)) is expected


@pytest.mark.asyncio
async def test_fail_repair_uses_bounded_backoff_with_jitter(monkeypatch):
    from raganything.services import document_repair

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    monkeypatch.setattr(document_repair, "get_pg_pool", lambda: _Pool(Connection()))
    monkeypatch.setattr(document_repair.random, "uniform", lambda _a, _b: 1.0)

    await document_repair.fail_repair(
        {"id": 9, "attempt_count": 2, "max_attempts": 3},
        "timed out",
        retryable=True,
    )

    _sql, args = calls[0]
    assert args == (9, "retry_wait", True, 60, "timed out")


@pytest.mark.asyncio
async def test_run_repair_job_only_exposes_target_document(monkeypatch):
    from raganything.services import document_quality, document_repair, kb_chunk_repo, kb_service

    stored = {
        "doc-target": {
            "status": "failed",
            "chunks_count": 1,
            "metadata": {"failed_chunk_ids": ["chunk-1"]},
        },
        "doc-other": {"status": "failed", "chunks_count": 1},
    }
    seen = []

    class DocStatus:
        async def get_by_id(self, doc_id):
            return stored.get(doc_id)

        async def get_docs_by_statuses(self, _statuses):
            return stored

        async def get_docs_by_status(self, _status):
            return stored

        async def upsert(self, records):
            stored.update(records)

        async def index_done_callback(self):
            return None

    doc_status = DocStatus()
    lightrag = SimpleNamespace(doc_status=doc_status)

    async def pipeline():
        visible = await lightrag.doc_status.get_docs_by_statuses(["failed"])
        seen.extend(visible)

    lightrag.apipeline_process_enqueue_documents = pipeline

    async def get_kb(_kb):
        return SimpleNamespace(lightrag=lightrag)

    async def load_statuses(_kb):
        return {
            "doc-target": {
                "status": "processed",
                "chunks_count": 1,
                "metadata": {},
            }
        }

    monkeypatch.setattr(kb_service, "get_kb", get_kb)
    monkeypatch.setattr(kb_service, "_load_doc_status_json", load_statuses)
    async def query_chunks(*_args):
        return [{"id": "chunk-1", "content": "valid text"}]
    async def ready_quality(*_args, **_kwargs):
        return {"ready": True}
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", query_chunks)
    monkeypatch.setattr(document_quality, "evaluate_content_readiness", ready_quality)

    await document_repair.run_repair_job(
        {"id": 1, "kb_name": "demo", "doc_id": "doc-target", "attempt_count": 1}
    )

    assert seen == ["doc-target"]
    assert lightrag.doc_status is doc_status
    assert stored["doc-target"]["metadata"]["graph_status"] == "completed"
    assert stored["doc-target"]["metadata"]["failed_chunk_ids"] == []
