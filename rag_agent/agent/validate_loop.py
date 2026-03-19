"""Manual validation script for AgentLoop.

Usage:
    OPENAI_API_KEY=... python -m rag_agent.agent.validate_loop
Optional env:
    OPENAI_BASE_URL=http://localhost:8000/v1
    OPENAI_MODEL=gpt-4o-mini
    TEST_QUESTION=什么是RAG
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow direct execution via: python rag_agent/agent/validate_loop.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_agent.agent.loop import AgentLoop
from rag_agent.llm.openai_provider import OpenAIProvider


async def main() -> None:
    api_key = "sk-c4x9pza11AKl8KOirlU1yCjPzZjriUQxjhzjfy6W1AIRcLMa"
    api_base = "https://yunwu.ai/v1"
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    question = os.getenv("TEST_QUESTION", "rag一般是怎么检索相关信息的？")

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY")

    provider = OpenAIProvider(api_key=api_key, api_base=api_base, default_model=model)
    loop = AgentLoop(provider=provider, workspace="./rag_agent_loop")

    result = await loop.process_message(question)

    print("final_answer:", result.final_answer)
    print("iterations:", result.iterations)
    print("tools_used:", result.tools_used)


if __name__ == "__main__":
    asyncio.run(main())
