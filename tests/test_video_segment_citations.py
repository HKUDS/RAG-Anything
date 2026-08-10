from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from raganything.services.video_segments import (
    controlled_video_media_url,
    enrich_video_segment_citations,
    merge_video_segment_citations,
)


def test_video_citations_deduplicate_parent_and_keep_segment_order():
    citations = merge_video_segment_citations([
        {"segment_id": "s-2", "segment_index": 2, "start_ms": 42000, "end_ms": 66000,
         "document_id": "doc-1", "document_name": "battery.mp4", "media_id": "m-1", "media_kb": "kb-a"},
        {"segment_id": "s-1", "segment_index": 1, "start_ms": 18000, "end_ms": 45000,
         "document_id": "doc-1", "document_name": "battery.mp4", "media_id": "m-1", "media_kb": "kb-a"},
        {"segment_id": "s-2", "segment_index": 2, "start_ms": 42000, "end_ms": 66000,
         "document_id": "doc-1", "document_name": "battery.mp4", "media_id": "m-1", "media_kb": "kb-a"},
    ])

    assert len(citations) == 1
    assert citations[0]["media_url"] == controlled_video_media_url("m-1", "kb-a")
    assert [item["segment_id"] for item in citations[0]["video_segments"]] == ["s-1", "s-2"]


def test_agent_video_marker_becomes_path_free_citation():
    from raganything.routers.agent import _video_segment_citations_from_context

    citations = _video_segment_citations_from_context(
        "[VIDEO_SEGMENT segment_id=segment-1 media_id=video-opaque start_ms=12000 end_ms=36000 document_id=doc-1]",
        "visible-kb",
    )

    assert citations[0]["video_segment"] == {
        "segment_id": "segment-1", "start_ms": 12000, "end_ms": 36000,
    }
    serialized = json.dumps(citations)
    assert "server_path" not in serialized
    assert "C:" not in serialized


def test_video_citation_enrichment_preserves_ordinary_citations():
    citations = enrich_video_segment_citations([
        {"source": "manual.pdf", "content": "ordinary source"},
        {"video_segment": {
            "segment_id": "segment-1", "segment_index": 0,
            "start_ms": 12000, "end_ms": 36000, "media_id": "opaque-video",
            "document_id": "doc-1", "document_name": "battery.mp4",
        }},
    ], "visible-kb")

    assert citations[0]["source"] == "manual.pdf"
    assert citations[1]["video_segment"]["start_ms"] == 12000
    assert citations[1]["media_url"] == controlled_video_media_url("opaque-video", "visible-kb")
    assert "server_path" not in json.dumps(citations)


@pytest.mark.asyncio
async def test_delete_video_segments_removes_document_rows_before_shared_asset(monkeypatch):
    from raganything.services import video_segments

    calls = []

    class Pool:
        async def execute(self, query, *args):
            calls.append((query, args))

    monkeypatch.setattr(video_segments, "get_pg_pool", lambda: Pool())
    await video_segments.delete_video_segments("kb-a", "doc-1")

    # media_id is content-derived, so a shared source may be referenced by
    # another document.  Document-local segment rows must go first; only then
    # is the (kb, document) asset row removed.  Relying on the asset FK
    # cascade alone would delete segments that still belong to other docs.
    assert "DELETE FROM video_segments" in calls[0][0]
    assert calls[0][1] == ("kb-a", "doc-1")
    assert "DELETE FROM video_assets" in calls[1][0]
    assert calls[1][1] == ("kb-a", "doc-1")


def test_video_media_path_requires_controlled_upload_root(tmp_path, monkeypatch):
    from raganything.routers.knowledge import _resolve_controlled_video_path

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    video = uploads / "lesson.mp4"
    video.write_bytes(b"video")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    monkeypatch.chdir(tmp_path)

    assert _resolve_controlled_video_path(str(video)) == video.resolve()
    assert _resolve_controlled_video_path(str(outside)) is None


