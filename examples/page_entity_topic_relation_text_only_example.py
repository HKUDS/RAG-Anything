import asyncio
import numpy as np

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc


async def dummy_embed(texts):
    dim = 32
    vectors = []
    for text in texts:
        vec = np.zeros(dim, dtype=np.float32)
        for ch in text:
            idx = (ord(ch) * 31) % dim
            vec[idx] += 1.0
        if np.linalg.norm(vec) > 0:
            vec = vec / np.linalg.norm(vec)
        vectors.append(vec)
    return np.vstack(vectors)


async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    # Minimal valid extraction output for LightRAG
    tuple_delimiter = "<|#|>"
    completion_delimiter = "<|COMPLETE|>"
    return (
        f"entity{tuple_delimiter}Page Entity{tuple_delimiter}Concept"
        f"{tuple_delimiter}A test entity for page relation.\n"
        f"{completion_delimiter}"
    )


async def main():
    config = RAGAnythingConfig(working_dir="./rag_storage5", parser="mineru")
    embedding_func = EmbeddingFunc(embedding_dim=32, func=dummy_embed)

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )

    # Skip parser check for KG-only test
    rag._parser_installation_checked = True

    # Prepare a fake content_list (text only)
    content_list = [
        {"type": "text", "text": "数字图像存储的定义", "page_idx": 0},
        {
            "type": "list",
            "sub_type": "text",
            "list_items": ["位图放大会失真", "颜色数量影响质量"],
            "page_idx": 0,
        },
        {"type": "text", "text": "傅里叶变换在图像处理中的应用", "page_idx": 1},
    ]

    # Cache latest parse info for no-input function
    rag._latest_content_list = content_list
    rag._latest_doc_id = "doc-test"
    rag._latest_file_path = "test.pdf"

    # Build page topics (use heuristic, no LLM)
    page_topics = await rag.extract_page_topics(content_list, use_llm=False)
    # Store topics in KG
    await rag.build_page_topic_relations(page_topics, cosine_threshold=0.1)

    # Build entity->page_topic relations (text only)
    await rag.build_page_entity_topic_relations_text_only()

    edges = await rag.lightrag.chunk_entity_relation_graph.get_all_edges()
    print(f"edges={len(edges)}")
    for edge in edges[:5]:
        print(edge)


if __name__ == "__main__":
    asyncio.run(main())
