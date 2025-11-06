#!/usr/bin/env python3
"""
SPIQA Test-A 测试脚本
基于test_spiqa_comprehensive.py修改
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import logging
import base64
from difflib import SequenceMatcher

import asyncio
import urllib.request
import urllib.error
import json
import os

# ------------------------------
# Ollama HTTP helpers
# ------------------------------

def _http_post_json(url: str, payload: dict, timeout: int = 240) -> dict:
    """Minimal helper to POST JSON without external deps."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} error from {url}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach {url}: {e}")

def _http_get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} error from {url}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach {url}: {e}")

def _list_ollama_models(host: str) -> List[str]:
    tags_url = f"{host.rstrip('/')}/api/tags"
    data = _http_get_json(tags_url)
    models = data.get("models", [])
    return [m.get("name") for m in models if m.get("name")]

def _ensure_vision_model_or_exit(image_root_exists: bool) -> Optional[str]:
    """Fail fast if image_root exists but no vision model is available.

    Returns the chosen vision model name if available; otherwise exits.
    """
    vision_model = os.getenv("VISION_MODEL", "").strip()
    host = os.getenv("LLM_BINDING_HOST", "http://localhost:11434").rstrip("/")

    # If no images at all, allow text-only mode
    if not image_root_exists:
        return vision_model or None

    # Require a vision model when images exist
    if not vision_model:
        print("❌ 未设置 VISION_MODEL，但检测到需要处理图片的问题。")
        print("👉 请先安装并设置视觉模型后重试，例如：")
        print("   ollama pull qwen2.5-vl:7b-instruct")
        print("   export VISION_MODEL=qwen2.5-vl:7b-instruct")
        raise SystemExit(1)

    try:
        names = _list_ollama_models(host)
    except Exception as exc:
        print(f"❌ 无法连接 Ollama 获取模型列表: {exc}")
        raise SystemExit(1)

    if vision_model not in names:
        print(f"❌ 视觉模型未安装: {vision_model}")
        print("👉 请先安装：")
        print(f"   ollama pull {vision_model}")
        print("或选择已安装模型，例如 qwen2.5-vl:7b-instruct / llama3.2-vision:11b / llava:7b")
        raise SystemExit(1)

    return vision_model

