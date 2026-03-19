"""End-to-end validation: RetrieveTool.execute -> GenerateTool.execute.

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

    # Optional: ingest one document before testing the retrieve->generate chain
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

from rag_agent.agent.tools.generate import GenerateTool
from rag_agent.agent.tools.retrieve import RetrieveTool
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

    api_key = "sk-c4x9pza11AKl8KOirlU1yCjPzZjriUQxjhzjfy6W1AIRcLMa"
    base_url = "https://yunwu.ai/v1"
    model = os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large").strip()
    working_dir="./rag_storage3"

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY or LLM_BINDING_API_KEY")

    question = os.getenv("TEST_QUESTION", "请帮我总结example1.pdf这个文档的内容").strip()
    retrieve_mode = os.getenv("RETRIEVE_MODE", "hybrid").strip() or "hybrid"
    retrieve_top_k = 20
    retrieve_chunk_top_k = 20

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

    result = await loop.process_message(question,file_path="example1.pdf",parse_method="auto")

    print("final_answer:", result.final_answer)
    print("iterations:", result.iterations)
    print("tools_used:", result.tools_used)
    '''
    retrieve_tool = RetrieveTool(
        rag=rag,
        mode=retrieve_mode,
        top_k=retrieve_top_k,
        chunk_top_k=retrieve_chunk_top_k,
    )
    generate_tool = GenerateTool(provider=provider, rag=rag, model=model)
    
    print("[STEP 1] retrieve.execute")
    retrieval_result = await retrieve_tool.execute(query=question)
    #print(retrieval_result)
    base_dir = Path(working_dir)
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_file = output_dir / "retrieval_result.json"
    with open(json_file, "w", encoding="utf-8") as file:
        json.dump(json.loads(retrieval_result), file, ensure_ascii=False, indent=2)

    try:
        retrieval_json = json.loads(retrieval_result)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"retrieve output is not valid JSON: {exc}")

    if retrieval_json.get("status") != "success":
        raise SystemExit(f"retrieve failed: {retrieval_json.get('message', 'unknown error')}")

    counts = retrieval_json.get("counts", {})
    print(f"[STEP 1] counts: {counts}")

    print("[STEP 2] generate.execute")
    generate_result = await generate_tool.execute(
        question=question,
        retrieval_result=retrieval_result,
        style="balanced",
        language="zh-CN",
        include_citations=True,
    )
    print(generate_result)

    try:
        generate_json = json.loads(generate_result)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"generate output is not valid JSON: {exc}")

    if generate_json.get("status") != "success":
        raise SystemExit(f"generate failed: {generate_json.get('message', 'unknown error')}")

    print("[PASS] retrieve -> generate workflow is healthy")
    '''


if __name__ == "__main__":
    asyncio.run(main())
