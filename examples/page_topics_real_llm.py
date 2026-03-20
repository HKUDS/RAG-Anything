import os
import argparse
import asyncio
from raganything import RAGAnything, RAGAnythingConfig
from lightrag import QueryParam
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything.utils import (
    separate_content,
)


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
    api_key = "sk-gkkdEvXexdGEsUCxymzqAyc2e3faJmmLmLWzmijFrI6HNeYz"
    base_url = "https://yunwu.ai/v1"  # 可选

    llm_model_func = build_llm_model_func(api_key, base_url)
    vision_model_func = build_vision_model_func(api_key, base_url, llm_model_func)
    embedding_func = build_embedding_func(api_key, base_url)

    config = RAGAnythingConfig(
        working_dir="./rag_storage5",
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
        file_path="test2.pdf",
        output_dir="./output",
        parse_method="auto",
        display_stats=True,
    )
    print(f"解析完成，块数={len(content_list)}，doc_id={doc_id}")

    topics = await rag.extract_page_topics(content_list, use_llm=True)
    print("逐页主题：")
    for idx, topic in sorted(topics.items()):
        print(f"- page {idx}: {topic}")
    
    await rag.build_page_topic_relations(
        topics,
        cosine_threshold=0.7,
        file_path="test2.pdf",
    )

    nodes = await rag.lightrag.chunk_entity_relation_graph.get_all_nodes()
    edges = await rag.lightrag.chunk_entity_relation_graph.get_all_edges()

    print(f"nodes={len(nodes)} edges={len(edges)}")
    for edge in edges[:5]:
        print(edge)

    await rag.build_page_entity_topic_relations_text_only(
        page_topics=topics,
        content_list=content_list,
        doc_id=doc_id,
        file_path="test2.pdf",
    )

    edges = await rag.lightrag.chunk_entity_relation_graph.get_all_edges()
    print(f"edges={len(edges)}")
    for edge in edges[:5]:
        print(edge)
    
    text_content, multimodal_items = separate_content(content_list)
    rag.set_content_source_for_context(
                content_list, rag.config.content_format
    )
    
    file_name = rag._get_file_reference(file_path="test2.pdf")
    if multimodal_items:
            await rag._process_multimodal_content(multimodal_items, file_name, doc_id)
    else:
        # If no multimodal content, mark multimodal processing as complete
        # This ensures the document status properly reflects completion of all processing
        await rag._mark_multimodal_processing_complete(doc_id)
        rag.logger.debug(
            f"No multimodal content found in document {doc_id}, marked multimodal processing as complete"
        )
        rag.logger.info(f"Document 'test2.pdf' processing complete!")
    query_text = "请简要介绍储存转发这一交换模式"

    # 先获取结构化检索结果，检查是否命中 page_topic 实体
    query_param = QueryParam(mode="hybrid")
    query_data = await rag.lightrag.aquery_data(query_text, param=query_param)
    data_block = query_data.get("data", {}) if isinstance(query_data, dict) else {}
    entities = data_block.get("entities", []) if isinstance(data_block, dict) else []

    # 过滤出 page_topic 实体及其命中情况
    page_topic_entities = [
        e for e in entities if isinstance(e, dict) and e.get("entity_type") == "page_topic"
    ]
    print(f"命中 page_topic 实体数: {len(page_topic_entities)}")
    for e in page_topic_entities[:10]:
        print(f"- {e.get('entity_name')} | {e.get('description', '')}")

    # 如需检查是否命中本次生成的 topics
    topic_set = set(topics.values())
    matched_topics = [
        e for e in page_topic_entities if e.get("entity_name") in topic_set
    ]
    print(f"命中当前文档 topics 数: {len(matched_topics)}")

    # 继续正常 aquery 生成回答
    text_result = await rag.aquery(query_text, mode="hybrid")
    print("文本查询结果:", text_result)


if __name__ == "__main__":
    asyncio.run(main())