def build_azure_openai_vision_func():
    """Create a vision function that talks to Azure OpenAI (gpt-4o/4o-mini) via HTTP."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    deployment = os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT", "")

    if not (endpoint and api_key and deployment):
        return None

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    async def vision_func(prompt=None, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs):
        # Build messages in Azure schema
        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            user_content = []
            if prompt:
                user_content.append({"type": "text", "text": prompt})
            if image_data:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                })
            messages.append({"role": "user", "content": user_content})

        payload = {
            "messages": messages,
            "temperature": 0.0,
            "top_p": 0.1,
            "max_tokens": 512
        }

        import urllib.request, json as _json
        req = urllib.request.Request(url, data=_json.dumps(payload).encode("utf-8"),
                                     headers={
                                         "Content-Type": "application/json",
                                         "api-key": api_key
                                     })
        try:
            def _do():
                with urllib.request.urlopen(req, timeout=240) as resp:
                    return _json.loads(resp.read().decode("utf-8"))
            resp = await asyncio.to_thread(_do)
            choices = resp.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
        except Exception as e:
            print(f"Azure Vision 调用失败: {e}")
            return ""

    return vision_func

# ------------------------------
# Helpers for evaluation / parsing
# ------------------------------

_LETTER_PATTERN = re.compile(r"\b([A-E])\b", re.IGNORECASE)

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def extract_option_letter(text: str) -> Optional[str]:
    if not text:
        return None
    m = _LETTER_PATTERN.search(text.strip())
    return m.group(1).upper() if m else None

def detect_is_multiple_choice(question_text: str) -> bool:
    if not question_text:
        return False
    # 常见 MC 格式：A) / B) / C) 或 A. / B. / C.
    return bool(re.search(r"\b[A-E]\s*[\)\.]", question_text))

def build_ollama_llm_func():
    """Create an LLM function that talks to Ollama via HTTP."""
    host = os.getenv("LLM_BINDING_HOST", "http://localhost:11434").rstrip("/")
    model = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct").strip()
    url = f"{host}/api/generate"
    timeout = 240

    async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        full_prompt = ""
        if system_prompt:
            full_prompt += f"System: {system_prompt}\n\n"
        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                full_prompt += f"System: {content}\n\n"
            elif role == "user":
                full_prompt += f"User: {content}\n\n"
            elif role == "assistant":
                full_prompt += f"Assistant: {content}\n\n"
        
        full_prompt += f"User: {prompt}\n\nAssistant:"
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "max_tokens": 2048
            }
        }
        
        try:
            response = _http_post_json(url, payload, timeout)
            return response.get("response", "").strip()
        except Exception as e:
            print(f"LLM调用失败: {e}")
            return ""

    return llm_func

def build_ollama_vision_func():
    """Create a vision function that talks to Ollama via HTTP."""
    host = os.getenv("LLM_BINDING_HOST", "http://localhost:11434").rstrip("/")
    model = os.getenv("VISION_MODEL", "llava:7b").strip()
    url = f"{host}/api/generate"
    timeout = 240

    async def vision_func(prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs):
        if messages:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0, "top_p": 0.1}
            }
        elif image_data:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]
            })
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0, "top_p": 0.1}
            }
        else:
            # Fallback to text-only
            full_prompt = ""
            if system_prompt:
                full_prompt += f"System: {system_prompt}\n\n"
            full_prompt += f"User: {prompt}\n\nAssistant:"
            payload = {
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.0, "top_p": 0.1}
            }

        try:
            resp = await asyncio.to_thread(_http_post_json, url, payload, timeout)
            return resp.get("response", "").strip()
        except Exception as e:
            print(f"Vision调用失败: {e}")
            return ""

    return vision_func

class ComprehensiveSPIQATester:
    def __init__(self, image_root: str = ""):
        self.image_root = image_root
        self.llm_func = build_ollama_llm_func()
        azure_v = build_azure_openai_vision_func()
        self.vision_func = azure_v if azure_v else build_ollama_vision_func()
        self.vision_model_name = os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT", "").strip() or os.getenv("VISION_MODEL", "").strip() or None
        
    def load_images_for_paper(self, paper_id: str, figures: Dict[str, Any]) -> Dict[str, str]:
        """加载论文的所有图片"""
        images = {}
        
        for fig_id, fig_info in figures.items():
            if self.image_root:
                # 图片路径应该是：image_root/paper_id/fig_id
                image_path = os.path.join(self.image_root, paper_id, fig_id)
                if os.path.exists(image_path):
                    try:
                        with open(image_path, 'rb') as f:
                            image_data = f.read()
                            images[fig_id] = base64.b64encode(image_data).decode('utf-8')
                            print(f"成功加载图片: {fig_id}")
                    except Exception as e:
                        print(f"加载图片失败 {fig_id}: {e}")
                else:
                    print(f"图片文件不存在: {image_path}")
        
        return images
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度"""
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    
    def calculate_phrase_overlap(self, text1: str, text2: str) -> float:
        """计算短语重叠度"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    async def process_question(self, paper_id: str, question_data: Dict[str, Any], 
                             question_index: int, images: Dict[str, str]) -> Dict[str, Any]:
        """处理单个问题"""
        question = question_data.get("question", "")
        answer = question_data.get("answer", "")
        explanation = question_data.get("explanation", "")
        reference = question_data.get("reference", "")
        
        # 构建上下文
        context_parts = []
        
        # 添加问题
        context_parts.append(f"问题: {question}")
        
        # 添加相关图片信息
        if reference and reference in images:
            context_parts.append(f"相关图片: {reference} (已加载)")
            print(f"使用图片: {reference}")
        elif reference:
            context_parts.append(f"相关图片: {reference} (未找到)")
            print(f"图片未找到: {reference}")
        
        # 构建系统提示（更严格的指令，对图表/表格读取更敏感）
        system_prompt = (
            "你是一个严格的科学图表阅读助手。\n"
            "- 如果题目为选择题，只输出最终选项字母（A/B/C/D/E），不要多余文本。\n"
            "- 如果为开放题，直接输出简洁的最终数值/结论，保留单位。\n"
            "- 优先依据提供的图片（图、表）读取数值与趋势；必要时才参考题干文字。\n"
            "- 数值题避免主观描述，直接给出结果；若信息不足，回答“无法判断”。"
        )
        
        # 构建用户提示（加入“只输出答案”提醒）
        user_prompt = "\n".join(context_parts + ["\n仅输出答案。"])
        
        try:
            # Prefer vision model when reference image is present and a vision model is configured
            use_image = bool(reference and reference in images and self.vision_model_name)
            is_mc = detect_is_multiple_choice(question)
            if use_image:
                # Step 1: structured extraction with VLM (JSON)
                image_b64 = images[reference]
                mime = "image/png" if reference.lower().endswith(".png") else "image/jpeg"
                extraction_system = (
                    "你是图表/表格读取器。严格输出 JSON，不要额外文本。字段: "
                    "{caption:string, key_values:object, trends:string, cells:object, units:string, final_answer:string}。"
                )
                extraction_user = (
                    user_prompt + "\n请先从图片中抽取关键信息并用 JSON 返回。如果能直接确定答案，请放在 final_answer。"
                )
                extract_msgs = [
                    {"role": "system", "content": extraction_system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": extraction_user},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        ],
                    },
                ]
                extraction = await self.vision_func(prompt=None, messages=extract_msgs)
                parsed_extract = None
                try:
                    parsed_extract = json.loads(extraction)
                except Exception:
                    parsed_extract = None

                # Step 2: if final_answer not present, reason with LLM using extracted JSON
                if parsed_extract and isinstance(parsed_extract, dict) and parsed_extract.get("final_answer"):
                    response = str(parsed_extract.get("final_answer"))
                else:
                    reasoning_prompt = (
                        f"已抽取的图表信息(JSON):\n{extraction}\n\n问题: {question}\n仅输出最终答案。"
                    )
                    response = await self.llm_func(reasoning_prompt, system_prompt=system_prompt)
            else:
                response = await self.llm_func(user_prompt, system_prompt=system_prompt)
            
            # 规范化与选择题字母抽取
            norm_pred = normalize_text(response)
            norm_gt = normalize_text(answer)
            pred_letter = extract_option_letter(response)
            gt_letter = extract_option_letter(answer)
            
            # 计算相似度
            similarity_score = self.calculate_similarity(norm_pred, norm_gt)
            phrase_overlap = self.calculate_phrase_overlap(norm_pred, norm_gt)
            
            # 判断是否正确（基于相似度阈值）
            is_correct = similarity_score >= 0.7
            # 对选择题优先用选项字母精确匹配
            if is_mc and pred_letter and gt_letter:
                is_correct = (pred_letter == gt_letter)
            
            result_obj = {
                "paper_id": paper_id,
                "question_index": question_index,
                "question": question,
                "ground_truth": answer,
                "predicted_answer": response,
                "explanation": explanation,
                "reference": reference,
                "evaluation": {
                    "is_correct": is_correct,
                    "similarity_score": similarity_score,
                    "phrase_overlap": phrase_overlap
                },
                "question_type": "multiple_choice" if is_mc else "open_ended",
                "parsed": {
                    "pred_letter": pred_letter,
                    "gt_letter": gt_letter
                }
            }
            if use_image:
                # 附加结构化抽取原文，便于调试与误差分析
                result_obj["vision_extraction"] = extraction if 'extraction' in locals() else ""
            return result_obj
            
        except Exception as e:
            return {
                "paper_id": paper_id,
                "question_index": question_index,
                "question": question,
                "ground_truth": answer,
                "error": str(e)
            }
    
    async def process_paper(self, paper_id: str, paper_content: Dict[str, Any]) -> List[Dict[str, Any]]:
        """处理单篇论文"""
        print(f"处理论文: {paper_id}")
        
        # 加载图片
        figures = paper_content.get("all_figures", {})
        images = self.load_images_for_paper(paper_id, figures)
        
        # 处理问题
        qa_data = paper_content.get("qa", [])
        results = []
        
        for i, question_data in enumerate(qa_data):
            print(f"  处理问题 {i+1}/{len(qa_data)}")
            result = await self.process_question(paper_id, question_data, i, images)
            results.append(result)
        
        return results

async def main():
    """主函数"""
    print("🚀 开始SPIQA Test-A测试...")
    
    # 加载数据集
    dataset_path = "dataset/test-A/SPIQA_testA.json"
    if not os.path.exists(dataset_path):
        print(f"❌ 数据集文件不存在: {dataset_path}")
        return
    
    with open(dataset_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"📊 总论文数: {len(data)}")
    
    # 创建测试器，并在有图片时进行视觉模型预检
    image_root_path = "dataset/test-A/SPIQA_testA_Images"
    image_root_exists = os.path.exists(image_root_path)
    _ensure_vision_model_or_exit(image_root_exists)

    image_root = image_root_path if image_root_exists else ""
    tester = ComprehensiveSPIQATester(image_root)
    
    # 处理所有论文
    all_results = {}
    processed_count = 0
    failed_count = 0
    correct_count = 0
    
    # 统计信息
    similarity_scores = []
    phrase_overlaps = []
    question_types = {}
    paper_stats = {}
    
    for paper_id, paper_content in data.items():
        print(f"\n🔬 处理论文: {paper_id}")
        
        try:
            paper_results = await tester.process_paper(paper_id, paper_content)
            
            paper_correct = 0
            paper_total = 0
            
            for res in paper_results:
                qid = f"{res['paper_id']}_q{res['question_index']}"
                all_results[qid] = res
                
                if "error" in res:
                    failed_count += 1
                else:
                    processed_count += 1
                    paper_total += 1
                    
                    # 收集统计信息
                    if "evaluation" in res:
                        evaluation = res["evaluation"]
                        similarity_scores.append(evaluation["similarity_score"])
                        phrase_overlaps.append(evaluation["phrase_overlap"])
                        
                        if evaluation["is_correct"]:
                            correct_count += 1
                            paper_correct += 1
                        
                        # 问题类型统计
                        q_type = res.get("question_type", "Unknown")
                        if q_type not in question_types:
                            question_types[q_type] = {"total": 0, "correct": 0}
                        question_types[q_type]["total"] += 1
                        if evaluation["is_correct"]:
                            question_types[q_type]["correct"] += 1
            
            paper_stats[paper_id] = {
                "total_questions": paper_total,
                "correct_questions": paper_correct,
                "accuracy": paper_correct / paper_total if paper_total > 0 else 0
            }
            
            # 保存中间结果
            with open("spiqa_testa_results.json", "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
            
            print(f"  ✅ 完成: {paper_correct}/{paper_total} 正确")
            
        except Exception as e:
            print(f"  ❌ 处理论文 {paper_id} 时出错: {e}")
            failed_count += 1
    
    # 计算最终统计
    overall_accuracy = correct_count / processed_count if processed_count > 0 else 0
    avg_similarity = sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0
    avg_phrase_overlap = sum(phrase_overlaps) / len(phrase_overlaps) if phrase_overlaps else 0
    
    print("\n" + "="*60)
    print("📈 Test-A 最终结果摘要")
    print("="*60)
    print(f"📊 总问题数: {processed_count + failed_count}")
    print(f"✅ 成功处理: {processed_count}")
    print(f"❌ 失败: {failed_count}")
    print(f"🎯 正确回答: {correct_count}")
    print(f"📈 总体准确率: {overall_accuracy:.3f} ({correct_count}/{processed_count})")
    print(f"📊 平均相似度: {avg_similarity:.3f}")
    print(f"📊 平均短语重叠: {avg_phrase_overlap:.3f}")
    
    print(f"\n📋 问题类型表现:")
    for q_type, stats in question_types.items():
        type_accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
        print(f"  {q_type}: {type_accuracy:.3f} ({stats['correct']}/{stats['total']})")
    
    # 保存最终结果
    output_file = "spiqa_testa_results_final.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\n💾 最终结果已保存到: {output_file}")

if __name__ == '__main__':
    asyncio.run(main())
