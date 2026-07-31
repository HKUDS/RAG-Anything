import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from raganything.routers import autorepair


_USER_WITH_AUTOREPAIR_PERMISSION = {
    "id": 41,
    "username": "autorepair-editor",
    "is_admin": False,
    "allowed_kbs": [],
}
_LEGACY_URL = f"/api/knowledge/media/legacy/abcdefghijklmnopqrstuvwx.{'a' * 64}?kb=verified-kb"


def test_autorepair_media_sanitizer_preserves_only_opaque_delivery_metadata():
    payload = autorepair._sanitize_media_payloads([{
        "url": _LEGACY_URL,
        "legacy_grant": f"abcdefghijklmnopqrstuvwx.{'a' * 64}",
        "media_id": "should-not-be-needed",
        "kb": "verified-kb",
        "caption": r"C:\\private\\figure.png",
    }], "verified-kb")

    assert payload[0]["legacy_grant"].startswith("abcdefghijklmnopqrstuvwx.")
    assert payload[0]["kb"] == "verified-kb"
    assert r"C:\\private" not in payload[0]["caption"]


@pytest.mark.asyncio
async def test_all_autorepair_kb_routes_fail_before_kb_components(monkeypatch):
    checked: list[str] = []

    async def deny_kb_access(*, kb, current_user):
        assert current_user == _USER_WITH_AUTOREPAIR_PERMISSION
        checked.append(kb)
        raise HTTPException(403, "forbidden")

    def unexpected_component(*_args, **_kwargs):
        raise AssertionError("KB component was created before access was verified")

    async def unexpected_async_component(*_args, **_kwargs):
        raise AssertionError("KB component was created before access was verified")

    monkeypatch.setattr(autorepair, "verify_kb_access", deny_kb_access)
    monkeypatch.setattr(autorepair, "_get_ar_graph", unexpected_component)
    monkeypatch.setattr(autorepair, "_get_ar_qa_engine", unexpected_async_component)
    monkeypatch.setattr(autorepair, "_get_ar_agent_components", unexpected_async_component)
    monkeypatch.setattr(autorepair, "_get_autorepair", unexpected_component)
    monkeypatch.setattr(autorepair.shared, "API_KEY", "configured")
    monkeypatch.setattr(autorepair.shared, "BASE_URL", "https://llm.invalid")

    calls = [
        lambda: autorepair.ar_kg_summary(
            kb="private-kb", _perm=None, current_user=_USER_WITH_AUTOREPAIR_PERMISSION
        ),
        lambda: autorepair.ar_kg_nodes(
            kb="private-kb", _perm=None, current_user=_USER_WITH_AUTOREPAIR_PERMISSION
        ),
        lambda: autorepair.ar_kg_edges(
            kb="private-kb", _perm=None, current_user=_USER_WITH_AUTOREPAIR_PERMISSION
        ),
        lambda: autorepair.ar_kg_node_detail(
            "node-1",
            kb="private-kb",
            _perm=None,
            current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
        ),
        lambda: autorepair.ar_kg_lineage(
            "node-1",
            kb="private-kb",
            _perm=None,
            current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
        ),
        lambda: autorepair.ar_dashboard(
            kb="private-kb", _perm=None, current_user=_USER_WITH_AUTOREPAIR_PERMISSION
        ),
        lambda: autorepair.ar_qa(
            autorepair.AutoRepairAgentQuery(query="check pump status"),
            kb="private-kb",
            _perm=None,
            current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
        ),
        lambda: autorepair.ar_qa_stream(
            autorepair.AutoRepairAgentQuery(query="check pump status"),
            kb="private-kb",
            _perm=None,
            current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
        ),
        lambda: autorepair.ar_diagnosis_start(
            autorepair.AutoRepairDiagnosisStart(query="check pump status"),
            kb="private-kb",
            _perm=None,
            current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
        ),
        lambda: autorepair.ar_diagnosis_continue(
            autorepair.AutoRepairDiagnosisContinue(
                session_id="session-1", query="check pump status"
            ),
            kb="private-kb",
            _perm=None,
            current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
        ),
    ]

    for call in calls:
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 403

    assert checked == ["private-kb"] * len(calls)


