"""
交互式查询 - 直接启动，基于已有的知识库
用法: python query.py
"""
import asyncio
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from functools import partial
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=False)

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig

API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))


async def main():
    def llm_func(prompt, system_prompt=None, history_messages=[], **kw):
        return openai_complete_if_cache(
            LLM_MODEL, prompt,
            system_prompt=system_prompt, history_messages=history_messages,
            api_key=API_KEY, base_url=BASE_URL, **kw,
        )

    def vision_func(prompt, system_prompt=None, history_messages=[],
                    image_data=None, messages=None, **kw):
        if messages is not None:
            return openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=messages, api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        elif image_data is not None:
            return openai_complete_if_cache(
                VISION_MODEL, "", system_prompt=None, history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                    ]},
                ],
                api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        else:
            return llm_func(prompt, system_prompt, history_messages, **kw)

    embedding_func = EmbeddingFunc(
        embedding_dim=EMB_DIM, max_token_size=8192,
        func=partial(openai_embed.func, model=EMB_MODEL, api_key=API_KEY, base_url=BASE_URL),
    )

    config = RAGAnythingConfig(
        working_dir="./rag_storage", parser="docling",
        enable_image_processing=False, enable_table_processing=False,
        enable_equation_processing=False,
    )

    rag = RAGAnything(
        config=config, llm_model_func=llm_func,
        vision_model_func=vision_func, embedding_func=embedding_func,
    )

    print("加载已有知识库...")
    result = await rag._ensure_lightrag_initialized()
    if not result.get("success"):
        print(f"初始化失败: {result.get('error')}")
        return
    print("就绪。输入 quit 退出。\n")

    while True:
        try:
            q = input("你的问题: ").strip()
            if q.lower() in ("quit", "exit", "q"):
                break
            if not q:
                continue
            print("思考中...")
            ans = await rag.aquery(q, mode="hybrid", vlm_enhanced=False)
            print(f"\n{ans}\n")
        except KeyboardInterrupt:
            break

    print("再见!")

if __name__ == "__main__":
    asyncio.run(main())