@pytest.mark.asyncio
async def test_document_video_segments_are_path_free(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import video_segments

    async def statuses(_kb):
        return {"doc-1": {}}

    async def segments(_kb, _doc):
        return [{
            "segment_id": "segment-1", "segment_index": 0,
            "start_ms": 0, "end_ms": 24000, "media_id": "opaque-video",
            "status": "ready", "server_path": r"C:\\private\\lesson.mp4",
        }]

    monkeypatch.setattr(knowledge, "_load_doc_status_json", statuses)
    monkeypatch.setattr(video_segments, "list_video_segments", segments)
    payload = await knowledge.get_document_video_segments("doc-1", kb="visible-kb")

    assert payload["segments"][0]["media_url"].startswith("/api/knowledge/media/opaque-video?")
    assert "server_path" not in json.dumps(payload)
    assert r"C:\\private" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_controlled_video_media_supports_range_and_hides_server_path(tmp_path, monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import video_segments

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    video = uploads / "lesson.mp4"
    video.write_bytes(b"0123456789")
    monkeypatch.chdir(tmp_path)

    async def allow_kb(kb, _user):
        return kb

    async def no_odl(_kb):
        return {}

    async def asset(_kb, _media_id):
        return {"server_path": str(video)}

    monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", no_odl)
    monkeypatch.setattr(video_segments, "get_video_asset", asset)
    app = FastAPI()
    app.include_router(knowledge.router)
    route = next(route for route in knowledge.router.routes if getattr(route, "path", None) == "/knowledge/media/{media_id}")
    app.dependency_overrides[route.dependant.dependencies[0].call] = lambda: None
    app.dependency_overrides[knowledge.get_current_user] = lambda: {"id": 7}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/knowledge/media/opaque-video", params={"kb": "visible-kb"}, headers={"Range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert str(video) not in response.text


# ── 分段引用富化闭环回归（4.1/5.2）────────────────────────────

class _Request:
    headers = {}


async def _body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def _agent_query_context():
    """Retrieval context carrying video segment anchors plus a text source."""
    return (
        "[来源 battery.mp4]\n"
        "第一步：检查电池电压并记录读数。\n"
        "第二步：确认电压在 12V 以上再继续操作。\n"
        "补充说明：操作完成后关闭电源并清理工位。\n" * 8 +
        "[VIDEO_SEGMENT segment_id=seg-2 media_id=m-1 start_ms=24000 end_ms=48000 document_id=doc-1]\n"
        "[VIDEO_SEGMENT segment_id=seg-1 media_id=m-1 start_ms=0 end_ms=24000 document_id=doc-1]\n"
        "[VIDEO_SEGMENT segment_id=seg-2 media_id=m-1 start_ms=24000 end_ms=48000 document_id=doc-1]"
    )


def _minimal_resolved_settings():
    return SimpleNamespace(
        models=SimpleNamespace(llm_profile_id="test-llm", vlm_profile_id="test-vlm"),
        fingerprint="settings-fingerprint",
        runtime=SimpleNamespace(llm_timeout=180, personal_concurrency=2),
        retrieval=SimpleNamespace(
            channels=("bm25", "vector", "graph"),
            bm25_top_k=50, vector_top_k=100, graph_top_k=30, graph_depth=2,
            rrf_k=60, bm25_tokenizer="jieba", bm25_k1=1.5, bm25_b=0.75,
        ),
    )


def _wire_agent_stream_prerequisites(monkeypatch, *, agent_mode, kb_instance):
    from raganything.routers import agent as agent_router
    from raganything.services import user_settings, vision_models

    async def get_agent(_agent_id):
        return {
            "id": "agent-1", "name": "agent", "kb_name": "kb", "owner_id": 7,
            "query_mode": "hybrid", "agent_mode": agent_mode, "retrieval_top_k": 20,
            "chunk_top_k": 5, "enable_rerank": False, "include_references": True,
            "max_response_tokens": 512, "temperature": 0.0, "system_prompt": "",
            "use_default_prompt": True,
        }

    class QueryLease:
        instance = kb_instance
        key = SimpleNamespace(corpus_revision="rev-1")
        cache_status = "hit"

        async def release(self):
            return None

    async def acquire_query_kb(_kb, **_kwargs):
        return QueryLease()

    async def noop(*_args, **_kwargs):
        return None

    async def value(result):
        return result

    async def empty_conversation(*_args, **_kwargs):
        return {"messages": []}

    async def resolve_settings(_user_id, **_kwargs):
        return _minimal_resolved_settings()

    async def available_sections(_user_id):
        return []

    async def platform_settings():
        return {"settings": {"limits": {"interactive_wait_seconds": 0}}}

    async def lease_ok(*_args, **_kwargs):
        return True

    async def query_scope(*_args, **_kwargs):
        return {
            "workspace": "kb", "corpus_revision": "rev-1",
            "settings_fingerprint": "settings-fingerprint",
            "llm_profile_fingerprint": "llm-fingerprint",
        }

    async def recall_media(*_args, **_kwargs):
        return [], "", "none", False

    async def passthrough(events_iter, _user):
        async for item in events_iter:
            yield item

    async def llm_callable(*_args, **_kwargs):
        return "电池电压应保持在 12V。"

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(agent_router, "acquire_query_kb", acquire_query_kb)
    monkeypatch.setattr(agent_router, "verify_kb_access", lambda kb, current_user: value(kb))
    monkeypatch.setattr(agent_router, "pg_get_conversation", empty_conversation)
    monkeypatch.setattr(agent_router, "pg_create_conversation", noop)
    monkeypatch.setattr(agent_router, "pg_add_message", noop)
    monkeypatch.setattr(agent_router, "record_query", noop)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_router, "_query_cache_scope", query_scope)
    monkeypatch.setattr(agent_router, "_recall_controlled_media_with_budget", recall_media)
    monkeypatch.setattr(agent_router, "authenticated_sse_events", passthrough)
    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", resolve_settings)
    monkeypatch.setattr(user_settings, "available_sections_for_user", available_sections)
    monkeypatch.setattr(user_settings, "get_platform_settings", platform_settings)
    monkeypatch.setattr(user_settings, "acquire_quota_lease", lease_ok)
    monkeypatch.setattr(user_settings, "heartbeat_quota_lease", lease_ok)
    monkeypatch.setattr(user_settings, "release_quota_lease", lease_ok)
    monkeypatch.setattr(
        vision_models,
        "require_available",
        lambda _profile_id, kind: SimpleNamespace(
            profile=SimpleNamespace(kind=kind, available=True),
            fingerprint=f"{kind}-fingerprint",
        ),
    )
    monkeypatch.setattr(vision_models, "build_llm_callable", lambda *_args, **_kwargs: llm_callable)
    monkeypatch.setattr(vision_models, "activate_llm_selection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(vision_models, "reset_llm_snapshot", lambda _token: None)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)


@pytest.mark.asyncio
async def test_query_pipeline_context_injects_video_segment_markers(monkeypatch):
    from raganything.query.pipeline import QueryMixin
    from raganything.services import video_segments

    chunks = [
        SimpleNamespace(
            chunk_id="chunk-1",
            content="第一步：检查电池电压并记录读数。\n第二步：确认电压在 12V 以上。",
            document_name="battery.mp4",
        )
    ]

    class HybridEngine:
        async def search(self, _query, top_k=None, options=None):
            return chunks

    async def segments_for_chunks(_kb, _chunk_ids):
        return {
            "chunk-1": {
                "segment_id": "seg-1", "segment_index": 0, "start_ms": 0,
                "end_ms": 24000, "document_id": "doc-1", "media_id": "m-1",
                "media_kb": "kb-a", "document_name": "battery.mp4",
            },
        }

    query = object.__new__(QueryMixin)
    query.lightrag = SimpleNamespace(workspace="./rag_storage_kb-a")
    query.hybrid_search_engine = HybridEngine()
    query.callback_manager = None
    query.logger = logging.getLogger("raganything.query.pipeline")
    query.batch_get_doc_source_info_async = AsyncMock(return_value={})
    monkeypatch.setattr(video_segments, "list_video_segments_for_chunks", segments_for_chunks)

    context = await query._aquery_rrf("如何检查电池电压", only_need_context=True)

    assert "[来源 battery.mp4]" in context
    assert (
        "[VIDEO_SEGMENT segment_id=seg-1 media_id=m-1 start_ms=0 end_ms=24000 document_id=doc-1]"
        in context
    )


@pytest.mark.asyncio
async def test_agent_sse_done_event_carries_video_segment_citations(monkeypatch):
    from raganything.routers import agent as agent_router

    class _KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **_kwargs):
            return _agent_query_context()

        async def finalize_storages(self):
            return None

    _wire_agent_stream_prerequisites(monkeypatch, agent_mode="none", kb_instance=_KB())

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="如何检查电池电压", thread_id="thread-1"),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    done = next(event for event in events if event["type"] == "done")

    assert len(done["citations"]) == 1
    citation = done["citations"][0]
    assert citation["media_id"] == "m-1"
    assert citation["media_kb"] == "kb"
    assert citation["media_url"].startswith("/api/knowledge/media/m-1?")
    assert citation["video_segment"] == {"segment_id": "seg-1", "start_ms": 0, "end_ms": 24000}
    assert [item["segment_id"] for item in citation["video_segments"]] == ["seg-1", "seg-2"]
    assert "server_path" not in body


