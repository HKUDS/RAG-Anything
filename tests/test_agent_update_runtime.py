from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from raganything.routers import agent as agent_router
from raganything.services import pg_agent_repo, user_settings


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


def _stub_runtime_services(monkeypatch, vision_models, *, llm_func=None, vlm_available=True):
    async def resolve_settings(_user_id):
        return _resolved_settings()

    async def platform_settings():
        return {"settings": {"limits": {"interactive_wait_seconds": 0}}}

    async def acquire_lease(*_args, **_kwargs):
        return "lease-1"

    async def lease_ok(*_args, **_kwargs):
        return True

    async def query_scope(*_args, **_kwargs):
        return {
            "workspace": "kb-alpha",
            "corpus_revision": "revision-1",
            "permission_scope": "user:7",
            "settings_fingerprint": "settings-fingerprint",
            "llm_profile_fingerprint": "llm-fingerprint",
        }

    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", resolve_settings)
    monkeypatch.setattr(user_settings, "get_platform_settings", platform_settings)
    monkeypatch.setattr(user_settings, "acquire_quota_lease", acquire_lease)
    monkeypatch.setattr(user_settings, "heartbeat_quota_lease", lease_ok)
    monkeypatch.setattr(user_settings, "release_quota_lease", lease_ok)
    monkeypatch.setattr(agent_router, "_query_cache_scope", query_scope)
    monkeypatch.setattr(
        vision_models,
        "require_available",
        lambda _profile_id, kind: (
            (_ for _ in ()).throw(RuntimeError("vlm unavailable"))
            if kind == "vlm" and not vlm_available
            else SimpleNamespace(
                profile=SimpleNamespace(kind=kind, available=True),
                fingerprint=f"{kind}-fingerprint",
            )
        ),
    )
    monkeypatch.setattr(
        vision_models,
        "build_llm_callable",
        lambda *_args, **_kwargs: llm_func,
    )
    monkeypatch.setattr(vision_models, "activate_llm_selection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(vision_models, "reset_llm_snapshot", lambda _token: None)


def _query_lease(instance):
    async def release():
        return None

    return SimpleNamespace(instance=instance, release=release)


def _make_agent(**overrides):
    agent = {
        "id": "agent-1",
        "name": "Agent One",
        "icon": "A",
        "description": "original description",
        "welcome_message": "hello",
        "kb_name": "kb-alpha",
        "llm_model": "qwen-plus",
        "temperature": 0.3,
        "max_response_tokens": 2048,
        "query_mode": "hybrid",
        "agent_mode": "none",
        "retrieval_top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": False,
        "include_references": True,
        "system_prompt": "custom instructions",
        "use_default_prompt": True,
        "owner_id": 7,
        "owner_username": "alice",
        "template_id": "",
        "created_at": "2026-07-08T00:00:00+00:00",
        "updated_at": "2026-07-08T00:00:00+00:00",
    }
    agent.update(overrides)
    return agent


class _DummyRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


async def _consume_streaming_response(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_update_agent_preserves_empty_string_clears_and_omits_unsent_fields(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    existing_agent = _make_agent()
    captured = {}

    async def fake_get_agent(agent_id):
        assert agent_id == "agent-1"
        return dict(existing_agent)

    async def fake_update_agent(agent_id, updates):
        captured["agent_id"] = agent_id
        captured["updates"] = dict(updates)
        merged = dict(existing_agent)
        merged.update(updates)
        return merged

    async def unexpected_verify_kb_access(**_kwargs):
        raise AssertionError("verify_kb_access should not run when kb_name is omitted")

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "pg_update_agent", fake_update_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", unexpected_verify_kb_access)

    response = await agent_router.update_agent(
        "agent-1",
        agent_router.AgentUpdateRequest(
            description="",
            welcome_message="",
            llm_model="qwen-max",
        ),
        current_user=current_user,
        _perm=None,
    )

    assert captured["agent_id"] == "agent-1"
    assert captured["updates"] == {
        "description": "",
        "welcome_message": "",
        "llm_model": "qwen-max",
    }
    assert response["agent"]["description"] == ""
    assert response["agent"]["welcome_message"] == ""
    assert response["agent"]["llm_model"] == "qwen-max"


@pytest.mark.asyncio
async def test_update_agent_rejects_forbidden_kb_change_before_persisting(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    update_called = {"value": False}

    async def fake_get_agent(_agent_id):
        return _make_agent()

    async def fake_verify_kb_access(**_kwargs):
        raise HTTPException(status_code=403, detail="forbidden kb")

    async def fake_update_agent(_agent_id, _updates):
        update_called["value"] = True
        return _make_agent()

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "pg_update_agent", fake_update_agent)

    with pytest.raises(HTTPException) as exc_info:
        await agent_router.update_agent(
            "agent-1",
            agent_router.AgentUpdateRequest(kb_name="kb-forbidden"),
            current_user=current_user,
            _perm=None,
        )

    assert exc_info.value.status_code == 403
    assert update_called["value"] is False


@pytest.mark.asyncio
async def test_pg_update_agent_does_not_resurrect_legacy_json_agent(monkeypatch):
    class FakePool:
        def __init__(self):
            self.calls = []

        async def fetchrow(self, sql, *values):
            self.calls.append((sql, values))
            return None

    pool = FakePool()
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)
    monkeypatch.setattr(
        pg_agent_repo,
        "_json_get_agent",
        lambda _agent_id: (_ for _ in ()).throw(
            AssertionError("legacy JSON must not be read")
        ),
    )

    updated = await pg_agent_repo.pg_update_agent(
        "legacy-agent",
        {"name": "Updated Legacy Agent", "description": "", "llm_model": "qwen-max"},
    )

    assert updated is None
    assert len(pool.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_mode", ["none", "react", "cot"])
async def test_agent_query_stream_uses_latest_agent_runtime_config_in_all_modes(
    monkeypatch,
    agent_mode,
):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    runtime_agent = _make_agent(
        llm_model="qwen-max",
        temperature=0.8,
        query_mode="global",
        agent_mode=agent_mode,
        max_response_tokens=2222,
        system_prompt="follow the saved agent instructions",
        use_default_prompt=True,
    )
    expected_system_prompt = agent_router._build_agent_system_prompt(runtime_agent)

    openai_calls = []
    kb_calls = []
    query_core_acquisitions = []
    search_tool_calls = []
    agentic_init = {}

    async def fake_openai_complete(model, prompt, **kwargs):
        openai_calls.append({"model": model, "prompt": prompt, **kwargs})
        return "stub answer"

    class FakeKB:
        def __init__(self):
            self.config = SimpleNamespace(
                enforce_citation=False,
                vision_search_enabled=False,
            )

        async def aquery(self, query, mode="hybrid", **kwargs):
            kb_calls.append({"query": query, "mode": mode, "kwargs": kwargs})
            return "[来源 1]\n" + ("context " * 80)

        async def finalize_storages(self):
            return None

    class FakeSearchTool:
        def __init__(self, instance, query_mode, top_k, chunk_top_k, enable_rerank, include_references, tag_scope=None, **kwargs):
            search_tool_calls.append(
                {
                    "instance": instance,
                    "query_mode": query_mode,
                    "top_k": top_k,
                    "chunk_top_k": chunk_top_k,
                    "enable_rerank": enable_rerank,
                    "include_references": include_references,
                    "tag_scope": tag_scope,
                    **kwargs,
                }
            )

    class FakeAgenticRAG:
        def __init__(self, llm_func, max_steps, mode, max_response_tokens, system_prompt_override):
            self.llm_func = llm_func
            self.mode = mode
            agentic_init.update(
                {
                    "max_steps": max_steps,
                    "mode": mode,
                    "max_response_tokens": max_response_tokens,
                    "system_prompt_override": system_prompt_override,
                }
            )

        def register_tool(self, tool):
            self.tool = tool

        async def run_stream(self, query):
            await self.llm_func("react prompt")
            yield SimpleNamespace(
                type="done",
                answer="react answer",
                content=None,
                step=None,
                thought=None,
                action=None,
                observation=None,
                elapsed_ms=None,
            )

        async def run_with_context(self, query, context):
            await self.llm_func("cot prompt")
            return SimpleNamespace(
                answer="cot answer",
                trace=[
                    SimpleNamespace(
                        step_number=1,
                        thought="reasoning step",
                        elapsed_ms=11,
                    )
                ],
            )

    async def fake_verify_kb_access(kb, current_user):
        assert current_user["id"] == 7
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        query_core_acquisitions.append((_kb_name, _kwargs))
        return _query_lease(FakeKB())

    async def fake_pg_get_agent(_agent_id):
        return dict(runtime_agent)

    async def fake_pg_get_conversation(_agent_id, thread_id):
        return {"id": thread_id, "messages": []}

    async def fake_pg_add_message(*_args, **_kwargs):
        return True

    async def fake_record_query(*_args, **_kwargs):
        return None

    async def fake_recall_query_images(*_args, **_kwargs):
        return [], "", None

    async def fake_generate_summary(*_args, **_kwargs):
        return None

    async def selected_llm(prompt, **kwargs):
        return await fake_openai_complete("profile-model", prompt, **kwargs)

    def discard_background_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(agent_router, "openai_complete_if_cache", fake_openai_complete)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_get_agent", fake_pg_get_agent)
    monkeypatch.setattr(agent_router, "pg_get_conversation", fake_pg_get_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", fake_pg_add_message)
    monkeypatch.setattr(agent_router, "record_query", fake_record_query)
    monkeypatch.setattr(agent_router, "recall_query_images", fake_recall_query_images)
    monkeypatch.setattr(agent_router, "_maybe_generate_summary", fake_generate_summary)
    monkeypatch.setattr(agent_router.asyncio, "create_task", discard_background_task)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    from raganything.services import vision_models
    _stub_runtime_services(monkeypatch, vision_models, llm_func=selected_llm, vlm_available=False)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    if agent_mode in {"react", "cot"}:
        import raganything.agentic_rag as agentic_module

        monkeypatch.setattr(agentic_module, "AgenticRAG", FakeAgenticRAG)
        monkeypatch.setattr(agentic_module, "SearchTool", FakeSearchTool)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="Explain the topic", thread_id="thread-1"),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert openai_calls, f"expected llm call for mode={agent_mode}"
    llm_call = openai_calls[0]
    assert llm_call["model"] == "profile-model"
    assert llm_call["system_prompt"] == expected_system_prompt
    assert llm_call["temperature"] == pytest.approx(0.8)
    assert llm_call["max_tokens"] == 2222
    assert '"type": "done"' in body or '"type":"done"' in body
    assert query_core_acquisitions == [
        ("kb-alpha", {"corpus_revision": "revision-1"})
    ]

    if agent_mode == "none":
        assert kb_calls
        assert kb_calls[0]["mode"] == "global"
    elif agent_mode == "react":
        assert agentic_init["mode"] == "react"
        assert agentic_init["system_prompt_override"] == expected_system_prompt
        assert search_tool_calls[0]["query_mode"] == "global"
    else:
        assert agentic_init["mode"] == "cot"
        assert agentic_init["system_prompt_override"] == expected_system_prompt
        assert kb_calls
        assert kb_calls[0]["mode"] == "global"


@pytest.mark.asyncio
async def test_retrieval_only_query_emits_metadata_without_history_or_generation(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    agent = _make_agent(agent_mode="none")
    calls = {"aquery": 0}

    class FakeKB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **_kwargs):
            calls["aquery"] += 1
            return "[来源 1]\n" + ("context " * 40)

        async def finalize_storages(self):
            return None

    async def fake_get_agent(_agent_id):
        return dict(agent)

    async def fake_verify_kb_access(kb, current_user):
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        return _query_lease(FakeKB())

    def unexpected(*_args, **_kwargs):
        raise AssertionError("retrieval_only must not create history, write history, or call generation")

    from raganything.services import vision_models

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_create_conversation", unexpected)
    monkeypatch.setattr(agent_router, "pg_get_conversation", unexpected)
    monkeypatch.setattr(agent_router, "record_query", unexpected)
    monkeypatch.setattr(agent_router, "pg_add_message", unexpected)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    _stub_runtime_services(monkeypatch, vision_models)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="Explain the topic", retrieval_only=True),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert calls["aquery"] == 1
    assert '"type": "retrieval"' in body
    assert '"context_present": true' in body
    assert '"type": "done"' in body
    assert "context context" not in body
