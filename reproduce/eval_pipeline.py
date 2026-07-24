#!/usr/bin/env python
"""
新能源知识库检索准确度 — 一键评测流水线

用法：
    python reproduce/eval_pipeline.py

前置条件：
    - 服务器已启动（python server.py）
    - .env 中已配置 API_KEY
    - 新能源 KB 已存在且已入库文档

流程：
    ① 从 reproduce/data/新能源_qa.jsonl 读取问答对
    ② 通过 Agent API 逐条查询（支持多模式：hybrid / rrf / mix / naive）
    ③ 汇总为 qa_results_*.json
    ④ 调用 LLMAnswerEvaluator 自动评分
    ⑤ 输出评测报告到 evaluation_energy/
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)

# ── 配置 ──────────────────────────────────────────────
BASE_URL = "http://localhost:8001/api"
QA_FILE = Path(__file__).parent / "data" / "新能源_qa.jsonl"
OUTPUT_DIR = Path(__file__).parent.parent / "evaluation_energy"
USERNAME = "admin"
PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "Qwe980142341")

# 评测模式列表（可单选或多选对比）
QUERY_MODES = ["hybrid"]  # hybrid / rrf / mix / naive

# 每问超时（秒）
QUERY_TIMEOUT = 120

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("eval_pipeline")


def login() -> str:
    """获取认证 token"""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def query_agent_stream(token: str, question: str, mode: str = "hybrid") -> dict:
    """
    通过 Agent 流式 API 查询，收集完整回答。
    返回 {"answer": str, "citations": list, "error": str|None}
    """
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "query": question,
        "thread_id": "",
        "mode": mode,
        "vlm_enhanced": False,
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/agents/default/query/stream",
            json=payload,
            headers=headers,
            timeout=QUERY_TIMEOUT,
            stream=True,
        )
        resp.raise_for_status()

        full_answer = ""
        citations = []
        error = None

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str:
                continue
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            if event_type == "token":
                full_answer += event.get("content", "")
            elif event_type == "done":
                citations = event.get("citations", [])
            elif event_type == "error":
                error = event.get("message", str(event))

        if error:
            return {"answer": full_answer, "citations": citations, "error": error, "success": False}
        return {"answer": full_answer, "citations": citations, "error": None, "success": True}

    except requests.Timeout:
        return {"answer": "", "citations": [], "error": f"Timeout after {QUERY_TIMEOUT}s", "success": False}
    except Exception as e:
        return {"answer": "", "citations": [], "error": str(e), "success": False}


def load_qa_pairs(filepath: Path) -> list[dict]:
    """读取 QA JSONL 文件"""
    pairs = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pairs.append(json.loads(line))
    logger.info(f"Loaded {len(pairs)} QA pairs from {filepath}")
    return pairs


async def main():
    logger.info("=" * 60)
    logger.info("🚀 新能源知识库检索评测流水线启动")
    logger.info("=" * 60)

    # ① 登录
    logger.info("[Step 1/4] 登录服务器...")
    try:
        token = login()
        logger.info("登录成功")
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return

    # ② 加载问答对
    logger.info("[Step 2/4] 加载测试问题集...")
    qa_pairs = load_qa_pairs(QA_FILE)
    if not qa_pairs:
        logger.error("QA 文件为空")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ③ 逐模式评测
    all_result_files = []
    for mode in QUERY_MODES:
        logger.info(f"\n{'─'*40}")
        logger.info(f"[Step 3/4] 模式=[{mode}] 批量提问（共 {len(qa_pairs)} 题）...")

        mode_results = []
        success_count = 0
        fail_count = 0

        for i, qa in enumerate(qa_pairs, 1):
            question = qa["question"]
            expected_answer = qa.get("answer", "")
            logger.info(f"  [{i}/{len(qa_pairs)}] {question[:50]}...")

            result = query_agent_stream(token, question, mode=mode)

            mode_results.append({
                "doc_id": "新能源电气技术",
                "question": question,
                "expected_answer": expected_answer,
                "generated_answer": result["answer"],
                "citations": result.get("citations", []),
                "method": mode,
                "success": result["success"],
                "error": result.get("error"),
                "timestamp": datetime.now().isoformat(),
            })

            if result["success"]:
                success_count += 1
                preview = result["answer"][:80].replace("\n", " ")
                logger.info(f"    ✅ {preview}...")
            else:
                fail_count += 1
                logger.warning(f"    ❌ {result['error']}")

        # 保存该模式的结果
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = OUTPUT_DIR / f"qa_results_{mode}_{ts}.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(mode_results, f, ensure_ascii=False, indent=2)
        all_result_files.append(str(result_file))

        logger.info(f"  模式 [{mode}] 完成: {success_count} 成功, {fail_count} 失败")
        logger.info(f"  结果已保存: {result_file}")

    # ④ 调用评测器打分
    logger.info(f"\n{'─'*40}")
    logger.info("[Step 4/4] LLM 自动评测打分...")

    from reproduce.llm_answer_evaluator import LLMAnswerEvaluator, EvaluationConfig
    import argparse

    class EvalArgs:
        pass

    eval_args = EvalArgs()
    eval_args.rag_results_files = all_result_files
    eval_args.rag_results_file = None
    eval_args.output_dir = str(OUTPUT_DIR)
    eval_args.api_key = os.getenv("LLM_BINDING_API_KEY")
    eval_args.base_url = os.getenv("LLM_BINDING_HOST")
    eval_args.evaluation_type = "comprehensive"
    eval_args.max_evaluations = None
    eval_args.qa_data_dir = None

    if not eval_args.api_key:
        logger.error("LLM_BINDING_API_KEY 未配置，跳过自动评测")
        logger.info("可手动运行: python reproduce/llm_answer_evaluator.py -rf <结果文件> -o evaluation_energy")
        return

    config = EvaluationConfig(eval_args)
    evaluator = LLMAnswerEvaluator(config)

    if len(all_result_files) > 1:
        await evaluator.evaluate_multiple_results(
            all_result_files,
            config.evaluation_type,
            config.max_evaluations,
        )
    else:
        # 适配 QA 格式为 evaluator 期望的格式
        # evaluator.evaluate_rag_results 期望的是原始的 RAG 结果格式，
        # 我们需要使用 evaluate_qa_files 方法
        await evaluator.evaluate_qa_files(
            all_result_files,
            config.evaluation_type,
            config.max_evaluations,
        )

    # ⑤ 输出汇总
    logger.info("\n" + "=" * 60)
    logger.info("✅ 评测完成！")
    logger.info(f"📁 结果目录: {OUTPUT_DIR.absolute()}")
    logger.info(f"📊 评测报告: {OUTPUT_DIR / 'llm_evaluation_report.md'}")
    logger.info(f"📋 详细数据: {OUTPUT_DIR / 'llm_evaluation_results.json'}")
    logger.info(f"📈 CSV 概要: {OUTPUT_DIR / 'llm_evaluation_summary.csv'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
