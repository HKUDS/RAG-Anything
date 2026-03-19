"""Validate session control in AgentLoop without real model API.

Usage:
    python -m rag_agent.agent.validate_session_loop
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from rag_agent.agent.loop import AgentLoop
from rag_agent.llm.base import LLMProvider, LLMResponse


class FakeProvider(LLMProvider):
    """A deterministic provider used for local session tests."""

    def __init__(self) -> None:
        super().__init__(api_key="fake", default_model="fake-model")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        user_count = sum(1 for m in messages if m.get("role") == "user")
        return LLMResponse(content=f"user_turns_seen={user_count}", finish_reason="stop")


async def main() -> None:
    provider = FakeProvider()

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        file_a = Path(tmpdir) / "doc_a.pdf"
        file_b = Path(tmpdir) / "doc_b.pdf"
        file_a.write_text("a", encoding="utf-8")
        file_b.write_text("b", encoding="utf-8")

        loop = AgentLoop(provider=provider, workspace=workspace)

        # Same file => same session => history should accumulate.
        r1 = await loop.process_message("Q1", file_path=str(file_a))
        r2 = await loop.process_message("Q2", file_path=str(file_a))

        # Recreate loop => session should be restored from disk.
        loop = AgentLoop(provider=provider, workspace=workspace)
        r3 = await loop.process_message("Q3", file_path=str(file_a))

        # Different file => different session => isolated history.
        r4 = await loop.process_message("Q4", file_path=str(file_b))

    print("same_file_turn1:", r1.final_answer)
    print("same_file_turn2:", r2.final_answer)
    print("same_file_after_reload:", r3.final_answer)
    print("other_file_turn1:", r4.final_answer)

    ok_same = r1.final_answer.endswith("=1") and r2.final_answer.endswith("=2")
    ok_persisted = r3.final_answer.endswith("=3")
    ok_isolation = r4.final_answer.endswith("=1")

    if ok_same and ok_persisted and ok_isolation:
        print("SESSION_TEST: PASS")
        return

    print("SESSION_TEST: FAIL")
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
