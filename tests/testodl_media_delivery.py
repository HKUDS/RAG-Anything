from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from starlette.requests import Request
from httpx import ASGITransport, AsyncClient

from raganything.services.odl_media_delivery import (
    build_persisted_media_catalog,
    catalog_media_payload,
    issue_legacy_media_grant,
    issue_owned_legacy_media_grant,
    resolve_catalog_media,
    resolve_legacy_media_grant,
)
from raganything.services.odl_media_manifest import (
    bind_persisted_image_chunk,
    build_media_entry,
    write_pending_manifest,
)


@pytest.fixture(autouse=True)
def _reset_controlled_roots_cache(tmp_path, monkeypatch):
    """Clear the process-level controlled-roots TTL cache per test and pin
    the project root to a temp dir so real repo `output*` dirs stay inert."""
    from raganything.services.odl_media_delivery import _reset_controlled_roots_cache

    _reset_controlled_roots_cache()
    monkeypatch.setattr(
        "raganything.services.odl_media_delivery._project_root",
        lambda: Path(tmp_path),
    )


def _persisted_catalog(tmp_path: Path, monkeypatch, *, kb_name: str = "kb-visible"):
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(tmp_path))
    image = tmp_path / "figure.png"
    image.write_bytes(b"png-image")
    entry = build_media_entry(
        path=image,
        output_root=tmp_path,
        page=1,
        element_id="image-1",
        caption="caption",
    )
    manifest = tmp_path / "media.json"
    write_pending_manifest(manifest, [entry])
    assert bind_persisted_image_chunk(
        manifest,
        media_id=entry["media_id"],
        document_id="doc-1",
        chunk_id="chunk-1",
    )
    catalog = build_persisted_media_catalog(
        {str(manifest)}, kb_name=kb_name, document_id="doc-1", workspace="workspace-1"
    )
    assert catalog is not None
    return image, entry, catalog


def test_catalog_resolves_only_persisted_valid_media(tmp_path, monkeypatch):
    image, entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    resolved = resolve_catalog_media(catalog, kb_name="kb-visible", media_id=entry["media_id"])
    assert resolved is not None
    assert resolved.path == image.resolve()
    assert resolved.caption == "caption"

    image.write_bytes(b"tampered")
    assert resolve_catalog_media(catalog, kb_name="kb-visible", media_id=entry["media_id"]) is None


def test_catalog_rejects_cross_kb_resolution(tmp_path, monkeypatch):
    _image, entry, catalog = _persisted_catalog(tmp_path, monkeypatch, kb_name="kb-a")
    assert resolve_catalog_media(catalog, kb_name="other-kb", media_id=entry["media_id"]) is None


def test_repeated_identical_media_in_distinct_parser_runs_have_distinct_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(tmp_path))
    first_root = tmp_path / "run-a"
    second_root = tmp_path / "run-b"
    first_root.mkdir()
    second_root.mkdir()
    first = first_root / "figure.png"
    second = second_root / "figure.png"
    first.write_bytes(b"same-image")
    second.write_bytes(b"same-image")

    first_entry = build_media_entry(path=first, output_root=first_root, page=1, element_id="image-1", caption="")
    second_entry = build_media_entry(path=second, output_root=second_root, page=1, element_id="image-1", caption="")

    assert first_entry["media_id"] != second_entry["media_id"]


def test_controlled_media_url_encodes_kb_query_value(tmp_path, monkeypatch):
    image, _entry, catalog = _persisted_catalog(tmp_path, monkeypatch, kb_name="kb&scope")

    payload = catalog_media_payload(catalog, kb_name="kb&scope", path=str(image))

    assert payload is not None
    assert payload["kb"] == "kb&scope"
    assert payload["url"].startswith("/api/knowledge/media/")
    assert payload["url"].endswith("?kb=kb%26scope")
    assert str(image) not in payload["url"]


def test_catalog_payload_ignores_disappeared_recall_candidate(tmp_path, monkeypatch):
    _image, _entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    missing = tmp_path / "missing.png"

    assert catalog_media_payload(catalog, kb_name="kb-visible", path=str(missing)) is None


