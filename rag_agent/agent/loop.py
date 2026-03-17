"""Minimal agent loop for RAG tool-calling workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rag_agent.llm.base import LLMProvider

from .context import ContextBuilder
from .tools import GenerateTool, RetrieveTool, ToolRegistry


@dataclass
class AgentLoopResult:
    """Result object returned by one agent loop run."""

    final_answer: str
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    """Minimal loop that lets the LLM decide when to call RAG tools."""

    def __init__(
        self,
        provider: LLMProvider,
        model: str | None = None,
        max_iterations: int = 8,
        max_tool_calls: int = 8,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        context: ContextBuilder | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.context = context or ContextBuilder()
        self.tools = tools or ToolRegistry()
        if tools is None:
            self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default RAG tools for MVP."""
        self.tools.register(RetrieveTool())
        self.tools.register(GenerateTool())

    async def run_once(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> AgentLoopResult:
        """Process one user message with iterative tool calling."""
        messages = self.context.build_messages(
            history=history or [],
            current_message=user_message,
            channel=channel,
            chat_id=chat_id,
        )

        tools_used: list[str] = []
        tool_calls_count = 0

        for iteration in range(1, self.max_iterations + 1):
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            if response.finish_reason == "error":
                return AgentLoopResult(
                    final_answer=response.content or "LLM returned an error.",
                    tools_used=tools_used,
                    iterations=iteration,
                    messages=messages,
                )

            if response.has_tool_calls:
                tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
                messages = self.context.add_assistant_message(messages, response.content, tool_call_dicts)

                for tool_call in response.tool_calls:
                    tool_calls_count += 1
                    tools_used.append(tool_call.name)

                    if tool_calls_count > self.max_tool_calls:
                        return AgentLoopResult(
                            final_answer=(
                                "Reached max tool call budget without a final answer. "
                                "Please refine the question or increase the budget."
                            ),
                            tools_used=tools_used,
                            iterations=iteration,
                            messages=messages,
                        )

                    tool_result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        result=tool_result,
                    )
                continue

            final_answer = response.content or ""
            messages = self.context.add_assistant_message(messages, final_answer)
            return AgentLoopResult(
                final_answer=final_answer,
                tools_used=tools_used,
                iterations=iteration,
                messages=messages,
            )

        return AgentLoopResult(
            final_answer=(
                f"Reached max iterations ({self.max_iterations}) without producing a final answer."
            ),
            tools_used=tools_used,
            iterations=self.max_iterations,
            messages=messages,
        )