@pytest.mark.asyncio
async def test_ar_kb_list_filters_inaccessible_kbs(monkeypatch):
    async def list_autorepair_kbs(domain):
        assert domain == "autorepair"
        return {
            "allowed-kb": {"name": "Allowed", "owner_username": "owner-a"},
            "private-kb": {"name": "Private", "owner_username": "owner-b"},
        }

    async def verify_access(*, kb, current_user):
        assert current_user == _USER_WITH_AUTOREPAIR_PERMISSION
        if kb == "private-kb":
            raise HTTPException(403, "forbidden")
        return kb

    monkeypatch.setattr(
        "raganything.services.kb_service.list_kbs_by_domain",
        list_autorepair_kbs,
    )
    monkeypatch.setattr(autorepair, "verify_kb_access", verify_access)

    result = await autorepair.ar_kb_list(
        _perm=None,
        current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
    )

    assert result == {
        "knowledge_bases": [
            {
                "name": "allowed-kb",
                "label": "Allowed",
                "created": "",
                "owner_username": "owner-a",
            }
        ]
    }


@pytest.mark.asyncio
async def test_ar_qa_uses_verified_kb_name(monkeypatch):
    used: dict[str, object] = {}

    async def allow_kb_access(*, kb, current_user):
        assert kb == "requested-kb"
        assert current_user == _USER_WITH_AUTOREPAIR_PERMISSION
        return "verified-kb"

    class _Engine:
        async def answer(self, query, context=None):
            return SimpleNamespace(
                query=query,
                answer=r"answer C:\private\answer.txt",
                citations=[{"source": r"file:///C:/private/source.pdf"}],
                related_images=[{
                    "data_url": _LEGACY_URL,
                    "caption": r"caption C:\private\figure.png",
                }],
                confidence=0.8,
                processing_time_ms=12,
                needs_human_review=False,
                trace=[{
                    "step": 1,
                    "thought": r"read C:\private\figure.png",
                    "action": r"file:///C:/private/action",
                    "observation": r"Image Path: C:\private\figure.png",
                }],
            )

    async def get_engine(kb):
        used["engine_kb"] = kb
        return _Engine()

    class _Dashboard:
        async def log_query(self, **kwargs):
            used["dashboard_kb"] = kwargs["kb_name"]

    monkeypatch.setattr(autorepair, "verify_kb_access", allow_kb_access)
    monkeypatch.setattr(autorepair, "_get_ar_qa_engine", get_engine)
    monkeypatch.setattr(
        autorepair,
        "_get_autorepair",
        lambda: {"dashboard": _Dashboard()},
    )

    result = await autorepair.ar_qa(
        autorepair.AutoRepairAgentQuery(query="check pump status"),
        kb="requested-kb",
        _perm=None,
        current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
    )

    serialized = json.dumps(result)
    assert r"C:\private" not in serialized
    assert "file:///" not in serialized
    assert result["related_images"][0]["data_url"].startswith(
        "/api/knowledge/media/legacy/"
    )
    assert result["trace"][0]["thought"] == ""
    assert result["trace"][0]["observation"] == ""
    assert used == {"engine_kb": "verified-kb", "dashboard_kb": "verified-kb"}