def test_catalog_rejects_duplicate_traversal_and_path_leaking_payload(tmp_path, monkeypatch):
    image, entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    assert resolve_catalog_media(catalog + catalog, kb_name="kb-visible", media_id=entry["media_id"]) is None

    payload = catalog_media_payload(catalog, kb_name="kb-visible", path=str(image))
    assert payload is not None
    assert str(image) not in json.dumps(payload)
    assert payload["media_id"] == entry["media_id"]
    assert payload["url"].startswith("/api/knowledge/media/")
    assert payload["kb"] == "kb-visible"

    escaped = dict(catalog[0])
    escaped["root_relative_path"] = "../outside.png"
    assert resolve_catalog_media([escaped], kb_name="kb-visible", media_id=entry["media_id"]) is None


def test_catalog_rejects_manifest_relative_path_traversal(tmp_path, monkeypatch):
    image, entry, _catalog = _persisted_catalog(tmp_path, monkeypatch)
    manifest = tmp_path / "media.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["entries"][0]["relative_path"] = "../figure.png"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert build_persisted_media_catalog(
        {str(manifest)}, kb_name="kb-visible", document_id="doc-1", workspace="workspace-1"
    ) is None
    assert image.exists()
    assert entry["media_id"]


def test_catalog_rejects_manifest_mime_mismatch(tmp_path, monkeypatch):
    _image, _entry, _catalog = _persisted_catalog(tmp_path, monkeypatch)
    manifest = tmp_path / "media.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["entries"][0]["mime"] = "image/gif"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert build_persisted_media_catalog(
        {str(manifest)}, kb_name="workspace-1", document_id="doc-1"
    ) is None


def test_catalog_resolves_media_under_nested_parser_output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(tmp_path))
    run_root = tmp_path / "document" / "run-1"
    page_root = run_root / "page-1"
    page_root.mkdir(parents=True)
    image = page_root / "figure.png"
    image.write_bytes(b"nested-image")
    entry = build_media_entry(
        path=image,
        output_root=page_root,
        page=1,
        element_id="nested-image",
        caption="nested",
    )
    entry["media_root_relative_path"] = "page-1"
    manifest = run_root / "media.json"
    write_pending_manifest(manifest, [entry])
    assert bind_persisted_image_chunk(
        manifest, media_id=entry["media_id"], document_id="doc-1", chunk_id="chunk-1"
    )
    catalog = build_persisted_media_catalog({str(manifest)}, kb_name="visible-kb", document_id="doc-1", workspace="workspace")
    assert catalog is not None
    resolved = resolve_catalog_media(catalog, kb_name="visible-kb", media_id=entry["media_id"])
    assert resolved is not None
    assert resolved.path == image.resolve()


def test_legacy_grants_require_and_bind_persisted_ownership(tmp_path, monkeypatch):
    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    image = tmp_path / "legacy.png"
    image.write_bytes(b"legacy-image")
    assert issue_legacy_media_grant("kb-a", image) is None
    grant = issue_owned_legacy_media_grant(
        kb_name="kb-a",
        path=image,
        document_id="doc-1",
        chunk_id="chunk-1",
    )
    assert grant is not None
    assert str(image) not in grant
    assert resolve_legacy_media_grant("kb-a", grant) is not None
    assert resolve_legacy_media_grant("kb-b", grant) is None
    assert resolve_legacy_media_grant("kb-a", grant + "x") is None


@pytest.mark.asyncio
async def test_media_endpoint_uses_kb_access_and_never_accepts_paths(tmp_path, monkeypatch):
    from raganything.routers import knowledge

    _image, entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    seen = []

    async def allow_kb(kb, user):
        seen.append((kb, user["id"]))
        return kb

    async def doc_status(_kb):
        return {"doc-1": {"metadata": {"odl_media_catalog": catalog}}}

    monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", doc_status)
    response = await knowledge.serve_odl_media(entry["media_id"], kb="kb-visible", current_user={"id": 7})
    assert response.media_type == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert seen == [("kb-visible", 7)]

    with pytest.raises(HTTPException) as rejected:
        await knowledge.serve_odl_media("C:/not-a-media-id.png", kb="kb-visible", current_user={"id": 7})
    assert rejected.value.status_code == 404


