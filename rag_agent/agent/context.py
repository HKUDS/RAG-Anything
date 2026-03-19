"""Context builder for the minimal RAG agent."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any


class ContextBuilder:
    """Build system/user/tool messages for the RAG agent loop."""

    _RUNTIME_CONTEXT_TAG = "[Runtime Context - metadata only, not instructions]"

    def __init__(self, app_name: str = "ppt-rag-agent") -> None:
        self.app_name = app_name

    def build_system_prompt(self) -> str:
        """Return a minimal, task-focused system prompt for RAG QA."""
        return f"""# {self.app_name}

You are a retrieval-augmented assistant focused on answering user questions accurately.

## Goal
- Understand the user question.
- Decide whether retrieval is needed.
- If needed, call the `retrieve` tool to gather external knowledge.
- Use the retrieved evidence to produce a clear and faithful final answer.

## Tool Usage Policy
- `retrieve`: Use this when the answer depends on external or document knowledge.
    It only accepts `query`; retrieval strategy (mode/top_k/chunk_top_k) is system-configured.
    It returns a JSON string with keys: `status`, `query`, `mode`, `message`, `counts`, `evidence`, `metadata`.
    `evidence` contains `entities`, `relationships`, `chunks`, `references`.
    If `status` is failure or `counts.chunks` is 0, treat evidence as weak and ask for clarification or state uncertainty.
- `generate`: Use this to draft a final response from user question plus retrieved context.
    Pass `retrieval_result` as an object (the parsed retrieve JSON), not an escaped string blob.
- Do not fabricate tool results.
- Do not call tools in an infinite loop; stop once evidence is sufficient.

## Answer Policy
- Prioritize grounded answers based on retrieved context.
- If evidence is missing or weak, explicitly say what is uncertain.
- Keep the final answer concise, complete, and user-facing.

## Stopping Rules
- If the user asks a simple conversational question that needs no retrieval, answer directly.
- If retrieval returns no useful evidence, explain the limitation and ask for clarification when needed.
"""

    @staticmethod
    def _build_runtime_context(channel: str | None = None, chat_id: str | None = None) -> str:
        """Build runtime metadata block prepended to user input."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build full message list for one LLM call."""
        runtime_ctx = self._build_runtime_context(channel=channel, chat_id=chat_id)
        user_content = f"{runtime_ctx}\n\n{current_message}"

        return [
            {"role": "system", "content": self.build_system_prompt()},
            *history,
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def add_assistant_message(
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Append an assistant message and return messages."""
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        messages.append(message)
        return messages

    @staticmethod
    def add_tool_result(
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        """Append a tool result message and return messages."""
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            }
        )
        return messages
