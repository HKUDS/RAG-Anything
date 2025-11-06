#!/usr/bin/env python3
"""
SPIQA Test-B 简化生成式任务评估
使用适合生成式任务的评估指标
"""

import json
from typing import Dict, List, Any
import re
from collections import defaultdict


def load_testb_dataset():
    """加载 Test-B 数据集"""
    with open("test-B/SPIQA_testB.json", "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_text_quality_metrics(text: str) -> Dict[str, float]:
    """计算文本质量指标"""
    if not text:
        return {
            "length_score": 0.0,
            "sentence_count": 0,
            "avg_sentence_length": 0.0,
            "word_diversity": 0.0,
            "readability_score": 0.0,
        }

    # 基本统计
    words = text.split()
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 长度分数（基于理想长度范围）
    text_length = len(text)
    if text_length < 50:
        length_score = text_length / 50
    elif text_length > 500:
        length_score = 500 / text_length
    else:
        length_score = 1.0

    # 句子数量
    sentence_count = len(sentences)

    # 平均句子长度
    avg_sentence_length = sum(len(s.split()) for s in sentences) / max(
        sentence_count, 1
    )

    # 词汇多样性（唯一词/总词数）
    unique_words = len(set(word.lower() for word in words))
    total_words = len(words)
    word_diversity = unique_words / max(total_words, 1)

    # 可读性分数（基于句子长度和词汇复杂度）
    ideal_sentence_length = 15  # 理想句子长度
    sentence_length_score = (
        1.0 - abs(avg_sentence_length - ideal_sentence_length) / ideal_sentence_length
    )
    readability_score = (sentence_length_score + word_diversity) / 2

    return {
        "length_score": length_score,
        "sentence_count": sentence_count,
        "avg_sentence_length": avg_sentence_length,
        "word_diversity": word_diversity,
        "readability_score": readability_score,
    }


def evaluate_question_answer_pair(
    question: str, question_type: str, evidence_info: List[Dict]
) -> Dict[str, Any]:
    """评估单个问题-答案对"""

    # 模拟生成答案（实际应用中这里会调用 RAG 系统）
    # 这里我们基于问题类型和证据信息生成模拟答案

    if "Shallow" in question_type:
        # 浅层问题：生成简短、直接的答案
        simulated_answer = f"Based on the evidence, {question.lower().replace('?', '')} can be answered by examining the provided context and rationale."
    elif "Deep" in question_type or "Complex" in question_type:
        # 深层问题：生成详细、分析性的答案
        simulated_answer = f"This is a complex question that requires detailed analysis. {question} involves multiple aspects that need to be considered: {', '.join([evid.get('rationale', '')[:50] for evid in evidence_info[:2]])}..."
    elif "Testing" in question_type:
        # 测试问题：生成具体、可验证的答案
        simulated_answer = f"The answer to {question.lower().replace('?', '')} can be determined from the experimental results and data presented in the evidence."
    else:
        simulated_answer = f"To answer {question.lower().replace('?', '')}, we need to analyze the provided evidence and context."

    # 模拟证据提取
    simulated_evidence = []
    for evid in evidence_info:
        context = evid.get("context", "")
        rationale = evid.get("rationale", "")
        if context:
            simulated_evidence.append(f"Context: {context[:100]}...")
        if rationale:
            simulated_evidence.append(f"Rationale: {rationale[:100]}...")

    # 评估答案质量
    answer_metrics = calculate_text_quality_metrics(simulated_answer)

    # 评估证据质量
    evidence_metrics = {
        "evidence_count": len(simulated_evidence),
        "evidence_coverage": min(
            1.0, len(simulated_evidence) / max(len(evidence_info), 1)
        ),
        "evidence_relevance": 0.8,  # 模拟相关性分数
    }

    # 计算综合分数
    overall_score = (
        answer_metrics["readability_score"] * 0.3
        + answer_metrics["length_score"] * 0.2
        + evidence_metrics["evidence_coverage"] * 0.3
        + evidence_metrics["evidence_relevance"] * 0.2
    )

    return {
        "question": question,
        "question_type": question_type,
        "simulated_answer": simulated_answer,
        "simulated_evidence": simulated_evidence,
        "answer_metrics": answer_metrics,
        "evidence_metrics": evidence_metrics,
        "overall_score": overall_score,
    }


def run_testb_simple_evaluation():
    """运行 Test-B 简化评估"""
    print("🚀 开始 SPIQA Test-B 生成式任务简化评估...")

    # 加载数据集
    print("📥 加载 Test-B 数据集...")
    dataset = load_testb_dataset()
    print(f"✅ 加载完成：{len(dataset)} 篇论文")

    results = []
    total_questions = 0

    # 统计信息
    stats = defaultdict(int)
    type_performance = defaultdict(list)

    print("🔍 开始处理问题...")

    for paper_id, paper_data in dataset.items():
        questions = paper_data.get("question", [])
        question_types = paper_data.get("question_type", [])
        evidential_info = paper_data.get("evidential_info", [])

        print(f"📄 处理论文 {paper_id}，共 {len(questions)} 个问题")

        for i, (question, qtype, evidence) in enumerate(
            zip(questions, question_types, evidential_info)
        ):
            total_questions += 1
            stats[qtype] += 1

            print(f"  ❓ 问题 {i+1}: {question[:50]}...")

            try:
                # 评估问题-答案对
                result = evaluate_question_answer_pair(question, qtype, evidence)
                result["paper_id"] = paper_id
                result["question_index"] = i

                results.append(result)
                type_performance[qtype].append(result["overall_score"])

                print(f"  ✅ 完成，分数: {result['overall_score']:.3f}")

            except Exception as e:
                print(f"  ❌ 处理失败: {e}")
                results.append(
                    {
                        "paper_id": paper_id,
                        "question_index": i,
                        "question": question,
                        "question_type": qtype,
                        "error": str(e),
                        "overall_score": 0.0,
                    }
                )

    # 计算统计信息
    print("\n📊 计算统计信息...")

    # 按问题类型计算性能
    type_stats = {}
    for qtype, scores in type_performance.items():
        if scores:
            type_stats[qtype] = {
                "count": len(scores),
                "average_score": sum(scores) / len(scores),
                "median_score": sorted(scores)[len(scores) // 2],
                "min_score": min(scores),
                "max_score": max(scores),
            }

    # 计算总体统计
    all_scores = [r["overall_score"] for r in results if "overall_score" in r]
    overall_stats = {
        "total_questions": total_questions,
        "successful_evaluations": len(all_scores),
        "overall_average_score": sum(all_scores) / len(all_scores)
        if all_scores
        else 0.0,
        "question_type_distribution": dict(stats),
        "type_performance": type_stats,
    }

    # 保存结果
    output_file = "spiqa_testb_simple_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {"results": results, "statistics": overall_stats},
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"✅ 结果已保存到: {output_file}")

    # 打印总结
    print("\n📈 评估总结:")
    print(f"总问题数: {total_questions}")
    print(f"成功评估: {len(all_scores)}")
    print(f"整体平均分数: {overall_stats['overall_average_score']:.3f}")

    print("\n📊 按问题类型统计:")
    for qtype, stats in type_stats.items():
        print(f"  {qtype}:")
        print(f"    数量: {stats['count']}")
        print(f"    平均分数: {stats['average_score']:.3f}")
        print(f"    中位数: {stats['median_score']:.3f}")
        print(f"    范围: {stats['min_score']:.3f} - {stats['max_score']:.3f}")

    return results, overall_stats


if __name__ == "__main__":
    results, stats = run_testb_simple_evaluation()
