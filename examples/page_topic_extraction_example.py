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
            "type": "list",
            "sub_type": "text",
            "list_items": [
                "放大位图时，增大每个像素，从而使线条和形状参差不齐。",
                "缩小位图时，也使原图变形。",
                "位图方式下，影响图像质量的关键因素是颜色数量和分辨率。",
            ],
            "bbox": [50, 220, 785, 416],
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
