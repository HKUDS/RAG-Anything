from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from raganything.routers import agent as agent_router
from raganything.services import user_settings, vision_models


def _resolved_settings():
    return user_settings.ResolvedUserSettings(
        models=user_settings.ModelSelection(
            llm_profile_id="test-llm", vlm_profile_id="test-vlm"
        ),
        ingestion=user_settings.ProcessingTaskSettings(
            parser="docling",
            chunking_strategy="recursive",
            chunk_size=800,
            enable_image=True,
            enable_table=True,
            enable_equation=True,
            enable_video=False,
            entity_types=(),
            minimum_relation_degree=0,
        ),
        retrieval=user_settings.RetrievalOptions(
            preset="balanced",
            rrf_k=60,
            bm25_top_k=50,
            vector_top_k=100,
            graph_top_k=30,
            graph_depth=2,
            channels=("bm25", "vector", "graph"),
            bm25_tokenizer="jieba",
            bm25_k1=1.5,
            bm25_b=0.75,
        ),
        runtime=user_settings.QuotaOptions(
            llm_timeout=180, personal_concurrency=2
        ),
        revision=1,
        fingerprint="settings-fingerprint",
        profile_fingerprints=user_settings.ModelProfileFingerprints(
            llm="llm-fingerprint", vlm="vlm-fingerprint"
        ),
    )


class _Request:
    headers = {}


async def _body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_retrieval_only_emits_metadata_without_generation_or_history(monkeypatch):
    calls = {"aquery": 0, "llm": 0, "history": 0}

    class _KB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **kwargs):
            calls["aquery"] += 1
            assert kwargs["only_need_context"] is True
            assert kwargs["retrieval_options"] == _resolved_settings().retrieval
            return "[来源 1] 检索上下文"

        async def finalize_storages(self):
            return None

    async def get_agent(_agent_id):
        return {
            "id": "agent-1", "name": "agent", "kb_name": "kb", "owner_id": 7,
            "query_mode": "hybrid", "agent_mode": "none", "retrieval_top_k": 20,
            "chunk_top_k": 5, "enable_rerank": False, "include_references": True,
            "max_response_tokens": 512, "temperature": 0.0, "system_prompt": "",
            "use_default_prompt": True,
        }

    class QueryLease:
        instance = _KB()

        async def release(self):
            return None

    async def acquire_query_kb(_kb, **_kwargs):
        return QueryLease()

    async def no_history(*_args, **_kwargs):
        calls["history"] += 1
        raise AssertionError("retrieval_only must not persist conversation or query history")

    async def empty_conversation(*_args, **_kwargs):
        return {"messages": []}

    async def resolve_settings(_user_id):
        return _resolved_settings()

    async def get_platform_settings():
        return {"settings": {"limits": {"interactive_wait_seconds": 0}}}

    async def acquire_lease(*_args, **_kwargs):
        return "lease-1"

    async def lease_ok(*_args, **_kwargs):
        return True

    async def query_scope(*_args, **_kwargs):
        return {"workspace": "kb", "settings_fingerprint": "settings-fingerprint"}

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(agent_router, "acquire_query_kb", acquire_query_kb)
    monkeypatch.setattr(agent_router, "verify_kb_access", lambda kb, current_user: _async_value(kb))
    monkeypatch.setattr(agent_router, "pg_get_conversation", empty_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", no_history)
    monkeypatch.setattr(agent_router, "record_query", no_history)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_router, "_query_cache_scope", query_scope)
    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", resolve_settings)
    monkeypatch.setattr(user_settings, "get_platform_settings", get_platform_settings)
    monkeypatch.setattr(user_settings, "acquire_quota_lease", acquire_lease)
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
    monkeypatch.setattr(vision_models, "build_llm_callable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(vision_models, "activate_llm_selection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(vision_models, "reset_llm_snapshot", lambda _token: None)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="测试", thread_id="thread-1", retrieval_only=True),
        _Request(),
        current_user={"id": 7, "username": "admin", "is_admin": True},
        _perm=None,
    )
    body = await _body(response)
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]

    retrieval = next(event for event in events if event["type"] == "retrieval")
    assert retrieval == {
        "type": "retrieval", "context_present": True, "context_chars": 12,
        "text_source_count": 1, "mode": "hybrid",
    }
    assert any(event.get("phase") == "retrieval" for event in events if event["type"] == "done")
    assert calls == {"aquery": 1, "llm": 0, "history": 0}


