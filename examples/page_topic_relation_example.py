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
        # normalize a bit for stability
        if np.linalg.norm(vec) > 0:
            vec = vec / np.linalg.norm(vec)
        vectors.append(vec)
    return np.vstack(vectors)


def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    return ""


async def main():
    config = RAGAnythingConfig(working_dir="./rag_storage2", parser="mineru")
    embedding_func = EmbeddingFunc(embedding_dim=32, func=dummy_embed)

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )


    page_topics = {
        0: "数字图像存储",
        1: "图像存储方式",
        2: "傅里叶变换",
        3: "数字图像的存储方法",
    }

    await rag.build_page_topic_relations(
        page_topics,
        cosine_threshold=0.2,
        file_path="page_topic_test",
    )

    nodes = await rag.lightrag.chunk_entity_relation_graph.get_all_nodes()
    edges = await rag.lightrag.chunk_entity_relation_graph.get_all_edges()

    print(f"nodes={len(nodes)} edges={len(edges)}")
    for edge in edges[:5]:
        print(edge)


if __name__ == "__main__":
    asyncio.run(main())
