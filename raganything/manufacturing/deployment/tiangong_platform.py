"""
天工讲堂平台集成适配器。
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class TiangongPlatformAdapter:
    """天工讲堂平台对接适配器。"""

    def __init__(self, api_base_url: str = "",
                 oauth_config: Optional[dict] = None):
        """
        Args:
            api_base_url: 平台 API 基地址
            oauth_config: OAuth2 配置 {"client_id", "client_secret", "token_url"}
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.oauth_config = oauth_config or {}

    def authenticate(self, platform_token: str) -> Optional[dict]:
        """使用平台 Token 验证并获取用户信息。"""
        # 验证平台 SSO Token
        try:
            # 调用平台用户信息端点
            user_info = self._call_platform_api(
                "GET", "/user/info",
                headers={"Authorization": f"Bearer {platform_token}"},
            )
            return {
                "user_id": user_info.get("user_id", ""),
                "name": user_info.get("name", ""),
                "institution_id": user_info.get("institution_id", ""),
                "role": user_info.get("role", "student"),
            }
        except Exception as e:
            logger.error(f"平台认证失败: {e}")
            return None

    def push_dashboard_data(self, data: dict) -> bool:
        """推送数据看板数据到平台。"""
        try:
            self._call_platform_api(
                "POST", "/dashboard/update",
                json_data=data,
            )
            return True
        except Exception as e:
            logger.error(f"看板数据推送失败: {e}")
            return False

    def sync_user_behavior(self, events: list[dict]) -> bool:
        """同步用户行为事件到平台。

        Args:
            events: [{"user_id", "action", "timestamp", "metadata"}, ...]
        """
        try:
            self._call_platform_api(
                "POST", "/analytics/events",
                json_data={"events": events},
            )
            return True
        except Exception as e:
            logger.error(f"行为事件同步失败: {e}")
            return False

    def health_check(self) -> dict:
        """检查平台连接状态。"""
        try:
            start = time.time()
            resp = self._call_platform_api("GET", "/health")
            latency = (time.time() - start) * 1000
            return {
                "connected": True,
                "latency_ms": round(latency, 2),
                "platform_version": resp.get("version", "unknown"),
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def get_deployment_status(self) -> dict:
        """获取在天工讲堂平台的部署状态。"""
        return {
            "platform_url": self.api_base_url,
            "connection": self.health_check(),
            "oauth_configured": bool(self.oauth_config),
            "timestamp": time.time(),
        }

    def _call_platform_api(self, method: str, path: str,
                           json_data: Optional[dict] = None,
                           headers: Optional[dict] = None) -> dict:
        """调用平台 API。"""
        import urllib.request
        import urllib.error

        url = f"{self.api_base_url}{path}"
        req_headers = headers or {}
        req_headers.setdefault("Content-Type", "application/json")

        body = None
        if json_data:
            body = json.dumps(json_data, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"平台 API 错误 {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"平台连接失败: {e.reason}")
