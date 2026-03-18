"""
Utility functions for RAGAnything query pipeline.
"""

import logging

logger = logging.getLogger("lightrag")


async def query_multiple_choice(rag, question: str, options: dict) -> str | None:
    """
    Two-stage query for multiple choice questions.
    Stage 1: Ask for the answer only (no options), to avoid answer jumping.
    Stage 2: Match the answer to the correct option letter.

    Args:
        rag: RAGAnything instance
        question: The question text
        options: Dict of option letters to values, e.g. {"A": "0", "B": "1", ...}

    Returns:
        The matching option letter (A/B/C/D), or None if query failed.
    """
    # Stage 1: get the answer without options
    query_step1 = f"{question}\n\n请直接给出答案，不要解释。"
    try:
        result_step1 = await rag.aquery(query_step1, mode="hybrid")
    except Exception as e:
        logger.error(f"Stage 1 query failed: {e}")
        return None

    if not isinstance(result_step1, str):
        return None

    logger.info(f"Stage 1 Answer: {result_step1}")

    # Stage 2: match answer to option letter
    options_text = "\n".join(f"{key}. {value}" for key, value in options.items())
    query_step2 = (
        f"题目：{question}\n\n"
        f"已知答案是：{result_step1}\n\n"
        f"选项：\n{options_text}\n\n"
        f"请只输出与答案最匹配的选项字母（A/B/C/D），不要任何其他内容。"
    )
    try:
        result_step2 = await rag.aquery(query_step2, mode="hybrid")
    except Exception as e:
        logger.error(f"Stage 2 query failed: {e}")
        return None

    return result_step2 if isinstance(result_step2, str) else None