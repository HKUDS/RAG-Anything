import os
import argparse
import asyncio
from raganything import RAGAnything, RAGAnythingConfig
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc


def build_llm_model_func(api_key: str, base_url: str | None):
    def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return openai_complete_if_cache(
            "gpt-4o-mini",
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    return llm_model_func


def build_vision_model_func(api_key: str, base_url: str | None, llm_model_func):
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
                "gpt-4o",
                "",
                system_prompt=None,
                history_messages=[],
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        if image_data:
            return openai_complete_if_cache(
                "gpt-4o",
                "",
                system_prompt=None,
                history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt}
                    if system_prompt
                    else None,
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                },
                            },
                        ],
                    },
                ],
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        return llm_model_func(prompt, system_prompt, history_messages or [], **kwargs)

    return vision_model_func


def build_embedding_func(api_key: str, base_url: str | None):
    return EmbeddingFunc(
        embedding_dim=3072,
        max_token_size=8192,
        func=lambda texts: openai_embed(
            texts,
            model="text-embedding-3-large",
            api_key=api_key,
            base_url=base_url,
        ),
    )


async def main():
    api_key = "sk-45rj0IHWppQbdpwjOCuMYGUUg6rjU7u7NX8gJiXw83P0QGtE"
    base_url = "https://yunwu.ai/v1"  # 可选

    llm_model_func = build_llm_model_func(api_key, base_url)
    vision_model_func = build_vision_model_func(api_key, base_url, llm_model_func)
    embedding_func = build_embedding_func(api_key, base_url)

    config = RAGAnythingConfig(
        working_dir="./rag_storage",
        parser="mineru",
        parse_method="auto",
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=embedding_func,
    )

    ensure_result = await rag._ensure_lightrag_initialized()
    if ensure_result and not ensure_result.get("success", True):
        raise RuntimeError(f"LightRAG 初始化失败: {ensure_result.get('error')}")

    content_list, doc_id = await rag.parse_document(
        file_path="example1.pdf",
        output_dir="./output",
        parse_method="auto",
        display_stats=True,
    )
    print(f"解析完成，块数={len(content_list)}，doc_id={doc_id}")

    topics = await rag.extract_page_topics(content_list, use_llm=True)
    print("逐页主题：")
    for idx, topic in sorted(topics.items()):
        print(f"- page {idx}: {topic}")


if __name__ == "__main__":
    asyncio.run(main())
