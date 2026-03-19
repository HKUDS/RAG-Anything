"""Validate GenerateTool behavior with fake provider and fake multimodal RAG.

Usage:
    python -m rag_agent.agent.tools.validate_generate_tool
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from rag_agent.agent.tools.generate import GenerateTool
from rag_agent.llm.base import LLMProvider, LLMResponse


class _FakeProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        _ = (messages, tools, model, max_tokens, temperature, tool_choice)
        return LLMResponse(content="这是文本分支生成结果。", finish_reason="stop")


class _FakeRAG:
    vision_model_func = object()

    async def _process_image_paths_for_vlm(self, prompt: str) -> tuple[str, int]:
        if "Image Path:" in prompt:
            return prompt + "\n[VLM_IMAGE_1]", 1
        return prompt, 0

    def _build_vlm_messages_with_images(self, enhanced_prompt: str, user_query: str, system_prompt: str):
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": enhanced_prompt},
                    {"type": "text", "text": user_query},
                ],
            },
        ]

    async def _call_vlm_with_multimodal_content(self, messages):
        _ = messages
        return "这是多模态分支生成结果（VLM pipeline）。"


def _build_retrieval_result(with_image: bool) -> str:
    chunk_content = "RAG combines retrieval and generation."
    if with_image:
        chunk_content += "\nImage Path: /tmp/demo_chart.png"

    payload = {
        "status": "success",
        "message": "ok",
        "counts": {"entities": 1, "relationships": 0, "chunks": 1, "references": 1},
        "evidence": {
            "entities": [
                {
                    "entity_name": "RAG",
                    "description": "Retrieval-Augmented Generation",
                }
            ],
            "relationships": [],
            "chunks": [
                {
                    "content": chunk_content,
                    "file_path": "demo.pdf",
                    "reference_id": "[1]",
                }
            ],
            "references": [{"reference_id": "[1]", "file_path": "demo.pdf"}],
        },
        "metadata": {"query_mode": "hybrid"},
    }
    return json.dumps(payload, ensure_ascii=False)


async def main() -> None:
    text_tool = GenerateTool(provider=_FakeProvider(default_model="fake-model"), rag=None)
    text_result = await text_tool.execute(
        question="什么是RAG？",
        retrieval_result=_build_retrieval_result(with_image=False),
    )
    text_parsed = json.loads(text_result)
    assert text_parsed["status"] == "success"
    assert text_parsed["used_multimodal"] is False
    assert "文本分支" in text_parsed["answer"]

    mm_tool = GenerateTool(
        provider=_FakeProvider(default_model="fake-model"),
        rag=_FakeRAG(),
        multimodal_mode="mix",
    )
    mm_result = await mm_tool.execute(
        question="图里表达了什么？",
        retrieval_result=_build_retrieval_result(with_image=True),
    )
    mm_parsed = json.loads(mm_result)
    assert mm_parsed["status"] == "success"
    assert mm_parsed["used_multimodal"] is True
    assert "VLM pipeline" in mm_parsed["answer"]

    print("GENERATE_TOOL_TEST: PASS")
    print("TEXT_RESULT:", text_result)
    print("MM_RESULT:", mm_result)


if __name__ == "__main__":
    asyncio.run(main())
