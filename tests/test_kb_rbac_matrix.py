import pytest
from fastapi import BackgroundTasks, HTTPException

from raganything.permissions import Permission
from raganything.routers import knowledge


class _DummyKB:
    def __init__(self):
        self.lightrag = object()


def _route_dependency_names(path: str, method: str) -> list[str]:
    for route in knowledge.router.routes:
        if getattr(route, "path", None) == path and method.upper() in getattr(route, "methods", set()):
            return [
                getattr(getattr(dep, "call", None), "__name__", repr(getattr(dep, "call", None)))
                for dep in route.dependant.dependencies
            ]
    raise AssertionError(f"route not found: {method} {path}")


@pytest.mark.asyncio
async def test_viewer_cannot_create_kb(monkeypatch):
    async def fake_load_kb_meta():
        return {}

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)

    async def deny_permission(user_id, permission):
        assert user_id == 11
        assert permission == Permission.KB_WRITE
        return False

    monkeypatch.setattr("raganything.dependencies._auth_has_permission", deny_permission)

    checker = knowledge.require_permission(Permission.KB_WRITE)
    with pytest.raises(HTTPException) as exc:
        await checker(
            request=type("Req", (), {"url": type("Url", (), {"path": "/api/kb/create"})(), "method": "POST", "client": None})(),
            current_user={"id": 11, "username": "viewer", "role": {"name": "viewer"}},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_create_kb(monkeypatch):
    saved = {}

    async def fake_load_kb_meta():
        return {}

    async def fake_save_kb_meta(meta):
        saved.update(meta)

    async def fake_get_kb(name):
        return _DummyKB()

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "save_kb_meta", fake_save_kb_meta)
    monkeypatch.setattr(knowledge, "get_kb", fake_get_kb)

    result = await knowledge.create_kb(
        kb_name="test701",
        _perm=None,
        current_user={"id": 21, "username": "editor", "is_admin": False},
        label="test701",
        domain="general",
    )

    assert result["status"] == "created"
    assert "test701" in saved
    assert saved["test701"]["owner_id"] == 21


@pytest.mark.asyncio
async def test_viewer_list_kbs_does_not_autocreate_personal_kb(monkeypatch):
    async def fake_load_kb_meta():
        return {}

    async def fake_save_kb_meta(_meta):
        raise AssertionError("viewer should not auto-create a knowledge base")

    async def deny_permission(user_id, permission):
        assert user_id == 31
        assert permission == Permission.KB_WRITE
        return False

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "save_kb_meta", fake_save_kb_meta)
    monkeypatch.setattr("raganything.routers.knowledge._auth_has_permission", deny_permission)

    result = await knowledge.list_kbs(current_user={"id": 31, "username": "viewer", "is_admin": False})

    assert result["knowledge_bases"] == []


@pytest.mark.asyncio
async def test_kb_write_routes_require_kb_write_permission():
    guarded_routes = [
        ("POST", "/upload"),
        ("POST", "/upload/batch"),
        ("POST", "/upload/folder"),
        ("POST", "/upload/content"),
        ("POST", "/upload/url"),
        ("DELETE", "/upload/tasks/{task_id}"),
        ("DELETE", "/knowledge/documents/{doc_id}"),
        ("POST", "/knowledge/documents/batch-delete"),
        ("POST", "/knowledge/documents/{doc_id}/retry"),
        ("POST", "/kb/create"),
    ]

    for method, path in guarded_routes:
        dependency_names = _route_dependency_names(path, method)
        assert "require_kb_write" in dependency_names, f"missing kb:write guard on {method} {path}"


def test_odl_media_routes_require_kb_read_permission():
    for path in ("/knowledge/media/{media_id}", "/knowledge/media/legacy/{grant}"):
        dependency_names = _route_dependency_names(path, "GET")
        assert "require_kb_read" in dependency_names


def test_reprocess_multimodal_requires_kb_write_permission():
    dependency_names = _route_dependency_names(
        "/kb/{kb_name}/reprocess-multimodal", "POST"
    )
    assert "require_kb_write" in dependency_names


@pytest.mark.asyncio
async def test_reprocess_multimodal_rejects_unscoped_kb_before_work(monkeypatch):
    async def deny_kb(_kb_name, _current_user):
        raise HTTPException(403, "forbidden")

    async def unexpected_work(_kb_name):
        raise AssertionError("must not begin work before KB access is verified")

    monkeypatch.setattr(knowledge, "verify_kb_access", deny_kb)
    monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", unexpected_work)

    with pytest.raises(HTTPException) as exc:
        await knowledge.reprocess_multimodal(
            "another-kb",
            BackgroundTasks(),
            current_user={"id": 21, "username": "editor", "is_admin": False},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_kb_route_requires_kb_delete_permission():
    dependency_names = _route_dependency_names("/kb/{name}", "DELETE")
    assert "require_kb_delete" in dependency_names


@pytest.mark.asyncio
async def test_admin_can_delete_kb(monkeypatch):
    cleaned = []

    async def fake_load_kb_meta():
        return {
            "test702": {
                "owner_id": 41,
                "owner_username": "editor",
            }
        }

    async def fake_cleanup(name):
        cleaned.append(name)

    async def fake_delete_tags(_name):
        return None

    async def fake_delete_tag_jobs(_name):
        return None

    monkeypatch.setattr(knowledge, "load_kb_meta", fake_load_kb_meta)
    monkeypatch.setattr(knowledge, "cleanup_kb_resources", fake_cleanup)
    monkeypatch.setattr(knowledge, "delete_kb_tags", fake_delete_tags)
    from raganything.services import document_tagging
    monkeypatch.setattr(document_tagging, "delete_kb_tag_jobs", fake_delete_tag_jobs)

    result = await knowledge.delete_kb(
        name="test702",
        _perm=None,
        current_user={"id": 1, "username": "admin", "is_admin": True},
    )

    assert result == {"status": "deleted", "name": "test702"}
    assert cleaned == ["test702"]
