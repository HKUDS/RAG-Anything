"""End-to-end validation: retrieve-only AgentLoop workflow.

Usage:
    python -m rag_agent.agent.tools.validate_retrieve_generate_flow

Optional env:
    OPENAI_API_KEY=...
    OPENAI_BASE_URL=https://api.openai.com/v1
    OPENAI_MODEL=gpt-4o-mini
    EMBEDDING_MODEL=text-embedding-3-large
    WORKING_DIR=./rag_storage2
    TEST_QUESTION=请帮我总结知识库里关于RAG检索流程的核心要点
    RETRIEVE_MODE=hybrid
    RETRIEVE_TOP_K=5
    RETRIEVE_CHUNK_TOP_K=5

    # Optional: ingest one document before testing the agent workflow
    TEST_FILE_PATH=./inputs/demo.pdf
    TEST_OUTPUT_DIR=./output
    TEST_PARSE_METHOD=auto
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if __package__ is None or __package__ == "":
    # Allow direct execution via: python rag_agent/agent/tools/validate_retrieve_generate_flow.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from rag_agent.llm.openai_provider import OpenAIProvider
from rag_agent.agent.loop import AgentLoop


def _int_env(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _build_rag(api_key: str, base_url: str, model: str, embedding_model: str, working_dir: str) -> RAGAnything:
    config = RAGAnythingConfig(
        working_dir=working_dir,
        parser="mineru",
        parse_method="auto",
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return openai_complete_if_cache(
            model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    def vision_model_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        image_data=None,
        messages=None,
        **kwargs,
    ):
        if messages:
            return openai_complete_if_cache(
                model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )

        if image_data:
            assembled_messages: list[dict[str, Any]] = []
            if system_prompt:
                assembled_messages.append({"role": "system", "content": system_prompt})
            assembled_messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                        },
                    ],
                }
            )
            return openai_complete_if_cache(
                model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=assembled_messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )

        return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

    embedding_func = EmbeddingFunc(
        embedding_dim=3072,
        max_token_size=8192,
        func=lambda texts: openai_embed(
            texts,
            model=embedding_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )

    return RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=embedding_func,
    )


async def _maybe_ingest_file(rag: RAGAnything) -> None:
    file_path = "example1.pdf"
    if not file_path:
        return

    output_dir = os.getenv("TEST_OUTPUT_DIR", "./output")
    parse_method = os.getenv("TEST_PARSE_METHOD", "auto")
    path_obj = Path(file_path).expanduser().resolve()
    if not path_obj.exists():
        raise SystemExit(f"TEST_FILE_PATH does not exist: {path_obj}")

    print(f"[SETUP] ingesting file: {path_obj}")
    await rag.process_document_complete_with_page_topics(
        file_path=str(path_obj),
        output_dir=output_dir,
        parse_method=parse_method,
    )
    print("[SETUP] ingest finished")


async def main() -> None:
    load_dotenv()

    api_key = "sk-GPqvN7FUGToh5cIqFKzaY6eZuoUwRUpwHIuUGzip7uEpv5Uo"
    base_url = "https://yunwu.ai/v1"
    model = os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LLM_MODEL", "gpt-4o").strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large").strip()
    working_dir="./rag_storage3"

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY or LLM_BINDING_API_KEY")

    question = os.getenv("TEST_QUESTION", "请帮我总结这个文档的内容").strip()
    rag = _build_rag(
        api_key=api_key,
        base_url=base_url,
        model=model,
        embedding_model=embedding_model,
        working_dir=working_dir,
    )
    await _maybe_ingest_file(rag)

    provider = OpenAIProvider(api_key=api_key, api_base=base_url, default_model=model)

    loop = AgentLoop(
        provider=provider,
        workspace="./rag_agent_loop",
        rag=rag,
        retrieve_config={
            "mode": "hybrid",
            "top_k": 20,
            "chunk_top_k": 20,
        },
    )

    result = await loop.process_message(question, file_path="example1.pdf", parse_method="auto")

    print("final_answer:", result.final_answer)
    print("iterations:", result.iterations)
    print("tools_used:", result.tools_used)
    if not result.final_answer.strip():
        raise SystemExit("Agent loop failed: empty final answer")

    print("[PASS] retrieve-only agent workflow is healthy")


if __name__ == "__main__":
    asyncio.run(main())
