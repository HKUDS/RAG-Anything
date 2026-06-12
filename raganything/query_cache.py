"""
查询结果缓存 — TTL + LRU 淘汰。

用法:
    from raganything.utils.query_cache import QueryCache

    cache = QueryCache(ttl=60, max_size=500)
    result = cache.get("query text")
    if result is None:
        result = do_expensive_query()
        cache.set("query text", result)
"""

import hashlib
import logging
import os
import time
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)


class QueryCache:
    """带 TTL 和 LRU 淘汰的查询缓存。"""

    def __init__(self, ttl: float = 60, max_size: int = 500):
        """
        Args:
            ttl: 缓存有效期（秒）
            max_size: 最大缓存条目数
        """
        self.ttl = ttl
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()

    def _hash(self, query: str) -> str:
        return hashlib.md5(query.strip().lower().encode()).hexdigest()

    def get(self, query: str) -> Optional[dict]:
        """获取缓存结果。过期或不存在返回 None。"""
        key = self._hash(query)
        if key not in self._store:
            return None

        timestamp, result = self._store[key]
        if time.time() - timestamp > self.ttl:
            del self._store[key]
            return None

        # 命中后移到末尾（LRU）
        self._store.move_to_end(key)
        return result

    def set(self, query: str, result: dict) -> None:
        """设置缓存。"""
        key = self._hash(query)
        self._store[key] = (time.time(), result)
        self._store.move_to_end(key)

        # 淘汰最旧
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def invalidate(self, query: str = "") -> None:
        """失效缓存。query 为空则清空全部。"""
        if query:
            key = self._hash(query)
            self._store.pop(key, None)
        else:
            self._store.clear()

    def get_stats(self) -> dict:
        """获取缓存统计。"""
        now = time.time()
        total = len(self._store)
        expired = sum(1 for ts, _ in self._store.values() if now - ts > self.ttl)
        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "max_size": self.max_size,
            "ttl_seconds": self.ttl,
        }


# 全局缓存实例
_query_cache: Optional[QueryCache] = None


def get_query_cache() -> QueryCache:
    """获取全局查询缓存实例。"""
    global _query_cache
    if _query_cache is None:
        ttl = int(os.getenv("QUERY_CACHE_TTL", "60"))
        _query_cache = QueryCache(ttl=ttl)
    return _query_cache
