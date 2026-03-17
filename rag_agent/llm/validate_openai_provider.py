"""Manual validation script for OpenAIProvider.

Usage:
    OPENAI_API_KEY=... python -m rag_agent.llm.validate_openai_provider
Optional env:
    OPENAI_BASE_URL=http://localhost:8000/v1
    OPENAI_MODEL=gpt-4o-mini
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow running via: python rag_agent/llm/validate_openai_provider.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_agent.llm.openai_provider import OpenAIProvider


async def main() -> None:
    api_key = "sk-c4x9pza11AKl8KOirlU1yCjPzZjriUQxjhzjfy6W1AIRcLMa"
    api_base = "https://yunwu.ai/v1"
    model = "gpt-4o-mini"

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY")

    provider = OpenAIProvider(api_key=api_key, api_base=api_base, default_model=model)

    print("[1/2] validating plain chat...")
    plain = await provider.chat(
        messages=[{"role": "user", "content": "请回复: provider ok"}],
    )
    print("finish_reason:", plain.finish_reason)
    print("content:", plain.content)
    print("usage:", plain.usage)

    print("\n[2/2] validating tool call output...")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "retrieve",
                "description": "Retrieve passages for a query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        }
    ]

    tool_resp = await provider.chat(
        messages=[
            {
                "role": "user",
                "content": "你必须调用 retrieve 工具来查询: agent loop 最小实现",
            }
        ],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "retrieve"}},
    )

    print("finish_reason:", tool_resp.finish_reason)
    print("tool_calls_count:", len(tool_resp.tool_calls))
    if tool_resp.tool_calls:
        tc = tool_resp.tool_calls[0]
        print("first_tool:", tc.name)
        print("first_args:", tc.arguments)
    else:
        print("no tool call returned; check model/tool-call support")


if __name__ == "__main__":
    asyncio.run(main())
