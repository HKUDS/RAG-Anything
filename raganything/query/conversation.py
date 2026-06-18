"""
Query functionality for RAGAnything

Contains all query-related methods for both text and multimodal queries
"""

import asyncio
import json
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import jieba
from datetime import datetime, timezone
from typing import Dict, List, Any
from pathlib import Path
from lightrag import QueryParam
from lightrag.utils import always_get_an_event_loop
from raganything.prompt import PROMPTS, INLINE_QUOTE_INSTRUCTION, ANSWER_FORMAT_INSTRUCTION

# Hint appended to LLM prompt when text chunk resolution fails (chunks=0)
DEGRADED_CONTEXT_HINT = (
    "\n\n⚠️ 注意：本次检索未能获取到关联的文档文本内容（仅获取到实体名称和关系路径），"
    "以下回答可能不够详细。请优先引用实体关系信息，并明确告知用户哪些信息来源自实体名而非原文。"
    "如果信息不足以回答问题，请如实说明。"
)
from raganything.citation_parser import has_citations
from raganything.utils import (
    get_processor_for_type,
    encode_image_to_base64,
    validate_image_file,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# ConversationManager — 多轮对话上下文记忆
# ═══════════════════════════════════════════════════════════

@dataclass
class ThreadSummary:
    """会话摘要（列表展示用）"""
    id: str
    title: str
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ConversationContext:
    """注入 LLM prompt 的对话上下文"""
    history_text: str = ""
    messages: list[dict] = field(default_factory=list)
    round_count: int = 0
    estimated_tokens: int = 0


class ConversationManager:
    """多轮对话会话管理器。

    按 thread_id 分组存储对话历史，支持持久化到 JSON 文件。
    每个用户独立隔离，提供上下文提取、token 截断等功能。
    """

    def __init__(self, storage_path: str = "./conversations.json",
                 max_rounds: int = 3, max_tokens: int = 2000,
                 max_per_user: int = 50):
        self.storage_path = Path(storage_path)
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.max_per_user = max_per_user
        self._lock = asyncio.Lock()
        self._threads: dict[str, dict] = {}

    # ── 持久化 ─────────────────────────────────────────

    async def _load(self) -> None:
        """从 JSON 文件加载会话数据。"""
        async with self._lock:
            try:
                if self.storage_path.exists():
                    data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                    self._threads = data.get("threads", {})
                    logger.info(
                        f"ConversationManager loaded {len(self._threads)} threads "
                        f"from {self.storage_path}"
                    )
                else:
                    self._threads = {}
                    await self._save_nolock()
            except Exception as e:
                logger.warning(f"Failed to load conversations: {e}")
                self._threads = {}

    async def _save_nolock(self) -> None:
        """持久化（调用方需持有锁）。"""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"threads": self._threads}
            self.storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save conversations: {e}")

    # ── 会话 CRUD ──────────────────────────────────────

    async def get_or_create_thread(self, user_id: str,
                                   thread_id: str = "",
                                   title: str = "新对话") -> dict:
        """获取或创建会话。

        Args:
            user_id: 用户 ID（用于隔离）
            thread_id: 空则创建新会话
            title: 创建新会话时的标题（自动截取 50 字符）

        Returns:
            thread dict: {id, user_id, title, created_at, updated_at, messages}
        """
        # 查找已有会话
        if thread_id and thread_id in self._threads:
            thread = self._threads[thread_id]
            if thread.get("user_id") == user_id:
                return thread
            # thread_id 存在但不属于该用户 → 返回空壳让调用方知道无效
            return {}

        # 检查用户会话数上限
        user_threads = [
            t for t in self._threads.values()
            if t.get("user_id") == user_id
        ]
        if len(user_threads) >= self.max_per_user:
            logger.warning(
                f"User {user_id} has reached max threads ({self.max_per_user})"
            )
            return {"error": f"已达到最大会话数限制（{self.max_per_user}）"}

        # 创建新会话
        new_id = thread_id or f"th_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        title = title[:50] if title else "新对话"
        thread = {
            "id": new_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        async with self._lock:
            self._threads[new_id] = thread
            await self._save_nolock()
        logger.info(f"Created thread {new_id} for user {user_id}")
        return thread

    async def add_message(self, thread_id: str, role: str,
                          content: str) -> None:
        """追加一条消息到会话。

        Args:
            thread_id: 会话 ID
            role: "user" | "assistant"
            content: 消息内容（max 10000 字符）
        """
        if thread_id not in self._threads:
            logger.warning(f"Thread {thread_id} not found for add_message")
            return
        content = content[:10000] if len(content) > 10000 else content
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with self._lock:
            self._threads[thread_id]["messages"].append(msg)
            self._threads[thread_id]["updated_at"] = msg["timestamp"]
            await self._save_nolock()

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数（字符数 / 2，中文友好）。"""
        return max(1, len(text) // 2)

    async def get_context(self, thread_id: str,
                          current_query: str = "") -> ConversationContext:
        """提取会话的对话上下文（最近 max_rounds 轮，不超过 max_tokens）。

        Returns:
            ConversationContext: 包含格式化历史和元数据
        """
        if thread_id not in self._threads:
            return ConversationContext()

        messages = self._threads[thread_id].get("messages", [])
        if not messages:
            return ConversationContext()

        # 取最近 N 轮（一轮 = user + assistant）
        max_msgs = self.max_rounds * 2
        recent = messages[-max_msgs:]

        # 按 token 预算从旧到新截断
        lines = []
        token_count = 0
        selected = []
        for msg in reversed(recent):
            line = f"{'用户' if msg['role'] == 'user' else '助手'}: {msg['content']}"
            est = self._estimate_tokens(line)
            if token_count + est > self.max_tokens:
                break
            lines.insert(0, line)
            selected.insert(0, msg)
            token_count += est

        history_text = "\n".join(lines)
        return ConversationContext(
            history_text=history_text,
            messages=selected,
            round_count=len(selected) // 2,
            estimated_tokens=token_count,
        )

    async def get_context_for_rewrite(self, thread_id: str) -> list[dict]:
        """获取用于查询改写的历史（最近 3 轮，仅 user 消息）。"""
        if thread_id not in self._threads:
            return []
        messages = self._threads[thread_id].get("messages", [])
        if not messages:
            return []
        recent = messages[-(self.max_rounds * 2):]
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    async def list_threads(self, user_id: str) -> list[ThreadSummary]:
        """列出用户的所有会话摘要，按更新时间倒序。"""
        user_threads = []
        for tid, t in self._threads.items():
            if t.get("user_id") == user_id:
                user_threads.append(ThreadSummary(
                    id=tid,
                    title=t.get("title", "新对话"),
                    message_count=len(t.get("messages", [])),
                    created_at=t.get("created_at", ""),
                    updated_at=t.get("updated_at", ""),
                ))
        user_threads.sort(key=lambda x: x.updated_at, reverse=True)
        return user_threads

    async def delete_thread(self, thread_id: str) -> bool:
        """删除会话。"""
        async with self._lock:
            if thread_id in self._threads:
                del self._threads[thread_id]
                await self._save_nolock()
                logger.info(f"Deleted thread {thread_id}")
                return True
        return False

    async def thread_exists(self, thread_id: str, user_id: str = "") -> bool:
        """检查会话是否存在且（可选）属于指定用户。"""
        if thread_id not in self._threads:
            return False
        if user_id and self._threads[thread_id].get("user_id") != user_id:
            return False
        return True

    def get_stats(self) -> dict:
        """获取统计信息。"""
        total_msgs = sum(
            len(t.get("messages", [])) for t in self._threads.values()
        )
        return {
            "total_threads": len(self._threads),
            "total_messages": total_msgs,
            "storage_path": str(self.storage_path),
        }

