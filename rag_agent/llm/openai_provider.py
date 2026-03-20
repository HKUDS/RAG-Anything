"""Minimal OpenAI provider for rag_agent."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from .base import LLMProvider, LLMResponse, ToolCallRequest


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider with normalized response output."""

    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
        default_model: str = "gpt-4o-mini",
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, default_model=default_model)
        self._client = AsyncOpenAI(api_key=api_key, base_url=api_base)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model or self.get_default_model(),
            "messages": messages,
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        try:
            response = await self._client.chat.completions.create(**payload)
            return self._parse_response(response)
        except Exception as exc:
            return LLMResponse(content=f"Error calling OpenAI: {exc}", finish_reason="error")

    def _parse_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCallRequest] = []
        for tool_call in message.tool_calls or []:
            arguments = self._parse_arguments(tool_call.function.arguments)
            tool_calls.append(
                ToolCallRequest(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=arguments,
                )
            )

        usage = response.usage
        usage_data = {}
        if usage:
            usage_data = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage_data,
        )

    @staticmethod
    def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str):
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {"_raw": raw_arguments}
        return parsed if isinstance(parsed, dict) else {"_raw": raw_arguments}
