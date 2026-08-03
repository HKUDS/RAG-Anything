"""Targeted tests for the harden-rbac-isolation backend changes.

Covers: GET /workflows/models read guard, workflow-run owner filtering,
WebSocket run ownership, vision-settings read guard, /upload/folder
whitelist, and cleanup_kb_resources collection-before-begin_deletion order.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.permissions import Permission  # noqa: E402


def _route_dependency_names(router, path: str, method: str) -> list[str]:
    for route in router.routes:
        if getattr(route, "path", None) == path and method.upper() in getattr(route, "methods", set()):
            return [
                getattr(getattr(dep, "call", None), "__name__", repr(getattr(dep, "call", None)))
                for dep in route.dependant.dependencies
            ]
    raise AssertionError(f"route not found: {method} {path}")


class _Req:
    url = type("Url", (), {"path": "/api/test"})()
    method = "GET"
    client = None


# ── GET /workflows/models guard ───────────────────────────

class TestWorkflowModelsGuard:
    def test_route_requires_workflow_read(self):
        from raganything.routers import admin

        names = _route_dependency_names(admin.router, "/workflows/models", "GET")
        assert "require_workflow_read" in names

    @pytest.mark.asyncio
    async def test_rejects_user_without_workflow_read(self, monkeypatch):
        from raganything.routers import admin

        async def deny(user_id, permission):
            assert permission == Permission.WORKFLOW_READ
            return False

        monkeypatch.setattr("raganything.dependencies._auth_has_permission", deny)
        checker = admin.require_permission(Permission.WORKFLOW_READ)
        with pytest.raises(HTTPException) as exc:
            await checker(
                request=_Req(),
                current_user={"id": 5, "username": "student", "role": {"name": "student"}},
            )
        assert exc.value.status_code == 403


# ── workflow run owner filtering ──────────────────────────

class _FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append((sql, args))
        return self.rows

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        return self.rows[0] if self.rows else None


class _FakePool:
    def __init__(self, rows):
        self.conn = _FakeConn(rows)

    def acquire(self):
        """Mimic asyncpg's pool.acquire() async context manager."""
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc_info):
        return False


RUN_ROWS = [{
    "run_id": "r1", "status": "completed", "started_at": None,
    "completed_at": None, "workflow_name": "wf",
}]


@pytest.fixture
def fake_wf_pool(monkeypatch):
    from raganything.routers import admin

    pool = _FakePool(RUN_ROWS)
    monkeypatch.setattr(admin, "_wf_pg_pool", AsyncMock(return_value=pool))
    return pool


