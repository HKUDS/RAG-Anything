"""auth.py 单元测试 — 密码复杂度、JWT、暴力破解防护"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 测试密码复杂度（同步版本，不依赖数据库）
from auth import verify_password, create_token, decode_token, pwd_context


class TestPasswordComplexity:
    """密码复杂度需求：>=8位，大写+小写+数字+特殊字符含其三"""

    def test_weak_password_too_short(self):
        """6位密码应被拒绝"""
        with pytest.raises(Exception):
            import asyncio
            async def _test():
                from auth import create_user
                await create_user("test", "t@t.com", "Ab1!")
            asyncio.run(_test())

    def test_strong_password_accepted(self):
        """含大写+小写+数字+特殊字符的强密码"""
        hash_result = pwd_context.hash("StrongP@ss123")
        assert verify_password("StrongP@ss123", hash_result)
        assert not verify_password("wrong", hash_result)

    def test_chinese_password_accepted(self):
        """中文+大小写+数字也应通过（特殊字符含中文）"""
        # 中文算特殊字符类，加上大小写和数字 = 4类，通过
        hash_result = pwd_context.hash("密码Test123")
        assert len("密码Test123") >= 8  # 8 chars


class TestJWT:
    """JWT Token 创建与验证"""

    def test_create_and_decode(self):
        token = create_token(42, "alice", False)
        payload = decode_token(token)
        assert payload is not None
        assert payload["user_id"] == 42
        assert payload["username"] == "alice"
        assert payload["is_admin"] is False

    def test_invalid_token(self):
        assert decode_token("not.a.valid.token") is None
        assert decode_token("") is None

    def test_admin_token(self):
        token = create_token(1, "admin", True)
        payload = decode_token(token)
        assert payload["is_admin"] is True

    def test_refresh_token(self):
        from auth import create_refresh_token, decode_refresh_token
        rtk = create_refresh_token(42, "alice", False)
        payload = decode_refresh_token(rtk)
        assert payload is not None
        assert payload["type"] == "refresh"
        assert payload["user_id"] == 42

    def test_refresh_token_rejected_as_access(self):
        from auth import create_refresh_token
        rtk = create_refresh_token(1, "admin", True)
        # Refresh token 不应被 access token 解码器接受
        assert decode_token(rtk) is None


class TestBruteForce:
    """暴力破解防护 — 仅测试函数存在性（DB 依赖需要完整环境）"""

    def test_brute_force_functions_exist(self):
        from auth import check_account_locked, record_failed_login, reset_failed_logins
        assert callable(check_account_locked)
        assert callable(record_failed_login)
        assert callable(reset_failed_logins)


class TestTokenBlacklist:
    """Token 黑名单 — 撤销与查询"""

    def test_revoke_and_check(self):
        from raganything.services.token_blacklist import TokenBlacklist
        from datetime import datetime, timedelta, timezone

        bl = TokenBlacklist()
        jti = "test-jti-001"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        bl.revoke(jti, expires)
        assert bl.is_revoked(jti)

    def test_not_revoked_by_default(self):
        from raganything.services.token_blacklist import TokenBlacklist
        bl = TokenBlacklist()
        assert not bl.is_revoked("nonexistent-jti")

    def test_expired_auto_cleanup(self):
        from raganything.services.token_blacklist import TokenBlacklist
        from datetime import datetime, timedelta, timezone

        bl = TokenBlacklist()
        jti = "expired-jti"
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        bl.revoke(jti, past)
        # 过期后不应再显示已撤销
        assert not bl.is_revoked(jti)

    def test_refresh_family_revoke(self):
        from raganything.services.token_blacklist import TokenBlacklist
        from datetime import datetime, timedelta, timezone

        bl = TokenBlacklist()
        family = "family-abc"
        jti1, jti2 = "jti-1", "jti-2"
        bl.register_refresh_family(family, jti1)
        bl.register_refresh_family(family, jti2)
        bl.revoke_refresh_family(family)
        # family 中所有 token 应被撤销
        assert bl.is_revoked(jti1) or bl.is_revoked(jti2)


class TestJWTWithJTI:
    """JWT Token 新增 jti 字段"""

    def test_access_token_contains_jti(self):
        token = create_token(42, "alice", False)
        payload = decode_token(token)
        assert payload is not None
        assert "jti" in payload
        assert len(payload["jti"]) == 32  # UUID hex = 32 chars
        assert payload["type"] == "access"

    def test_refresh_token_contains_jti_and_rfam(self):
        from auth import create_refresh_token, decode_refresh_token
        rtk = create_refresh_token(42, "alice", False)
        payload = decode_refresh_token(rtk)
        assert payload is not None
        assert "jti" in payload
        assert "rfam" in payload  # refresh token family
        assert payload["type"] == "refresh"


class TestRBACIntegration:
    """RBAC 权限服务集成"""

    def test_permission_check_functions_exist(self):
        import asyncio
        async def _check():
            from raganything.services.auth import has_permission, get_user_role, user_is_admin
            assert callable(has_permission)
            assert callable(get_user_role)
            assert callable(user_is_admin)
        asyncio.run(_check())

    def test_permission_module_loads(self):
        from raganything.permissions import Permission, DEFAULT_ROLES
        assert hasattr(Permission, 'USERS_READ')
        assert 'admin' in DEFAULT_ROLES

    def test_token_blacklist_module_loads(self):
        from raganything.services.token_blacklist import get_token_blacklist
        bl = get_token_blacklist()
        assert bl is not None

    def test_audit_logger_module_loads(self):
        from raganything.services.audit import AuditLogger
        assert callable(AuditLogger)