async def _async_value(value):
    return value


def _agent(agent_mode="none"):
    return {
        "id": "agent-1", "name": "agent", "kb_name": "kb", "owner_id": 7,
        "query_mode": "hybrid", "agent_mode": agent_mode, "retrieval_top_k": 20,
        "chunk_top_k": 5, "enable_rerank": False, "include_references": True,
        "max_response_tokens": 512, "temperature": 0.0, "system_prompt": "",
        "use_default_prompt": True,
    }


def _wire_query_prerequisites(monkeypatch, *, agent_mode="none", acquire=None):
    async def get_agent(_agent_id):
        return _agent(agent_mode)

    async def resolve_settings(_user_id):
        return _resolved_settings()

    async def platform_settings():
        return {"settings": {"limits": {"interactive_wait_seconds": 0}}}

    async def lease_ok(*_args, **_kwargs):
        return True

    async def query_scope(*_args, **_kwargs):
        return {"workspace": "kb", "settings_fingerprint": "settings-fingerprint"}

    monkeypatch.setattr(agent_router, "pg_get_agent", get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", lambda kb, current_user: _async_value(kb))
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_router, "_query_cache_scope", query_scope)
    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", resolve_settings)
    monkeypatch.setattr(user_settings, "get_platform_settings", platform_settings)
    monkeypatch.setattr(user_settings, "acquire_quota_lease", acquire or lease_ok)
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
    monkeypatch.setattr(vision_models, "build_llm_callable", lambda *_args, **_kwargs: None)


@pytest.mark.asyncio
async def test_invalid_retrieval_mode_rejects_before_quota_or_kb(monkeypatch):
    called = {"lease": 0, "kb": 0}

    async def acquire(*_args, **_kwargs):
        called["lease"] += 1
        return "lease"

    async def get_kb(*_args, **_kwargs):
        called["kb"] += 1
        raise AssertionError("KB must not be created")

    _wire_query_prerequisites(monkeypatch, agent_mode="react", acquire=acquire)
    monkeypatch.setattr(agent_router, "get_kb", get_kb)

    with pytest.raises(Exception) as raised:
        await agent_router.agent_query_stream(
            "agent-1",
            agent_router.AgentQueryRequest(query="test", retrieval_only=True),
            _Request(),
            current_user={"id": 7, "username": "user", "is_admin": False},
            _perm=None,
        )

    assert raised.value.status_code == 422
    assert called == {"lease": 0, "kb": 0}


@pytest.mark.asyncio
async def test_quota_429_does_not_create_kb(monkeypatch):
    called = {"kb": 0}

    async def denied(*_args, **_kwargs):
        return None

    async def get_kb(*_args, **_kwargs):
        called["kb"] += 1
        raise AssertionError("KB must not be created")

    _wire_query_prerequisites(monkeypatch, acquire=denied)
    monkeypatch.setattr(agent_router, "get_kb", get_kb)

    with pytest.raises(Exception) as raised:
        await agent_router.agent_query_stream(
            "agent-1",
            agent_router.AgentQueryRequest(query="test", retrieval_only=True),
            _Request(),
            current_user={"id": 7, "username": "user", "is_admin": False},
            _perm=None,
        )

    assert raised.value.status_code == 429
    assert called["kb"] == 0


@pytest.mark.asyncio
async def test_unconsumed_stream_does_not_create_kb(monkeypatch):
    called = {"kb": 0}

    async def get_kb(*_args, **_kwargs):
        called["kb"] += 1
        raise AssertionError("KB must not be created before body consumption")

    _wire_query_prerequisites(monkeypatch)
    monkeypatch.setattr(agent_router, "get_kb", get_kb)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="test", retrieval_only=True),
        _Request(),
        current_user={"id": 7, "username": "user", "is_admin": False},
        _perm=None,
    )
    assert called["kb"] == 0
    await response.body_iterator.aclose()
