"""
测试文档下载端点的 ?token 双模式认证
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


class TestDownloadTokenAuth:
    """验证 download_document 端点支持 Authorization header + ?token 双模式认证"""

    @pytest.mark.asyncio
    async def test_token_query_param_fallback(self):
        """当没有 Authorization header 但提供了 ?token=xxx 时，应通过 token 认证"""
        from raganything.routers.knowledge import download_document

        mock_user = {"id": 1, "username": "testuser", "is_admin": True}
        test_file = Path.cwd() / "tests" / "test_document_download.py"

        with (
            patch(
                "raganything.routers.knowledge.get_current_user_from_token",
                AsyncMock(return_value=mock_user),
            ),
            patch(
                "raganything.routers.knowledge._verify_kb_access_for_download",
                AsyncMock(return_value=None),
            ),
            patch(
                "raganything.routers.knowledge._resolve_download_file",
                AsyncMock(return_value=(test_file, "test.pdf")),
            ),
            patch("mimetypes.guess_type", return_value=("application/pdf", None)),
            patch("raganything.routers.knowledge.lightrag_logger", MagicMock()),
        ):
            result = await download_document(
                doc_id="test_doc_001",
                kb="test_kb",
                token="valid_token_abc123",  # ← ?token=xxx 参数
                current_user=None,  # ← 无 Authorization header
            )

        from starlette.responses import FileResponse
        assert isinstance(result, FileResponse)
        assert result.media_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self):
        """没有 Authorization header 也没有 ?token 时，应返回 401"""
        from raganything.routers.knowledge import download_document
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await download_document(
                doc_id="test_doc_001",
                kb="test_kb",
                token=None,  # ← 无 token
                current_user=None,  # ← 无 Authorization header
            )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_header_still_works(self):
        """Authorization header 认证向后兼容 — 不应该断裂"""
        from raganything.routers.knowledge import download_document

        mock_user = {"id": 2, "username": "editor", "is_admin": True}
        test_file = Path.cwd() / "tests" / "test_document_download.py"

        with (
            patch(
                "raganything.routers.knowledge._verify_kb_access_for_download",
                AsyncMock(return_value=None),
            ),
            patch(
                "raganything.routers.knowledge._resolve_download_file",
                AsyncMock(return_value=(test_file, "video.mp4")),
            ),
            patch("mimetypes.guess_type", return_value=("video/mp4", None)),
            patch("raganything.routers.knowledge.lightrag_logger", MagicMock()),
        ):
            result = await download_document(
                doc_id="test_doc_002",
                kb="test_kb",
                token=None,
                current_user=mock_user,  # ← 通过 Authorization header 认证
            )

        from starlette.responses import FileResponse
        assert isinstance(result, FileResponse)
        assert result.media_type == "video/mp4"

    @pytest.mark.asyncio
    async def test_download_accepts_file_under_resolved_project_root(self, tmp_path):
        """A junction launch path must not reject an in-project upload."""
        from raganything.routers import knowledge

        project_root = tmp_path / "project-root"
        upload_file = project_root / "uploads" / "document.pdf"
        upload_file.parent.mkdir(parents=True)
        upload_file.write_bytes(b"pdf")
        cwd_alias = MagicMock()
        cwd_alias.resolve.return_value = project_root

        with (
            patch.object(knowledge.Path, "cwd", return_value=cwd_alias),
            patch(
                "raganything.routers.knowledge._verify_kb_access_for_download",
                AsyncMock(return_value=None),
            ),
            patch(
                "raganything.routers.knowledge._resolve_download_file",
                AsyncMock(return_value=(upload_file, "document.pdf")),
            ),
            patch("mimetypes.guess_type", return_value=("application/pdf", None)),
            patch("raganything.routers.knowledge.lightrag_logger", MagicMock()),
        ):
            result = await knowledge.download_document(
                doc_id="test_doc_junction",
                kb="test_kb",
                current_user={"id": 1, "is_admin": True},
            )

        from starlette.responses import FileResponse
        assert isinstance(result, FileResponse)
        assert result.path == str(upload_file)

    @pytest.mark.asyncio
    async def test_download_rejects_file_outside_resolved_project_root(self, tmp_path):
        """Canonicalization must retain the boundary against external files."""
        from fastapi import HTTPException
        from raganything.routers import knowledge

        project_root = tmp_path / "project-root"
        project_root.mkdir()
        external_file = tmp_path / "external.pdf"
        external_file.write_bytes(b"pdf")
        cwd_alias = MagicMock()
        cwd_alias.resolve.return_value = project_root

        with (
            patch.object(knowledge.Path, "cwd", return_value=cwd_alias),
            patch(
                "raganything.routers.knowledge._verify_kb_access_for_download",
                AsyncMock(return_value=None),
            ),
            patch(
                "raganything.routers.knowledge._resolve_download_file",
                AsyncMock(return_value=(external_file, "external.pdf")),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await knowledge.download_document(
                    doc_id="test_doc_external",
                    kb="test_kb",
                    current_user={"id": 1, "is_admin": True},
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_file_not_found_returns_404(self):
        """文档没有原始文件时，应返回 404"""
        from raganything.routers.knowledge import download_document
        from fastapi import HTTPException

        mock_user = {"id": 1, "username": "testuser", "is_admin": True}

        with (
            patch(
                "raganything.routers.knowledge._verify_kb_access_for_download",
                AsyncMock(return_value=None),
            ),
            patch(
                "raganything.routers.knowledge._resolve_download_file",
                AsyncMock(return_value=None),  # ← 文件未找到
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await download_document(
                    doc_id="pasted_content_doc",
                    kb="test_kb",
                    token=None,
                    current_user=mock_user,
                )


@pytest.mark.asyncio
async def test_download_resolution_uses_clean_name_but_keeps_staged_file(monkeypatch, tmp_path):
    from raganything.routers import knowledge

    prefix = "0fb7375fdfa54875b2ed60d479aed21a"
    staged_file = tmp_path / f"{prefix}_battery.mp4"
    staged_file.write_bytes(b"video")

    class Connection:
        async def fetchrow(self, *_args):
            return {"file_path": staged_file.name, "status": "completed"}

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr("raganything.services.pg_state_repo.get_pg_pool", lambda: Pool())
    monkeypatch.setattr(knowledge, "_find_upload_file", lambda _path: staged_file)

    resolved = await knowledge._resolve_download_file("test-kb", "doc-1")

    assert resolved == (staged_file.resolve(), "battery.mp4")

        assert exc_info.value.status_code == 404
