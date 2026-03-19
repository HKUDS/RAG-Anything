"""LLM abstractions for rag_agent."""

from .base import LLMProvider, LLMResponse, ToolCallRequest

try:
	from .openai_provider import OpenAIProvider
except ModuleNotFoundError:  # pragma: no cover - optional dependency at import time
	OpenAIProvider = None  # type: ignore[assignment]

__all__ = ["LLMProvider", "LLMResponse", "ToolCallRequest", "OpenAIProvider"]