@pytest.mark.asyncio
async def test_media_endpoint_asgi_enforces_authentication_and_kb_scope(tmp_path, monkeypatch):
    """Exercise the actual HTTP route without server startup side effects."""
    from raganything.routers import knowledge

    _image, entry, catalog = _persisted_catalog(
        tmp_path, monkeypatch, kb_name="kb-a"
    )
    app = FastAPI()
    app.include_router(knowledge.router)
    transport = ASGITransport(app=app)

    # No dependency override: the production bearer dependency must reject an
    # unauthenticated media request before any document status lookup.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauthenticated = await client.get(
            f"/knowledge/media/{entry['media_id']}", params={"kb": "kb-a"}
        )
    assert unauthenticated.status_code == 401

    route = next(
        route for route in knowledge.router.routes
        if getattr(route, "path", None) == "/knowledge/media/{media_id}"
    )
    permission_guard = route.dependant.dependencies[0].call
    app.dependency_overrides[permission_guard] = lambda: None
    app.dependency_overrides[knowledge.get_current_user] = lambda: {"id": 7}

    async def deny_kb(_kb, _user):
        raise HTTPException(403, "forbidden")

    monkeypatch.setattr(knowledge, "verify_kb_access", deny_kb)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        forbidden = await client.get(
            f"/knowledge/media/{entry['media_id']}", params={"kb": "kb-b"}
        )
    assert forbidden.status_code == 403

    async def allow_kb(kb, _user):
        assert kb == "kb-a"
        return kb

    async def doc_status(_kb):
        return {"doc-1": {"metadata": {"odl_media_catalog": catalog}}}

    monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", doc_status)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get(
            f"/knowledge/media/{entry['media_id']}", params={"kb": "kb-a"}
        )
    assert allowed.status_code == 200
    assert allowed.headers["content-type"].startswith("image/png")
    assert allowed.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_agent_sse_media_payloads_contain_no_filesystem_path(tmp_path, monkeypatch):
    from raganything.routers import agent

    image, _entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    active_reader = object()

    async def resolve_payload(*, kb_name, image_path, text_chunk_reader=None):
        assert kb_name == "kb-visible"
        assert text_chunk_reader is active_reader
        return catalog_media_payload(catalog, kb_name=kb_name, path=image_path)

    monkeypatch.setattr(agent, "resolve_controlled_media_payload", resolve_payload)
    payloads = await agent._controlled_recalled_media(
        "kb-visible", [str(image)], text_chunk_reader=active_reader
    )
    assert len(payloads) == 1
    assert str(image) not in json.dumps(payloads)
    assert payloads[0]["url"].startswith("/api/knowledge/media/")
    assert payloads[0]["kb"] == "kb-visible"


def test_agent_trace_sanitizer_removes_local_media_references():
    from raganything.routers.agent import _sanitize_client_trace_step

    safe = _sanitize_client_trace_step({
        "step": 1,
        "thought": r"Read C:\\private\\image.png",
        "observation": r"Image Path: C:\\private\\image.png",
        "action": "search",
    })

    assert safe["observation"] == ""
    assert r"C:\\private" not in safe["thought"]