@pytest.mark.asyncio
async def test_ar_qa_stream_redacts_observations_and_exception_details(monkeypatch):
    private_path = r"C:\private\document\figure.png"

    async def allow_kb_access(*, kb, current_user):
        assert kb == "requested-kb"
        assert current_user == _USER_WITH_AUTOREPAIR_PERMISSION
        return "verified-kb"

    class _Engine:
        async def answer_stream(self, _query):
            yield {
                "type": "thinking",
                "step": 1,
                "thought": "retrieved",
                "action": "search",
                "observation": f"Image Path: {private_path}",
            }
            raise RuntimeError(f"failed to read {private_path}")

    async def get_engine(kb):
        assert kb == "verified-kb"
        return _Engine()

    monkeypatch.setattr(autorepair, "verify_kb_access", allow_kb_access)
    monkeypatch.setattr(autorepair, "_get_ar_qa_engine", get_engine)
    monkeypatch.setattr(autorepair.shared, "API_KEY", "configured")
    monkeypatch.setattr(autorepair.shared, "BASE_URL", "https://llm.invalid")

    response = await autorepair.ar_qa_stream(
        autorepair.AutoRepairAgentQuery(query="check pump status"),
        kb="requested-kb",
        _perm=None,
        current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    payload = "".join(chunks)

    assert "AutoRepair query failed" in payload
    assert private_path not in payload
    assert "Image Path:" not in payload
    assert "data:image" not in payload


@pytest.mark.asyncio
async def test_ar_qa_stream_sanitizes_split_tokens_and_image_payload(monkeypatch):
    private_path = r"C:\private\document\figure.png"
    controlled_url = _LEGACY_URL

    async def allow_kb_access(**_kwargs):
        return "verified-kb"

    class _Engine:
        async def answer_stream(self, _query):
            yield {
                "type": "thinking",
                "step": 1,
                "thought": private_path,
                "action": f"file:///{private_path}",
                "observation": private_path,
            }
            yield {"type": "token", "content": "路径C:"}
            yield {"type": "token", "content": "\\private\\document\\figure.png\n"}
            yield {
                "type": "done",
                "images": [
                    {
                        "data_url": controlled_url,
                        "caption": f"caption {private_path}",
                        "page": 1,
                        "relevance": 0.8,
                    },
                    {
                        "data_url": "data:image/png;base64,c2VjcmV0",
                        "caption": private_path,
                    },
                ],
                "confidence": 0.8,
            }

    async def get_engine(kb):
        assert kb == "verified-kb"
        return _Engine()

    class _Dashboard:
        async def log_query(self, **_kwargs):
            return None

    monkeypatch.setattr(autorepair, "verify_kb_access", allow_kb_access)
    monkeypatch.setattr(autorepair, "_get_ar_qa_engine", get_engine)
    monkeypatch.setattr(
        autorepair, "_get_autorepair", lambda: {"dashboard": _Dashboard()}
    )
    monkeypatch.setattr(autorepair.shared, "API_KEY", "configured")
    monkeypatch.setattr(autorepair.shared, "BASE_URL", "https://llm.invalid")

    response = await autorepair.ar_qa_stream(
        autorepair.AutoRepairAgentQuery(query="check pump status"),
        kb="requested-kb",
        _perm=None,
        current_user=_USER_WITH_AUTOREPAIR_PERMISSION,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    payload = "".join(chunks)

    assert controlled_url in payload
    assert private_path not in payload
    assert "file:///" not in payload
    assert "data:image" not in payload


class _DummyRAG:
    async def aquery(self, *_args, **_kwargs):
        return "retrieved context with enough content for direct answer " * 3


async def _collect_stream_events(engine):
    return [event async for event in engine.answer_stream("check pump status")]


@pytest.mark.asyncio
async def test_qa_engine_fails_closed_without_controlled_media_resolver(monkeypatch):
    from raganything.autorepair.agent.qa_engine import QAEngine

    local_path = r"C:\private\document\figure.png"

    async def llm(*_args, **_kwargs):
        return "answer"

    async def recall(_instance, _query, kb_name, _ctx):
        assert kb_name == "verified-kb"
        return [local_path], "", "direct"

    monkeypatch.setattr(
        "raganything.autorepair.agent.qa_engine.recall_query_images", recall
    )
    engine = QAEngine(
        rag_client=_DummyRAG(),
        llm_client=llm,
        kb_name="verified-kb",
    )

    events = await _collect_stream_events(engine)
    done = next(event for event in events if event["type"] == "done")
    serialized = json.dumps(done)

    assert done["images"] == []
    assert local_path not in serialized
    assert "data:image" not in serialized


@pytest.mark.asyncio
async def test_qa_engine_emits_only_controlled_media_url(monkeypatch):
    from raganything.autorepair.agent.qa_engine import QAEngine

    local_path = r"C:\controlled\odl-artifacts\figure.png"
    controlled_url = _LEGACY_URL

    async def llm(*_args, **_kwargs):
        return "answer"

    async def recall(_instance, _query, kb_name, _ctx):
        assert kb_name == "verified-kb"
        return [local_path], "", "direct"

    async def resolve_media(path):
        assert path == local_path
        return controlled_url

    monkeypatch.setattr(
        "raganything.autorepair.agent.qa_engine.recall_query_images", recall
    )
    engine = QAEngine(
        rag_client=_DummyRAG(),
        llm_client=llm,
        kb_name="verified-kb",
        media_url_resolver=resolve_media,
    )

    events = await _collect_stream_events(engine)
    done = next(event for event in events if event["type"] == "done")
    serialized = json.dumps(done)

    assert done["images"][0]["data_url"] == controlled_url
    assert done["images"][0]["url"] == controlled_url
    assert local_path not in serialized
    assert "data:image" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_value",
    [
        "data:image/png;base64,c2VjcmV0",
        r"C:\private\document\figure.png",
        "file:///private/document/figure.png",
        "/api/knowledge/media/../../private?kb=verified-kb",
        "/api/knowledge/media/opaque123?broken",
        "/api/knowledge/media/opaque123?kb=verified-kb&path=file:///private",
        "/api/knowledge/media/opaque123?kb=another-kb",
        "http://[::1",
        "//[invalid",
    ],
)
async def test_qa_engine_rejects_unsafe_media_resolver_output(
    monkeypatch, unsafe_value
):
    from raganything.autorepair.agent.qa_engine import QAEngine

    async def llm(*_args, **_kwargs):
        return "answer"

    async def recall(*_args, **_kwargs):
        return [r"C:\controlled\figure.png"], "", "direct"

    monkeypatch.setattr(
        "raganything.autorepair.agent.qa_engine.recall_query_images", recall
    )
    engine = QAEngine(
        rag_client=_DummyRAG(),
        llm_client=llm,
        kb_name="verified-kb",
        media_url_resolver=lambda _path: unsafe_value,
    )

    events = await _collect_stream_events(engine)
    done = next(event for event in events if event["type"] == "done")

    assert done["images"] == []


@pytest.mark.asyncio
async def test_production_qa_engine_uses_shared_controlled_media_directory(
    monkeypatch
):
    local_path = r"C:\controlled\odl-artifacts\figure.png"
    controlled_url = _LEGACY_URL
    components = {}

    async def get_kb(kb_name):
        assert kb_name == "verified-kb"
        return object()

    async def resolve_payload(*, kb_name, image_path):
        assert kb_name == "verified-kb"
        assert image_path == local_path
        return {"url": controlled_url}

    monkeypatch.setattr(autorepair, "_get_autorepair", lambda: components)
    monkeypatch.setattr(autorepair.shared, "get_kb", get_kb)
    monkeypatch.setattr(
        autorepair.shared,
        "resolve_controlled_media_payload",
        resolve_payload,
        raising=False,
    )

    engine = await autorepair._get_ar_qa_engine("verified-kb")

    assert await engine._resolve_media_url(local_path) == controlled_url


@pytest.mark.asyncio
async def test_production_media_directory_absence_fails_closed(monkeypatch):
    monkeypatch.delattr(
        autorepair.shared,
        "resolve_controlled_media_payload",
        raising=False,
    )

    assert await autorepair._resolve_autorepair_media_url(
        "verified-kb", r"C:\controlled\figure.png"
    ) is None


@pytest.mark.asyncio
async def test_qa_engine_llm_failure_does_not_echo_retrieval_context(monkeypatch):
    from raganything.autorepair.agent.qa_engine import QAEngine

    private_path = r"C:\private\document\figure.png"

    class _PathRAG:
        async def aquery(self, *_args, **_kwargs):
            return f"Image Path: {private_path}\n" + ("retrieved context " * 20)

    async def failing_llm(*_args, **_kwargs):
        raise RuntimeError(f"failed while reading {private_path}")

    async def no_images(*_args, **_kwargs):
        return [], "", "none"

    monkeypatch.setattr(
        "raganything.autorepair.agent.qa_engine.recall_query_images", no_images
    )

    engine = QAEngine(
        rag_client=_PathRAG(),
        llm_client=failing_llm,
        kb_name="verified-kb",
    )

    events = await _collect_stream_events(engine)
    serialized = json.dumps(events, ensure_ascii=False)

    assert "回答生成服务暂时不可用。" in serialized
    assert private_path not in serialized
    assert "data:image" not in serialized
