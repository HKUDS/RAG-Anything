# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════════
Prompt Builder — 统一的 Prompt 构造管线
═══════════════════════════════════════════════════════════════════════════════════

【文件作用】
  统一的 Prompt 构造器，替代 agent.py 中三处手动 Prompt 拼接逻辑。
  支持优先级分层的上下文注入与 Token 预算管理。

【核心类】
  ContextLayer         — 上下文层数据类（name, content, priority, max_tokens, enabled）
  PromptBuilder        — Builder 模式 Prompt 构造器

【使用方式】
  builder = PromptBuilder()
  builder.system_instruction(sp)
  builder.add_context_layer(ContextLayer(...))
  builder.retrieval_context(ctx)
  builder.user_query(query, citation_instruction)
  final_prompt, system_prompt = builder.build()

【分层模型】
  Layer 0: System Instruction  — priority=0,  永不截断
  Layer 1: User Profile        — priority=10, max_tokens=500,  默认关闭
  Layer 2: Conversation Summary— priority=20, max_tokens=1000, 默认关闭
  Layer 3: Image Context       — priority=25, max_tokens=2000
  Layer 4: Recent History      — priority=30, max_tokens=2000
  Layer 5: Retrieval Context   — priority=50, 使用剩余预算
  Layer 6: User Query          — priority=100, 永不截断

【替换了什么】
  - agent.py 中 RAG 模式 (L990-1037) 的手动 Prompt 拼接
  - agent.py 中 ReAct 模式 (L560-579) 的手动 Prompt 拼接
  - agent.py 中 CoT 模式 (L612-627) 的手动 Prompt 拼接

【与其他文件的关系】
  被 raganything/routers/agent.py 调用（agent_query_stream 端点）
  参考 specs/context-layered-injection/spec.md

English:
  Unified prompt construction pipeline that replaces three independent
  prompt concatenation blocks in agent.py. Supports priority-layered
  context injection with per-layer token budgets.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rag_server.prompt_builder")

# ═══════════════════════════════════════════════════════════════
# Default layer token budgets
# ═══════════════════════════════════════════════════════════════

_DEFAULT_LAYER_CONFIG = {
    "user_profile":       {"priority": 10, "max_tokens": 500,  "enabled": False},
    "conversation_summary": {"priority": 20, "max_tokens": 1000, "enabled": True},
    "image_context":      {"priority": 25, "max_tokens": 2000, "enabled": True},
    "recent_history":     {"priority": 30, "max_tokens": 2000, "enabled": True},
    "retrieval_context":  {"priority": 50, "max_tokens": None, "enabled": True},
}


def _load_layer_config() -> dict:
    """Load layer configuration from environment, falling back to defaults.

    CONVERSATION_CONTEXT_LAYER_CONFIG expects a JSON string like:
      {"recent_history": {"max_tokens": 1500, "enabled": true}}
    """
    raw = os.getenv("CONVERSATION_CONTEXT_LAYER_CONFIG", "")
    if not raw:
        return _DEFAULT_LAYER_CONFIG

    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid CONVERSATION_CONTEXT_LAYER_CONFIG JSON, using defaults")
        return _DEFAULT_LAYER_CONFIG

    merged = {**_DEFAULT_LAYER_CONFIG}
    for key, val in overrides.items():
        if key in merged and isinstance(val, dict):
            merged[key] = {**merged[key], **val}
    return merged