@pytest.mark.asyncio
async def test_agent_stream_done_event_uses_controlled_media_payload(tmp_path, monkeypatch):
    """Consume the real stream generator without starting server workers."""
    from types import SimpleNamespace

    from raganything.routers import agent

    image, _entry, catalog = _persisted_catalog(tmp_path, monkeypatch)

    async def get_agent(_agent_id):
        return {
            "id": "agent-1",
            "name": "test-agent",
            "icon": "bot",
            "owner_id": 7,
            "kb_name": "kb-visible",
            "query_mode": "naive",
            "agent_mode": "none",
        }

    class Instance:
        config = SimpleNamespace(enforce_citation=False)
        lightrag = SimpleNamespace(text_chunks=object())

        async def aquery(self, *_args, **_kwargs):
            return "[来源 test]\nretrieval context"

    class VlmProfile:
        available = True

    async def selected_vlm(_user_id):
        return SimpleNamespace(profile=VlmProfile())

    async def controlled_recall(_instance, _query, _kb, _context):
        return [str(image)], "", "direct"

    async def noop(*_args, **_kwargs):
        return None

    async def answer_llm(**_kwargs):
        return "answer"

    async def doc_status(_kb):
        return {"doc-1": {"metadata": {"odl_media_catalog": catalog}}}

    monkeypatch.setattr(agent, "pg_get_agent", get_agent)
    monkeypatch.setattr(
        agent,
        "verify_kb_access",
        lambda kb, current_user: _async_value(kb),
    )
    released = 0

    class QueryLease:
        instance = Instance()

        async def release(self):
            nonlocal released
            released += 1

    monkeypatch.setattr(
        agent,
        "acquire_query_kb",
        lambda _kb, **_kwargs: _async_value(QueryLease()),
    )
    monkeypatch.setattr(agent, "recall_query_images", controlled_recall)
    async def resolve_payload(*, kb_name, image_path, text_chunk_reader=None):
        assert text_chunk_reader is QueryLease.instance.lightrag.text_chunks
        return catalog_media_payload(catalog, kb_name=kb_name, path=image_path)

    monkeypatch.setattr(agent, "resolve_controlled_media_payload", resolve_payload)
    monkeypatch.setattr(agent, "_build_agent_llm", lambda _runtime, _selected=None: answer_llm)
    monkeypatch.setattr(agent, "pg_add_message", noop)
    monkeypatch.setattr(agent, "record_query", noop)
    monkeypatch.setattr(agent, "pg_get_conversation", noop)
    from raganything.services import user_settings
    from tests.test_agent_update_runtime import _resolved_settings

    monkeypatch.setattr(
        user_settings,
        "resolve_user_settings_for_task",
        AsyncMock(return_value=_resolved_settings()),
    )
    monkeypatch.setattr(user_settings, "get_platform_settings", AsyncMock(return_value={
        "settings": {"limits": {"interactive_wait_seconds": 0}}
    }))
    monkeypatch.setattr(user_settings, "acquire_quota_lease", AsyncMock(return_value="lease-1"))
    monkeypatch.setattr(user_settings, "heartbeat_quota_lease", AsyncMock(return_value=True))
    monkeypatch.setattr(user_settings, "release_quota_lease", AsyncMock(return_value=True))
    monkeypatch.setattr(agent, "_query_cache_scope", AsyncMock(return_value={
        "workspace": "kb-visible", "settings_fingerprint": "settings-fingerprint"
    }))

    from raganything.services import vision_models

    monkeypatch.setattr(vision_models, "resolve_user_vlm_selection", selected_vlm)
    monkeypatch.setattr(
        vision_models,
        "require_available",
        lambda _profile_id, kind: SimpleNamespace(
            profile=SimpleNamespace(kind=kind, available=True),
            fingerprint=f"{kind}-fingerprint",
        ),
    )
    monkeypatch.setattr(vision_models, "build_llm_callable", lambda *_args, **_kwargs: answer_llm)
    monkeypatch.setattr(vision_models, "activate_llm_selection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(vision_models, "reset_llm_snapshot", lambda _token: None)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    response = await agent.agent_query_stream(
        "agent-1",
        agent.AgentQueryRequest(query="image question", thread_id="thread-1"),
        request,
        current_user={"id": 7, "username": "tester", "is_admin": False},
    )
    handlers_before = list(agent.lightrag_logger.handlers)
    parts = [part async for part in response.body_iterator]
    body = "".join(
        part.decode("utf-8") if isinstance(part, bytes) else part
        for part in parts
    )

    assert str(image) not in body
    done_lines = [line for line in body.splitlines() if '"type": "done"' in line]
    assert len(done_lines) == 1, body
    done = json.loads(done_lines[0].removeprefix("data: "))
    assert done["images"][0]["url"].startswith("/api/knowledge/media/")
    assert done["images"][0]["kb"] == "kb-visible"
    assert done["images"][0]["media_id"] == catalog[0]["media_id"]
    assert released == 1
    assert agent.lightrag_logger.handlers == handlers_before


async def _async_value(value):
    return value


def test_odl_chunk_serialization_uses_catalog_url_not_local_path(tmp_path, monkeypatch):
    from raganything.routers import knowledge

    image, _entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    serialized = knowledge._serialize_document_chunk(
        {
            "chunk_id": "chunk-1",
            "content": f"Image Path: {image}",
            "is_multimodal": True,
        },
        {},
        status_info={"metadata": {"odl_media_catalog": catalog}},
            kb="kb-visible",
    )

    assert serialized["media_id"] == catalog[0]["media_id"]
    assert serialized["media_path"] is None
    assert str(image) not in json.dumps(serialized)
    assert serialized["media_url"].startswith("/api/knowledge/media/")
    assert serialized["media_kb"] == "kb-visible"


