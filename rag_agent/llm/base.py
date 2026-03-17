"""LLM provider base abstractions for ppt-RAG agent."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    """Normalized tool call request returned by an LLM."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai_tool_call(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible tool call payload."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class LLMResponse:
    """Normalized response object returned by provider implementations."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract provider interface used by agent loop."""

    _CHAT_RETRY_DELAYS = (1, 2, 4)
    _TRANSIENT_ERROR_MARKERS = (
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "timed out",
        "connection",
        "server error",
        "temporarily unavailable",
    )

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.default_model = default_model

    def get_default_model(self) -> str:
        if not self.default_model:
            raise ValueError("default_model is not set")
        return self.default_model

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Run one chat completion call and return a normalized response."""

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        text = (content or "").lower()
        return any(marker in text for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Call chat() with minimal retry for transient provider failures."""
        for delay in self._CHAT_RETRY_DELAYS:
            try:
                response = await self.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tool_choice=tool_choice,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")

            if response.finish_reason != "error":
                return response
            if not self._is_transient_error(response.content):
                return response
            await asyncio.sleep(delay)

        return await self.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tool_choice=tool_choice,
        )
