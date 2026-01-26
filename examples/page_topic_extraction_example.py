import asyncio

from raganything.raganything import RAGAnything
from raganything.config import RAGAnythingConfig


def fake_llm_model(prompt, system_prompt=None, history_messages=None, **kwargs):
    """Simple stub that always returns a JSON topic."""
    return "{\"page_idx\": 1, \"topic\": \"Digital image storage\"}"


def build_sample_content_list():
    """Construct a minimal content_list for quick testing."""
    return [
        {"type": "header", "text": "绪论", "page_idx": 0},
        {
            "type": "text",
            "text": "数字图像怎么存储？",
            "text_level": 1,
            "bbox": [270, 450, 700, 551],
            "page_idx": 1,
        },
        {
            "type": "image",
            "img_path": "/home/lh/project2026/ppt-RAG/output/example1/hybrid_auto/images/123.jpg",
            "image_caption": ["示例图片"],
            "image_footnote": [],
            "bbox": [318, 566, 458, 809],
            "page_idx": 1,
        },
    ]


async def main():
    config = RAGAnythingConfig(parser="mineru", parse_method="auto")
    rag = RAGAnything(config=config, llm_model_func=fake_llm_model)

    content_list = build_sample_content_list()
    topics = await rag.extract_page_topics(content_list, use_llm=True)
    print("Extracted topics:", topics)


if __name__ == "__main__":
    asyncio.run(main())