@pytest.mark.asyncio
async def test_agent_cot_done_event_carries_video_segment_citations(monkeypatch):
    import raganything.agentic_rag as agentic_rag_module
    from raganything.agentic_rag import AgentResult
    from raganything.routers import agent as agent_router

    class _KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **_kwargs):
            return _agent_query_context()

        async def finalize_storages(self):
            return None

    class _FakeAgenticRAG:
        def __init__(self, *_args, **_kwargs):
            self._tools = []

        def register_tool(self, tool):
            self._tools.append(tool)

        async def run_with_context(self, query, ctx):
            return AgentResult(answer="电池电压应保持在 12V。", trace=[])

    class _FakeSearchTool:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(agentic_rag_module, "AgenticRAG", _FakeAgenticRAG)
    monkeypatch.setattr(agentic_rag_module, "SearchTool", _FakeSearchTool)
    _wire_agent_stream_prerequisites(monkeypatch, agent_mode="cot", kb_instance=_KB())

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="如何检查电池电压", thread_id="thread-1"),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    done = next(event for event in events if event["type"] == "done")

    assert done["citations"][0]["media_id"] == "m-1"
    assert done["citations"][0]["media_kb"] == "kb"
    assert done["citations"][0]["video_segment"] == {"segment_id": "seg-1", "start_ms": 0, "end_ms": 24000}
    assert [item["segment_id"] for item in done["citations"][0]["video_segments"]] == ["seg-1", "seg-2"]
    assert "server_path" not in body


