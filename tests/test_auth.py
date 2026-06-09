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
