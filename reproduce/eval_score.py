#!/usr/bin/env python
"""使用 qwen-plus 自动评测 100 道题的答案准确度。"""

import json, os, sys, asyncio, logging, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from lightrag.llm.openai import openai_complete_if_cache
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)

logger = logging.getLogger("eval_score")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
EVAL_MODEL = "qwen-plus"  # DashScope 可用模型

INPUT_FILE = "evaluation_energy/qa_results_hybrid_20260724_120349.json"
OUTPUT_DIR = Path("evaluation_energy")

EVAL_SYSTEM_PROMPT = """你是一个严格的 RAG 答案评测专家。你的任务是对比"标准答案"和"RAG生成答案"，从多个维度打分。

评分规则：
- accuracy (0或1)：生成答案的事实内容是否与标准答案一致。数字、名称、定义这些关键信息一致则给1，否则给0。
- relevance (0-1)：生成答案与问题的相关性。
- completeness (0-1)：相比标准答案，生成答案是否完整覆盖了关键信息点。
- faithfulness (0-1)：生成答案是否有编造标准答案中没有的内容（越少编造分越高）。

输出严格的 JSON 格式，不要多余文字：
{"accuracy": 0或1, "relevance": 0.0-1.0, "completeness": 0.0-1.0, "faithfulness": 0.0-1.0, "overall": 0.0-1.0, "reasoning": "一句中文理由"}
"""


def build_eval_prompt(question: str, expected: str, generated: str) -> str:
    return f"""【问题】{question}

【标准答案】{expected}

【RAG生成答案】{generated}

请按 JSON 格式打分："""


async def evaluate_one(question: str, expected: str, generated: str) -> dict:
    prompt = build_eval_prompt(question, expected, generated)
    for attempt in range(3):
        try:
            raw = await asyncio.wait_for(
                openai_complete_if_cache(
                    model=EVAL_MODEL,
                    prompt=prompt,
                    system_prompt=EVAL_SYSTEM_PROMPT,
                    api_key=API_KEY,
                    base_url=BASE_URL,
                    temperature=0.0,
                    max_tokens=500,
                ),
                timeout=30,
            )
            # Extract JSON
            raw = raw.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            # Find JSON object
            import re
            m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
            else:
                result = json.loads(raw)
            return {"success": True, **result}
        except (asyncio.TimeoutError, Exception) as e:
            if attempt == 2:
                return {"success": False, "error": str(e), "accuracy": -1}
            await asyncio.sleep(1)


async def main():
    # Load results
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info(f"Loaded {len(data)} QA pairs")

    # Filter out empty answers
    valid = [d for d in data if d.get("answer", "").strip() and d.get("success", True)]
    logger.info(f"Valid (non-empty) answers: {len(valid)}/{len(data)}")

    # Evaluate
    scores = []
    correct = 0
    total = len(valid)

    for i, item in enumerate(valid, 1):
        q = item["question"]
        expected = item.get("correct_answer", item.get("expected_answer", ""))
        generated = item.get("answer", "")

        result = await evaluate_one(q, expected, generated)

        accuracy = result.get("accuracy", -1)
        overall = result.get("overall", 0)
        reasoning = result.get("reasoning", "")

        if accuracy == 1:
            correct += 1

        scores.append({
            "question": q[:80],
            "expected_answer": expected[:120],
            "generated_answer": generated[:120],
            **result,
        })

        logger.info(f"[{i}/{total}] acc={accuracy} overall={overall:.2f} {reasoning[:40]}")

        # Save every 20
        if i % 20 == 0:
            rate = correct / i * 100 if i > 0 else 0
            logger.info(f"  → Current accuracy: {correct}/{i} = {rate:.1f}%")

    # Stats
    accuracy_rate = correct / total * 100 if total > 0 else 0
    avg_overall = sum(s.get("overall", 0) for s in scores) / len(scores) if scores else 0

    # Report
    report = f"""# 新能源知识库 RAG 检索准确度评测报告

## 概览
- **评测时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **评测模型**: {EVAL_MODEL}
- **测试问题数**: {total}
- **知识库**: 新能源（《新能源汽车电气技术》）
- **查询模式**: hybrid

## 准确度
- **正确数**: {correct}/{total}
- **准确率**: {accuracy_rate:.1f}%
- **平均综合得分**: {avg_overall:.2f}/1.0

## 分维度统计
| 维度 | 平均分 |
|------|--------|
| Accuracy | {accuracy_rate:.1f}% |
| Relevance | {sum(s.get('relevance', 0) for s in scores) / len(scores):.3f} |
| Completeness | {sum(s.get('completeness', 0) for s in scores) / len(scores):.3f} |
| Faithfulness | {sum(s.get('faithfulness', 0) for s in scores) / len(scores):.3f} |
| Overall | {avg_overall:.3f} |

## 质量分布
- 高 (>80%): {sum(1 for s in scores if s.get('overall', 0) >= 0.8)} 题
- 中 (50-80%): {sum(1 for s in scores if 0.5 <= s.get('overall', 0) < 0.8)} 题
- 低 (<50%): {sum(1 for s in scores if s.get('overall', 0) < 0.5)} 题

## 低分案例（需关注）
"""
    low_scores = [s for s in scores if s.get("overall", 0) < 0.6]
    for s in low_scores[:15]:
        report += f"- **Q**: {s['question'][:60]}... → acc={s.get('accuracy')} overall={s.get('overall', 0):.2f} reason={s.get('reasoning', '')[:80]}\n"

    report += f"""
## 输出文件
- 详细评分: `{OUTPUT_DIR / 'eval_scores.json'}`
- 评测报告: `{OUTPUT_DIR / 'eval_report.md'}`
"""

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "eval_scores.json", "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)
    with open(OUTPUT_DIR / "eval_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"\n{'='*50}")
    logger.info(f"评测完成！准确率: {accuracy_rate:.1f}% ({correct}/{total})")
    logger.info(f"平均综合分: {avg_overall:.2f}")
    logger.info(f"报告: {OUTPUT_DIR / 'eval_report.md'}")
    logger.info(f"详细: {OUTPUT_DIR / 'eval_scores.json'}")


if __name__ == "__main__":
    asyncio.run(main())