# ═══════════════════════════════════════════════════════════════
# ContextLayer
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContextLayer:
    """A single layer of context to inject into the prompt.

    Attributes:
        name: Unique layer identifier (e.g. "recent_history", "image_context").
        content: The text content of this layer. Empty string → layer is treated as disabled.
        priority: Lower number = earlier in prompt (0 = system instruction, 100 = user query).
        max_tokens: Maximum token budget for this layer. None = no limit.
        enabled: Whether this layer should appear in the final prompt.
        label: Section heading in the prompt (e.g. "## 对话历史").
    """
    name: str
    content: str = ""
    priority: int = 50
    max_tokens: Optional[int] = None
    enabled: bool = True
    label: str = ""

    def effective_content(self) -> str:
        """Return content trimmed to max_tokens budget, or empty if disabled."""
        if not self.enabled or not self.content:
            return ""
        if self.max_tokens is not None and self.max_tokens > 0:
            return _truncate_by_tokens(self.content, self.max_tokens)
        return self.content

    def token_estimate(self) -> int:
        """Rough token estimate: ~2 chars per token for CJK, ~4 for Latin."""
        if not self.content:
            return 0
        return max(1, len(self.content) // 2)


# ═══════════════════════════════════════════════════════════════
# PromptBuilder
# ═══════════════════════════════════════════════════════════════

class PromptBuilder:
    """Unified prompt constructor with priority-layered context injection.

    Usage:
        builder = PromptBuilder(max_total_tokens=8192)
        builder.system_instruction("You are a helpful assistant.")
        builder.add_context_layer(ContextLayer(
            name="recent_history", content=history_text,
            priority=30, max_tokens=2000, label="## 对话历史"
        ))
        builder.retrieval_context(retrieval_text)
        builder.user_query(query, citation_instruction)
        final_prompt, system_prompt = builder.build()
    """

    def __init__(self, max_total_tokens: int = 8192):
        self._max_total_tokens = max_total_tokens
        self._system_instruction: str = ""
        self._layers: list[ContextLayer] = []
        self._retrieval_context: str = ""
        self._user_query: str = ""
        self._citation_instruction: str = ""
        self._degraded_hint: str = ""

    # ── setters ──────────────────────────────────────────────

    def system_instruction(self, text: str) -> "PromptBuilder":
        """Set the system prompt (Layer 0, never truncated)."""
        self._system_instruction = text
        return self

    def add_context_layer(self, layer: ContextLayer) -> "PromptBuilder":
        """Add a context layer, sorted by priority at build time."""
        self._layers.append(layer)
        return self

    def retrieval_context(self, text: str) -> "PromptBuilder":
        """Set the retrieval/RAG context (Layer 5, uses remaining token budget)."""
        self._retrieval_context = text
        return self

    def user_query(self, query: str, citation_instruction: str = "") -> "PromptBuilder":
        """Set the user query and optional citation instruction (Layer 6, never truncated)."""
        self._user_query = query
        self._citation_instruction = citation_instruction
        return self

    def degraded_hint(self, hint: str) -> "PromptBuilder":
        """Set a hint shown when retrieval context is degraded."""
        self._degraded_hint = hint
        return self

    # ── build ────────────────────────────────────────────────

    def build(self) -> tuple[str, str]:
        """Assemble the final prompt and return (final_prompt, system_prompt).

        Layers are assembled in priority order (ascending).
        Token budget is deducted from lowest-priority non-mandatory layers first.
        System instruction and user query are never truncated.
        """
        # Separate mandatory layers (0 and 100) from trimmable ones
        mandatory_parts: list[tuple[int, str]] = []
        trimmable_parts: list[tuple[int, str, str]] = []  # (priority, label, content)

        # System instruction is passed separately, not in prompt body
        # But we record it for the total token budget calculation

        # Sort layers by priority
        sorted_layers = sorted(self._layers, key=lambda l: l.priority)

        for layer in sorted_layers:
            content = layer.effective_content()
            if not content:
                continue
            label = layer.label or f"## {layer.name}\n"
            formatted = f"{label}{content}\n\n"

            if layer.priority >= 100:
                # Mandatory — never trim
                mandatory_parts.append((layer.priority, formatted))
            else:
                trimmable_parts.append((layer.priority, label, content))

        # Add retrieval context (priority 50)
        if self._retrieval_context:
            label = "## 检索内容\n"
            trimmable_parts.append((50, label, self._retrieval_context))

        # Add user query at the end (mandatory, priority 100)
        user_part = f"## 问题\n{self._user_query}\n\n"
        if self._citation_instruction:
            user_part += f"{self._citation_instruction}"
        if self._degraded_hint:
            user_part += f"{self._degraded_hint}"
        mandatory_parts.append((100, user_part))

        # Calculate total token usage
        mandatory_tokens = sum(_token_est(p[1]) for p in mandatory_parts)
        trimmable_tokens = sum(_token_est(label + content) for (_, label, content) in trimmable_parts)

        # If we exceed budget, trim from lowest-priority (highest number) trimmable layers first
        budget_for_trimmable = self._max_total_tokens - mandatory_tokens
        if budget_for_trimmable < 0:
            budget_for_trimmable = max(0, self._max_total_tokens // 2)

        # Sort trimmable descending by priority (trim lowest-priority first)
        trimmable_parts.sort(key=lambda x: -x[0])

        used = 0
        kept: list[str] = []

        for priority, label, content in trimmable_parts:
            full = f"{label}{content}\n\n"
            est = _token_est(full)
            if used + est <= budget_for_trimmable:
                kept.append((priority, full))
                used += est
            else:
                # Try to fit truncated version
                remaining = budget_for_trimmable - used
                if remaining > 50:
                    truncated_content = _truncate_by_tokens(content, max(50, remaining - _token_est(label)))
                    if truncated_content:
                        kept.append((priority, f"{label}{truncated_content}\n\n"))
                        break
                break

        # Re-sort kept trimmable parts by priority ascending for final output
        kept.sort(key=lambda x: x[0])

        # Assemble
        all_parts = mandatory_parts + kept
        all_parts.sort(key=lambda x: x[0])

        # Filter: priority 0 (system instruction) goes to system_prompt, not body
        body_parts = []
        sys_parts = []

        for priority, text in all_parts:
            if priority == 0:
                sys_parts.append(text)
            else:
                body_parts.append(text)

        final_prompt = "".join(body_parts)
        system_prompt_parts = []
        if self._system_instruction:
            system_prompt_parts.append(self._system_instruction)
        system_prompt_parts.extend(sys_parts)
        final_system_prompt = "\n".join(system_prompt_parts) if system_prompt_parts else self._system_instruction

        return final_prompt, final_system_prompt

    # ── convenience methods ──────────────────────────────────

    def add_user_profile(self, profile_text: str) -> "PromptBuilder":
        """Add user profile layer (priority=10)."""
        self.add_context_layer(ContextLayer(
            name="user_profile",
            content=profile_text,
            priority=10,
            max_tokens=int(os.getenv("CONVERSATION_SUMMARY_MAX_TOKENS", "500")),
            enabled=bool(profile_text),
            label="## 用户画像\n",
        ))
        return self

    def add_summary(self, summary_text: str) -> "PromptBuilder":
        """Add conversation summary layer (priority=20)."""
        enabled = (
            os.getenv("CONVERSATION_SUMMARY_ENABLED", "true").lower() == "true"
            and bool(summary_text)
        )
        self.add_context_layer(ContextLayer(
            name="conversation_summary",
            content=summary_text,
            priority=20,
            max_tokens=int(os.getenv("CONVERSATION_SUMMARY_MAX_TOKENS", "1000")),
            enabled=enabled,
            label="## 对话摘要\n",
        ))
        return self

    def add_recent_history(self, history_text: str) -> "PromptBuilder":
        """Add recent conversation history layer (priority=30)."""
        max_tokens = int(os.getenv("CONVERSATION_MAX_TOKENS", "2000"))
        self.add_context_layer(ContextLayer(
            name="recent_history",
            content=history_text,
            priority=30,
            max_tokens=max_tokens,
            enabled=bool(history_text),
            label="## 对话历史\n",
        ))
        return self

    def add_image_context(self, image_text: str) -> "PromptBuilder":
        """Add image/video context layer (priority=25)."""
        self.add_context_layer(ContextLayer(
            name="image_context",
            content=image_text,
            priority=25,
            max_tokens=2000,
            enabled=bool(image_text),
            label="",
        ))
        return self


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _token_est(text: str) -> int:
    """Rough token estimate: ~2 chars per token."""
    if not text:
        return 0
    return max(1, len(text) // 2)


def _truncate_by_tokens(text: str, max_tokens: int) -> str:
    """Truncate text from the start to fit within max_tokens."""
    if not text or max_tokens <= 0:
        return ""
    max_chars = max_tokens * 2
    if len(text) <= max_chars:
        return text
    # Keep the last max_chars characters — preserve recent/end content
    return "…(截断)…\n" + text[-max_chars + 10:]