class TestWorkflowRunOwnerFiltering:
    @pytest.mark.asyncio
    async def test_list_filters_by_owner_for_non_admin(self, fake_wf_pool):
        from raganything.routers import admin

        result = await admin.list_workflow_runs(
            workflow_id="wf1", _perm=None,
            current_user={"id": 7, "username": "t", "is_admin": False},
        )
        sql, args = fake_wf_pool.conn.queries[0]
        assert "user_id = $2" in sql
        assert args == ("wf1", 7)
        assert result["runs"][0]["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_list_admin_sees_all_runs(self, fake_wf_pool):
        from raganything.routers import admin

        result = await admin.list_workflow_runs(
            workflow_id="wf1", _perm=None,
            current_user={"id": 1, "username": "sa", "is_admin": True},
        )
        sql, args = fake_wf_pool.conn.queries[0]
        assert "user_id" not in sql
        assert args == ("wf1",)
        assert result["runs"][0]["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_detail_filters_by_owner_for_non_admin(self, fake_wf_pool):
        from raganything.routers import admin

        result = await admin.get_workflow_run(
            workflow_id="wf1", run_id="r1", _perm=None,
            current_user={"id": 7, "username": "t", "is_admin": False},
        )
        sql, args = fake_wf_pool.conn.queries[0]
        assert "user_id = $2" in sql
        assert args == ("r1", 7)
        assert result["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_detail_admin_sees_any_run(self, fake_wf_pool):
        from raganything.routers import admin

        result = await admin.get_workflow_run(
            workflow_id="wf1", run_id="r1", _perm=None,
            current_user={"id": 1, "username": "sa", "is_admin": True},
        )
        sql, args = fake_wf_pool.conn.queries[0]
        assert "user_id" not in sql
        assert args == ("r1",)
        assert result["run_id"] == "r1"


class TestWorkflowRunWebSocketOwnership:
    @pytest.mark.asyncio
    async def test_foreign_run_closed_with_4001(self, monkeypatch):
        from raganything.routers import admin

        calls = []

        class _FakeWS:
            async def close(self, code, reason):
                calls.append((code, reason))

            async def accept(self):
                calls.append("accepted")

        pool = _FakePool([])  # no rows -> run not owned
        monkeypatch.setattr(admin, "_wf_pg_pool", AsyncMock(return_value=pool))
        monkeypatch.setattr(admin, "_auth_user_is_admin", AsyncMock(return_value=False))

        async def fake_auth(ws_obj, required_permission=None):
            return {"id": 7, "username": "t"}

        monkeypatch.setattr(admin, "_authenticate_ws", fake_auth)

        await admin.websocket_workflow_run(_FakeWS(), "r1")
        assert calls == [(4001, "Run not found or not owned")]

    @pytest.mark.asyncio
    async def test_own_run_is_accepted(self, monkeypatch):
        from raganything.routers import admin

        calls = []

        class _FakeWS:
            async def close(self, code, reason):
                calls.append((code, reason))

            async def accept(self):
                calls.append("accepted")

            async def receive_text(self):
                calls.append("receive")
                raise RuntimeError("disconnect")

        pool = _FakePool([{"run_id": "r1"}])
        monkeypatch.setattr(admin, "_wf_pg_pool", AsyncMock(return_value=pool))
        monkeypatch.setattr(admin, "_auth_user_is_admin", AsyncMock(return_value=False))

        async def fake_auth(ws_obj, required_permission=None):
            return {"id": 7, "username": "t"}

        monkeypatch.setattr(admin, "_authenticate_ws", fake_auth)

        with pytest.raises(RuntimeError):
            await admin.websocket_workflow_run(_FakeWS(), "r1")
        assert calls == ["accepted", "receive"]


# ── vision-settings read guard ────────────────────────────

class TestVisionSettingsReadGuard:
    def test_get_uses_read_guard_and_put_keeps_write_guard(self):
        from raganything.routers import knowledge

        get_names = _route_dependency_names(knowledge.router, "/kb/{kb}/vision-settings", "GET")
        # GET uses the named read-access helper (kb:read inside); no bare permission closure.
        assert "_verify_kb_vision_read_access" in get_names
        assert "require_kb_read" not in get_names
        put_names = _route_dependency_names(knowledge.router, "/kb/{kb}/vision-settings", "PUT")
        assert "_verify_kb_vision_write_access" in put_names

    @pytest.mark.asyncio
    async def test_read_guard_requires_kb_read(self, monkeypatch):
        from raganything.routers import knowledge

        async def allow_kb(kb, user):
            return kb

        async def deny_permission(user_id, permission):
            assert permission == Permission.KB_READ
            return False

        monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
        monkeypatch.setattr("raganything.routers.knowledge._auth_has_permission", deny_permission)
        with pytest.raises(HTTPException) as exc:
            await knowledge._verify_kb_vision_read_access(
                kb="demo",
                current_user={"id": 9, "username": "s", "role": {"name": "student"}},
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_read_guard_allows_kb_read(self, monkeypatch):
        from raganything.routers import knowledge

        async def allow_kb(kb, user):
            return kb

        async def allow_permission(user_id, permission):
            return True

        monkeypatch.setattr(knowledge, "verify_kb_access", allow_kb)
        monkeypatch.setattr("raganything.routers.knowledge._auth_has_permission", allow_permission)
        result = await knowledge._verify_kb_vision_read_access(
            kb="demo",
            current_user={"id": 9, "username": "s", "role": {"name": "student"}},
        )
        assert result == "demo"


# ── /upload/folder whitelist ──────────────────────────────

class TestUploadFolderWhitelist:
    @pytest.mark.asyncio
    async def test_outside_whitelist_returns_403(self, monkeypatch, tmp_path):
        from raganything.routers import knowledge

        monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", AsyncMock())
        monkeypatch.setenv("FOLDER_UPLOAD_ROOTS", str(tmp_path))
        outside = tmp_path / ".." / "outside-folder"
        outside.mkdir(exist_ok=True)

        with pytest.raises(HTTPException) as exc:
            await knowledge.upload_folder(
                folder_path=str(outside), kb="demo",
                current_user={"id": 9, "username": "s"},
                _perm=None,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_inside_whitelist_proceeds_to_work(self, monkeypatch, tmp_path):
        from raganything.routers import knowledge

        monkeypatch.setattr(knowledge, "_ensure_vision_index_mutable", AsyncMock())
        monkeypatch.setenv("FOLDER_UPLOAD_ROOTS", str(tmp_path))
        inside = tmp_path / "sub"
        inside.mkdir(exist_ok=True)

        async def boom(*args, **kwargs):
            raise HTTPException(500, "reached downstream")

        monkeypatch.setattr(knowledge, "_create_upload_settings_snapshot", boom)
        with pytest.raises(HTTPException) as exc:
            await knowledge.upload_folder(
                folder_path=str(inside), kb="demo",
                current_user={"id": 9, "username": "s"},
                _perm=None,
            )
        assert exc.value.status_code == 500

    def test_roots_override_and_defaults(self, monkeypatch):
        from raganything.routers import knowledge

        monkeypatch.setenv("FOLDER_UPLOAD_ROOTS", str(tmp_path := Path(".").resolve() / "x"))
        roots = knowledge._folder_upload_roots()
        assert roots == [str(tmp_path.resolve())]

        monkeypatch.delenv("FOLDER_UPLOAD_ROOTS", raising=False)
        roots = knowledge._folder_upload_roots()
        assert len(roots) == 2
        assert any(os.path.basename(r) == "uploads" for r in roots)
        assert any(os.path.basename(r) == "rag_storage" for r in roots)

    def test_is_path_within(self, tmp_path):
        from raganything.routers import knowledge

        root = tmp_path / "root"
        root.mkdir(exist_ok=True)
        (root / "sub").mkdir(exist_ok=True)
        assert knowledge._is_path_within(str(root / "sub"), str(root))
        assert knowledge._is_path_within(str(root), str(root))
        assert not knowledge._is_path_within(str(tmp_path / "root2"), str(root))
        assert not knowledge._is_path_within(str(tmp_path.parent), str(root))


# ── cleanup_kb_resources ordering ─────────────────────────

class TestCleanupKbResourcesOrdering:
    @pytest.mark.asyncio
    async def test_collects_file_paths_before_begin_deletion(self, monkeypatch, tmp_path):
        import raganything.services.kb_service as kb_service

        calls = []

        async def fake_load_doc_status(name):
            calls.append("collect_doc_status")
            return {"doc1": {"file_path": "uploads/report.pdf"}}

        async def fake_load_text_chunks(name):
            calls.append("collect_text_chunks")
            return {}

        def fake_begin_deletion(name):
            calls.append("begin_deletion")
            return []

        async def fake_wait_leases(name, timeout):
            return True

        async def fake_cancel_tags(name):
            return None

        async def fake_load_meta():
            return {}

        async def fake_save_meta(meta):
            return None

        monkeypatch.setattr(kb_service, "_load_doc_status_json", fake_load_doc_status)
        monkeypatch.setattr(kb_service, "_load_text_chunks_json", fake_load_text_chunks)
        monkeypatch.setattr(kb_service.kb_instances, "begin_deletion", fake_begin_deletion)
        monkeypatch.setattr(kb_service.kb_instances, "wait_for_no_query_leases", fake_wait_leases)
        monkeypatch.setattr(kb_service, "_cancel_deferred_auto_tag_tasks", fake_cancel_tags)
        monkeypatch.setattr(kb_service, "load_kb_meta", fake_load_meta)
        monkeypatch.setattr(kb_service, "save_kb_meta", fake_save_meta)
        monkeypatch.setattr(kb_service, "kb_dir", lambda name: str(tmp_path / name))

        await kb_service.cleanup_kb_resources("demo")

        assert calls.index("collect_doc_status") < calls.index("begin_deletion")
        assert calls.index("collect_text_chunks") < calls.index("begin_deletion")


# ── agent conversation guard downgrade ─────────────────────

class TestAgentConversationGuards:
    def test_conversation_routes_use_agent_read(self):
        from raganything.routers import agent

        assert "require_agent_read" in _route_dependency_names(
            agent.router, "/agents/{agent_id}/conversations", "POST"
        )
        assert "require_agent_read" in _route_dependency_names(
            agent.router, "/agents/{agent_id}/conversations/{thread_id}", "PUT"
        )
        assert "require_agent_read" in _route_dependency_names(
            agent.router, "/agents/{agent_id}/conversations/{thread_id}", "DELETE"
        )
        assert "require_agent_write" in _route_dependency_names(
            agent.router,
            "/agents/{agent_id}/conversations/{thread_id}/messages/{message_id}",
            "PUT",
        )
