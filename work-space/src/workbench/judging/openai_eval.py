from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from lightrag.llm.openai import openai_complete_if_cache

from src.config import ENV

logger = logging.getLogger("OpenAIQAEval")


def _strip_json_fence(text: str) -> str:
    text = str(text).strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def _loads_json(text: str) -> Any:
    cleaned = _strip_json_fence(text)
    return json.loads(cleaned)


@dataclass
class OpenAIJudgeClient:
    api_key: str
    model: str

    def __post_init__(self):
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is missing.")
        if not self.model:
            raise RuntimeError("OpenAI evaluation model is missing.")

    async def _complete_json(self, system_prompt: str, user_prompt: str) -> Any:
        response = await openai_complete_if_cache(
            model=self.model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=self.api_key,
            base_url=None,
            timeout=300,
        )
        try:
            return _loads_json(response)
        except Exception as exc:
            logger.error("OpenAI JSON parse failed: %s", exc)
            logger.error("Raw response: %s", response)
            raise

    async def generate_gold_questions(
        self,
        *,
        doc_name: str,
        reference_text: str,
        num_questions: int = 10,
    ) -> Dict[str, Any]:
        system_prompt = (
            "You are a rigorous medical benchmark designer. "
            "Create document-grounded evaluation questions only from the provided reference content. "
            "Do not invent facts outside the reference text."
        )
        user_prompt = f"""
Generate exactly {num_questions} medical QA benchmark items for the document below.

Requirements:
- Use only the provided reference content.
- Questions must range from easy to hard.
- Mix question types: direct fact, comparison, table/figure reading, synthesis, reasoning.
- Every question must be answerable from the reference content.
- Keep answers concise but complete.
- Provide 1 to 3 evidence snippets copied or near-copied from the reference content.
- Provide 2 to 6 evidence keywords that should appear in retrieved evidence.
- Difficulty must be one of: easy, medium, hard.
- question_type must be one of: factoid, comparison, multimodal, synthesis, reasoning.

Return strict JSON with this shape:
{{
  "document_name": "{doc_name}",
  "questions": [
    {{
      "question_id": "q01",
      "difficulty": "easy",
      "question_type": "factoid",
      "question": "...",
      "gold_answer": "...",
      "evidence_snippets": ["..."],
      "evidence_keywords": ["...", "..."]
    }}
  ]
}}

Reference content:
{reference_text}
"""
        data = await self._complete_json(system_prompt, user_prompt)
        if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
            raise RuntimeError("OpenAI gold-question generation returned invalid schema.")
        return data

    async def judge_answer(
        self,
        *,
        question: str,
        gold_answer: str,
        evidence_snippets: List[str],
        evidence_keywords: List[str],
        retrieved_context: str,
        model_answer: str,
    ) -> Dict[str, Any]:
        system_prompt = (
            "You are a strict evaluator for medical RAG systems. "
            "Judge answer correctness against the gold answer and evidence, "
            "and judge groundedness only against the retrieved context."
        )
        user_prompt = f"""
Evaluate the following RAG answer.

Scoring rubric:
- correctness: integer 0-4
- groundedness: integer 0-4
- completeness: integer 0-4
- evidence_recall_at_10: 0 or 1
- unsupported_claim: 0 or 1

Definitions:
- correctness: whether the final answer is factually correct relative to the gold answer.
- groundedness: whether the answer's main claims are supported by the retrieved context.
- completeness: whether the answer covers the key points in the gold answer.
- evidence_recall_at_10: 1 if the retrieved context clearly contains the required gold evidence; else 0.
- unsupported_claim: 1 if the answer makes a medically meaningful claim not supported by the retrieved context.

Return strict JSON:
{{
  "correctness": 0,
  "groundedness": 0,
  "completeness": 0,
  "evidence_recall_at_10": 0,
  "unsupported_claim": 0,
  "reasoning": "short explanation"
}}

Question:
{question}

Gold answer:
{gold_answer}

Gold evidence snippets:
{json.dumps(evidence_snippets, ensure_ascii=False)}

Gold evidence keywords:
{json.dumps(evidence_keywords, ensure_ascii=False)}

Retrieved context:
{retrieved_context}

Model answer:
{model_answer}
"""
        data = await self._complete_json(system_prompt, user_prompt)
        required = {
            "correctness",
            "groundedness",
            "completeness",
            "evidence_recall_at_10",
            "unsupported_claim",
        }
        if not isinstance(data, dict) or not required.issubset(set(data.keys())):
            raise RuntimeError("OpenAI judge returned invalid schema.")
        return data


def build_openai_judge_client() -> OpenAIJudgeClient:
    model = getattr(ENV, "openai_eval_model", None) or ENV.openai_llm or "gpt-4o-mini"
    return OpenAIJudgeClient(api_key=ENV.openai_api_key, model=model)