@pytest.mark.asyncio
async def test_autorepair_non_streaming_carries_video_segment_citations(monkeypatch):
    from raganything.routers import autorepair

    class _Response:
        query = "如何检查电池"
        answer = "检查电池电压并记录读数。"
        citations = [
            {"source_title": "手册.pdf", "page": 1, "section": "",
             "excerpt": "步骤 1", "reliability": "high", "url": "", "ingested_at": ""},
            {"segment_id": "seg-2", "segment_index": 1, "start_ms": 24000, "end_ms": 48000,
             "media_id": "m-1", "media_kb": "autorepair-kb", "document_id": "doc-1",
             "document_name": "battery.mp4"},
            {"segment_id": "seg-1", "segment_index": 0, "start_ms": 0, "end_ms": 24000,
             "media_id": "m-1", "media_kb": "autorepair-kb", "document_id": "doc-1",
             "document_name": "battery.mp4"},
            {"segment_id": "seg-1", "segment_index": 0, "start_ms": 0, "end_ms": 24000,
             "media_id": "m-1", "media_kb": "autorepair-kb", "document_id": "doc-1",
             "document_name": "battery.mp4"},
        ]
        related_images = []
        confidence = 0.9
        processing_time_ms = 12.0
        needs_human_review = False
        trace = []

    async def get_engine(_kb):
        return SimpleNamespace(answer=AsyncMock(return_value=_Response()))

    async def allow_kb(*, kb, current_user):
        return kb

    monkeypatch.setattr(autorepair, "verify_kb_access", allow_kb)
    monkeypatch.setattr(autorepair, "_get_ar_qa_engine", get_engine)
    monkeypatch.setattr(autorepair, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        autorepair, "_get_autorepair",
        lambda: {"dashboard": SimpleNamespace(log_query=AsyncMock())},
    )

    payload = await autorepair.ar_qa(
        autorepair.AutoRepairAgentQuery(query="如何检查电池"),
        kb="verified-kb", _perm=None,
        current_user={"id": 41, "username": "u", "is_admin": False, "allowed_kbs": []},
    )

    assert payload["citations"][0]["source_title"] == "手册.pdf"
    video = payload["citations"][1]
    assert video["media_id"] == "m-1"
    assert video["media_kb"] == "verified-kb"
    assert video["media_url"].startswith("/api/knowledge/media/m-1?")
    assert video["video_segment"] == {"segment_id": "seg-1", "start_ms": 0, "end_ms": 24000}
    assert [item["segment_id"] for item in video["video_segments"]] == ["seg-1", "seg-2"]
    assert "server_path" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_autorepair_stream_done_carries_video_segment_citations(monkeypatch):
    from raganything.routers import autorepair

    async def events(_query):
        yield {"type": "thinking", "step": 1, "action": "search", "elapsed_ms": 10}
        yield {"type": "token", "content": "检查电池"}
        yield {"type": "done", "elapsed_ms": 120, "confidence": 0.9, "images": [],
               "citations": [
                   {"segment_id": "seg-1", "segment_index": 0, "start_ms": 0, "end_ms": 24000,
                    "media_id": "m-1", "media_kb": "autorepair-kb", "document_id": "doc-1",
                    "document_name": "battery.mp4"},
               ]}

    async def get_engine(_kb):
        return SimpleNamespace(answer_stream=events)

    async def allow_kb(*, kb, current_user):
        return kb

    async def passthrough(events_iter, _user):
        async for item in events_iter:
            yield item

    monkeypatch.setattr(autorepair, "verify_kb_access", allow_kb)
    monkeypatch.setattr(autorepair, "_get_ar_qa_engine", get_engine)
    monkeypatch.setattr(autorepair, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        autorepair, "_get_autorepair",
        lambda: {"dashboard": SimpleNamespace(log_query=AsyncMock())},
    )
    monkeypatch.setattr(autorepair, "authenticated_sse_events", passthrough)
    monkeypatch.setattr(autorepair.shared, "API_KEY", "configured")
    monkeypatch.setattr(autorepair.shared, "BASE_URL", "https://llm.invalid")

    response = await autorepair.ar_qa_stream(
        autorepair.AutoRepairAgentQuery(query="如何检查电池"),
        kb="verified-kb", _perm=None,
        current_user={"id": 41, "username": "u", "is_admin": False, "allowed_kbs": []},
    )
    body = await _body(response)
    events_out = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    done = next(event for event in events_out if event["type"] == "done")

    assert done["citations"][0]["media_id"] == "m-1"
    assert done["citations"][0]["media_kb"] == "verified-kb"
    assert done["citations"][0]["video_segment"] == {"segment_id": "seg-1", "start_ms": 0, "end_ms": 24000}
    assert done["citations"][0]["media_url"].startswith("/api/knowledge/media/m-1?")
    assert "server_path" not in body


