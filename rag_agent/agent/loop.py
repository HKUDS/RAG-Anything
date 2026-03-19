"""Minimal agent loop for RAG tool-calling workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_agent.llm.base import LLMProvider

from .context import ContextBuilder
from .session import Session, SessionManager
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
        workspace: str | Path,
        model: str | None = None,
        max_iterations: int = 8,
        max_tool_calls: int = 8,
        max_history_messages: int = 200,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        rag: Any | None = None,
        retrieve_config: dict[str, Any] | None = None,
        context: ContextBuilder | None = None,
        tools: ToolRegistry | None = None,
        sessions: SessionManager | None = None,
    ) -> None:
        self.provider = provider
        self.workspace = Path(workspace).expanduser().resolve()
        self.rag = rag
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.max_history_messages = max_history_messages
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retrieve_config = dict(retrieve_config or {})

        self.context = context or ContextBuilder()
        self.tools = tools or ToolRegistry()
        self.sessions = sessions or SessionManager(self.workspace)
        if tools is None:
            self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default RAG tools for MVP."""
        self.tools.register(
            RetrieveTool(
                rag=self.rag,
                mode=str(self.retrieve_config.get("mode", "hybrid")),
                top_k=self.retrieve_config.get("top_k"),
                chunk_top_k=self.retrieve_config.get("chunk_top_k"),
            )
        )
        self.tools.register(
            GenerateTool(
                provider=self.provider,
                rag=self.rag,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        )

    async def process_message(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        session_key: str | None = None,
        file_path: str | Path | None = None,
        parse_method: str | None = None,
        session_options: dict[str, Any] | None = None,
    ) -> AgentLoopResult:
        """Build session/context and then run one agent loop turn."""
        resolved_session_key = session_key or self._build_session_key(
            file_path=file_path,
            parse_method=parse_method,
            **(session_options or {}),
        )
        session = self.sessions.get_or_create(resolved_session_key)

        history_messages = history
        if history_messages is None:
            history_messages = session.get_history(max_messages=self.max_history_messages)
        
        messages = self.context.build_messages(
            history=history_messages,
            current_message=user_message,
            channel=channel,
            chat_id=chat_id,
        )
        print("[DEBUG] prepared messages for LLM:", json.dumps(messages, indent=2, ensure_ascii=False))
        result = await self.run_once(messages)
        self._save_turn(session=session, messages=result.messages, skip=1 + len(history_messages))
        self.sessions.save(session)
        return result

    async def run_once(self, initial_messages: list[dict[str, Any]]) -> AgentLoopResult:
        """Run the pure agent loop over prepared messages."""
        messages = initial_messages

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

    @staticmethod
    def _build_session_key(
        file_path: str | Path | None,
        parse_method: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Build file-scoped session key, inspired by processor cache-key logic."""
        if not file_path:
            return "chat:default"

        path = Path(file_path).expanduser().resolve()
        mtime = path.stat().st_mtime if path.exists() else None

        config_dict: dict[str, Any] = {
            "file_path": str(path),
            "mtime": mtime,
            "parse_method": parse_method,
        }

        relevant_keys = {
            "lang",
            "device",
            "start_page",
            "end_page",
            "formula",
            "table",
            "backend",
            "source",
        }
        for key, value in kwargs.items():
            if key in relevant_keys:
                config_dict[key] = value

        key_payload = json.dumps(config_dict, sort_keys=True, ensure_ascii=False)
        key_hash = hashlib.md5(key_payload.encode()).hexdigest()
        return f"file:{key_hash}"

    @staticmethod
    def _save_turn(session: Session, messages: list[dict[str, Any]], skip: int) -> None:
        """Save only new turn messages into session history."""
        for msg in messages[skip:]:
            entry = dict(msg)
            role = entry.get("role")
            content = entry.get("content")

            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue

            if role == "user" and isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                parts = content.split("\n\n", 1)
                if len(parts) > 1 and parts[1].strip():
                    entry["content"] = parts[1]
                else:
                    continue

            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)

        session.updated_at = datetime.now()