def test_odl_chunk_without_catalog_fails_closed(tmp_path):
    from raganything.routers import knowledge

    image = tmp_path / "unowned.png"
    image.write_bytes(b"unowned")
    serialized = knowledge._serialize_document_chunk(
        {
            "chunk_id": "chunk-unowned",
            "content": f"Image Path: {image}",
            "is_multimodal": True,
        },
        {},
        status_info={"metadata": {"provenance_ref": "controlled-sidecar.json"}},
        kb="kb-visible",
    )

    assert serialized["media_id"] is None
    assert serialized["media_path"] is None
    assert serialized["media_url"] is None
    assert serialized["media_available"] is False
    assert str(image) not in json.dumps(serialized)


@pytest.mark.asyncio
async def test_raw_path_endpoint_is_retired():
    from raganything.routers import knowledge

    with pytest.raises(HTTPException) as rejected:
        await knowledge.serve_image()
    assert rejected.value.status_code == 410


@pytest.mark.asyncio
async def test_legacy_marker_delivery_requires_a_persisted_kb_chunk(tmp_path, monkeypatch):
    from raganything.routers import shared
    from raganything.services import kb_service

    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    image = tmp_path / "legacy.png"
    image.write_bytes(b"legacy-image")

    async def doc_status(_kb):
        return {
            "doc-1": {
                "chunks_list": ["chunk-1"],
                "metadata": {},
            }
        }

    class TextChunks:
        async def get_by_ids(self, ids):
            assert ids == ["chunk-1"]
            return [{"id": "chunk-1", "content": f"[图片路径：{image}]"}]

    async def get_kb(_kb):
        return SimpleNamespace(lightrag=SimpleNamespace(text_chunks=TextChunks()))

    monkeypatch.setattr(kb_service, "_load_doc_status_json", doc_status)
    monkeypatch.setattr(shared, "get_kb", get_kb)
    payload = await shared.resolve_controlled_media_payload(
        kb_name="kb-visible",
        image_path=str(image),
    )

    assert payload is not None
    assert payload["kb"] == "kb-visible"
    assert payload["legacy_grant"]
    assert str(image) not in json.dumps(payload)
    assert payload["url"].startswith("/api/knowledge/media/legacy/")

    async def no_marker(self, _ids):
        return [{"id": "chunk-1", "content": "no media marker"}]

    TextChunks.get_by_ids = no_marker
    assert await shared.resolve_controlled_media_payload(
        kb_name="kb-visible",
        image_path=str(image),
    ) is None


@pytest.mark.asyncio
async def test_image_search_omits_non_catalog_paths(tmp_path, monkeypatch):
    from raganything.routers import knowledge

    image, _entry, catalog = _persisted_catalog(tmp_path, monkeypatch)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")

    class Repo:
        async def reload(self):
            return None

        async def query(self, _vector, top_k):
            assert top_k == 10
            return [
                {
                    "image_path": str(image),
                    "entity_name": "catalog image",
                    "description": "controlled",
                    "_score": 0.9,
                },
                {
                    "image_path": str(outside),
                    "entity_name": "unowned image",
                    "description": "must be dropped",
                    "_score": 0.8,
                },
            ]

        def count(self):
            return 2

    class Vision:
        async def embed_image(self, _path):
            return [0.1, 0.2]

    async def get_kb(_kb):
        return SimpleNamespace(
            lightrag=SimpleNamespace(image_vision_repo=Repo()),
            vision_embed_func=Vision(),
        )

    async def doc_status(_kb):
        return {"doc-1": {"metadata": {"odl_media_catalog": catalog}}}

    monkeypatch.setenv("VISION_SEARCH_ENABLED", "true")
    monkeypatch.setattr(knowledge, "get_kb", get_kb)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", doc_status)
    monkeypatch.setattr(knowledge, "load_kb_meta", AsyncMock(return_value={
        "kb-visible": {"extra": {"vision_embedding": {
            "profile_id": "vision-test",
            "profile_fingerprint": "vision-fingerprint",
        }}}
    }))

    response = await knowledge.image_search(
        Request({"type": "http", "method": "POST", "path": "/"}),
        UploadFile(filename="query.png", file=BytesIO(b"query")),
        top_k=10,
        kb="kb-visible",
        current_user={"id": 7},
    )

    assert response["count"] == 1
    assert response["results"][0]["media_id"] == catalog[0]["media_id"]
    assert response["results"][0]["kb"] == "kb-visible"
    serialized = json.dumps(response)
    assert str(image) not in serialized
    assert str(outside) not in serialized
    assert "image_path" not in serialized