@pytest.mark.asyncio
async def test_document_chunk_dto_attaches_video_segment_metadata(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import video_segments

    async def statuses(_kb):
        return {
            "doc-1": {
                "chunks_list": ["chunk-1"], "chunks_count": 1,
                "file_path": "battery.mp4", "status": "ready", "metadata": {},
            }
        }

    async def segments_for_chunks(_kb, _chunk_ids):
        return {
            "chunk-1": {
                "segment_id": "seg-1", "segment_index": 0, "start_ms": 12000,
                "end_ms": 36000, "document_id": "doc-1", "media_id": "m-1",
                "media_kb": "verified-kb", "document_name": "battery.mp4",
            },
        }

    record = {
        "chunk_id": "chunk-1",
        "content": "视频内容分析: 检查电池电压并记录读数。",
        "tokens": 8,
        "chunk_order_index": 0,
    }

    class LightRAG:
        text_chunks = SimpleNamespace(get_by_ids=AsyncMock(return_value=[record]))
        doc_status = None

    monkeypatch.setattr(knowledge, "get_kb", AsyncMock(return_value=SimpleNamespace(lightrag=LightRAG())))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", statuses)
    monkeypatch.setattr(
        knowledge, "_get_tags_for_chunks_best_effort",
        AsyncMock(return_value={"chunk-1": []}),
    )
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", AsyncMock(return_value={}))
    monkeypatch.setattr(video_segments, "list_video_segments_for_chunks", segments_for_chunks)

    payload = await knowledge.get_document_chunk(
        "doc-1", "chunk-1", kb="verified-kb",
        current_user={"id": 7, "username": "u", "is_admin": True},
    )
    chunk = payload["chunk"]
    assert chunk["video_segment"] == {"segment_id": "seg-1", "start_ms": 12000, "end_ms": 36000}
    assert chunk["media_id"] == "m-1"
    assert chunk["media_kb"] == "verified-kb"
    assert chunk["media_url"].startswith("/api/knowledge/media/m-1?")
    assert "server_path" not in json.dumps(payload)

    payload_list = await knowledge.get_document_chunks(
        "doc-1", kb="verified-kb",
        current_user={"id": 7, "username": "u", "is_admin": True},
    )
    assert payload_list["chunks"][0]["video_segment"] == {
        "segment_id": "seg-1", "start_ms": 12000, "end_ms": 36000,
    }
    assert payload_list["chunks"][0]["media_url"].startswith("/api/knowledge/media/m-1?")