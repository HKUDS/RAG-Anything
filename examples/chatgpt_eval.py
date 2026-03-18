#!/usr/bin/env python
"""
Evaluate questions using GPT-4o-mini directly (without RAG).
Reads a JSON question file, sends each question to GPT-4o-mini,
and saves results to data/chatgpt/ with auto-generated filenames.
"""
 
import os
import json
import argparse
import asyncio
import logging
from pathlib import Path
from datetime import datetime
 
import sys
sys.path.append(str(Path(__file__).parent.parent))
 
from openai import AsyncOpenAI
from dotenv import load_dotenv
 
load_dotenv(dotenv_path=".env", override=False)
 
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)
 
 
async def query_gpt4o(client: AsyncOpenAI, question: str, options: dict) -> str:
    """Send a single question to GPT-4o-mini and return its answer."""
    options_text = "\n".join(f"{key}. {value}" for key, value in options.items())
    prompt = (
        f"{question}\n\n选项：\n{options_text}\n\n"
        f"请直接回答正确选项的字母（A/B/C/D），并简要说明理由。"
    )
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "你是一个计算机科学领域的专业教师，擅长数据结构和算法。请根据题目内容选择正确答案。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT-4o-mini API call failed: {e}")
        return None
 
 
async def evaluate(questions_file: str, api_key: str, base_url: str = None):
    """Main evaluation logic."""
    # Load questions
    with open(questions_file, "r", encoding="utf-8") as f:
        data = json.load(f)
 
    questions = data.get("single_choice", [])
    logger.info(f"Loaded {len(questions)} questions from {questions_file}")
 
    # Init OpenAI client
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)
 
    results = []
    for item in questions:
        qid = item["id"]
        question = item["question"]
        options = item["options"]
        correct_answer = item.get("answer")  # may be None if no answer field
 
        logger.info(f"\n[Question {qid}]: {question}")
 
        model_answer = await query_gpt4o(client, question, options)
        logger.info(f"Model Answer: {model_answer}")
        if correct_answer:
            logger.info(f"Correct Answer: {correct_answer}")
 
        results.append(
            {
                "id": qid,
                "question": question,
                "options": options,
                "correct_answer": correct_answer,
                "model_answer": model_answer,
            }
        )
 
    # Calculate accuracy (only if answers are present)
    answered = [r for r in results if r["model_answer"] is not None and r["correct_answer"] is not None]
    correct_count = sum(
        1 for r in answered
        if r["correct_answer"].strip().upper() in r["model_answer"].strip().upper()
    )
    accuracy = correct_count / len(answered) if answered else 0
 
    output = {
        "accuracy": f"{accuracy:.2%}",
        "correct": correct_count,
        "answered": len(answered),
        "total": len(results),
        "results": results,
    }
 
    # Save to data/chatgpt/ with auto-generated filename
    output_dir = Path("data/chatgpt")
    output_dir.mkdir(parents=True, exist_ok=True)
 
    source_stem = Path(questions_file).stem  # e.g. "test5_questions_v2"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{source_stem}_{timestamp}.json"
 
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
 
    logger.info(f"\nResults saved to {output_file}")
    if answered:
        logger.info(f"Accuracy: {accuracy:.2%} ({correct_count}/{len(answered)})")
    else:
        logger.info("No answers provided in input file, accuracy not calculated.")
 
 
def main():
    parser = argparse.ArgumentParser(description="Evaluate questions with GPT-4o-mini")
    parser.add_argument("questions_file", help="Path to the JSON file containing questions")
    parser.add_argument(
        "--api-key",
        default=os.getenv("LLM_BINDING_API_KEY"),
        help="OpenAI API key (defaults to LLM_BINDING_API_KEY env var)",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LLM_BINDING_HOST"),
        help="Optional base URL for API",
    )
    args = parser.parse_args()
 
    if not args.api_key:
        logger.error("Error: API key is required. Set LLM_BINDING_API_KEY or use --api-key.")
        return
 
    asyncio.run(evaluate(args.questions_file, args.api_key, args.base_url))
 
 
if __name__ == "__main__":
    main()