@pytest.mark.asyncio
async def test_multimodal_catalog_is_written_before_completion(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from raganything.processor.multimodal_processor import MultimodalProcessorMixin

    image, entry, _catalog = _persisted_catalog(tmp_path, monkeypatch)
    manifest = tmp_path / "media.json"

    class StatusStore:
        def __init__(self):
            self.status = {"metadata": {}}
            self.upserts = []

        async def get_by_id(self, _doc_id):
            return self.status

        async def upsert(self, payload):
            self.upserts.append(payload)
            self.status = payload["doc-1"]

        async def index_done_callback(self):
            return None

    store = StatusStore()
    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = MagicMock()
    processor.lightrag = SimpleNamespace(
        doc_status=store, workspace="./rag_storage_kb-visible"
    )
    processor._current_doc_status_timestamp = lambda: "now"

    async def persisted_ids(_doc_id):
        return {"chunk-1"}

    processor._persisted_chunk_ids_for_completion = persisted_ids
    complete = await processor._bind_and_audit_odl_image_media(
        "doc-1",
        [{
            "chunk_order_index": 0,
            "original_item": {
                "_odl_media": entry,
                "_odl_media_manifest_path": str(manifest),
            },
        }],
        {"chunk-1": {"chunk_order_index": 0}},
    )
    assert complete is True
    metadata = store.status["metadata"]
    assert metadata["odl_media_catalog"][0]["media_id"] == entry["media_id"]
    assert metadata["image_media_counts"]["catalog_media"] == 1
    assert metadata.get("multimodal_processed") is not True


@pytest.mark.asyncio
async def test_multimodal_final_audit_keeps_all_retry_batch_media(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from raganything.processor.multimodal_processor import MultimodalProcessorMixin

    monkeypatch.setenv("ODL_ARTIFACT_ROOT", str(tmp_path))
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first-image")
    second.write_bytes(b"second-image")
    entries = [
        build_media_entry(
            path=first, output_root=tmp_path, page=1,
            element_id="image-1", caption="first",
        ),
        build_media_entry(
            path=second, output_root=tmp_path, page=2,
            element_id="image-2", caption="second",
        ),
    ]
    manifest = tmp_path / "media.json"
    write_pending_manifest(manifest, entries)
    assert bind_persisted_image_chunk(
        manifest, media_id=entries[0]["media_id"], document_id="doc-1", chunk_id="chunk-1"
    )
    assert bind_persisted_image_chunk(
        manifest, media_id=entries[1]["media_id"], document_id="doc-1", chunk_id="chunk-2"
    )

    class StatusStore:
        def __init__(self):
            self.status = {"metadata": {}}

        async def get_by_id(self, _doc_id):
            return self.status

        async def upsert(self, payload):
            self.status = payload["doc-1"]

        async def index_done_callback(self):
            return None

    store = StatusStore()
    processor = object.__new__(MultimodalProcessorMixin)
    processor.logger = MagicMock()
    processor.lightrag = SimpleNamespace(
        doc_status=store, workspace="./rag_storage_kb-visible"
    )
    processor._current_doc_status_timestamp = lambda: "now"

    async def persisted_ids(_doc_id):
        return {"chunk-1", "chunk-2"}

    processor._persisted_chunk_ids_for_completion = persisted_ids
    completed = await processor._finalize_odl_image_media_contract(
        "doc-1",
        [
            {"_odl_media": entries[0], "_odl_media_manifest_path": str(manifest)},
            {"_odl_media": entries[1], "_odl_media_manifest_path": str(manifest)},
        ],
    )

    assert completed is True
    metadata = store.status["metadata"]
    assert metadata["image_media_counts"]["catalog_media"] == 2
    assert {item["media_id"] for item in metadata["odl_media_catalog"]} == {
        entries[0]["media_id"], entries[1]["media_id"],
    }
