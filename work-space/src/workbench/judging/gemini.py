import json
import logging

from google import genai
from google.genai import types

from src.config import ENV

logger = logging.getLogger("Evaluator")


class GeminiEvaluator:
    def __init__(self):
        if not ENV.google_api_key:
            raise ValueError("GOOGLE_API_KEY is missing in .env")
        self.client = genai.Client(api_key=ENV.google_api_key)
        self.model_name = "gemini-2.5-flash"

    def generate_gold_questions(self, context_text: str, num_questions=5):
        prompt = f"""
        You are a Medical Professor. Based on the following text, generate {num_questions} diverse QA pairs to test a RAG system.

        Criteria:
        1. General: Ask about main purpose.
        2. Specific: Ask about numbers, metrics, entities.
        3. Reasoning: Ask about relationships.

        Output JSON format (Array of Objects):
        [
            {{"question": "...", "answer": "...", "type": "General"}},
            {{"question": "...", "answer": "...", "type": "Specific"}}
        ]

        Text content:
        {context_text[:15000]} ... (truncated)
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(response.text)
        except Exception as exc:
            logger.error("Gemini generation error: %s", exc)
            return []

    def evaluate_answer(self, question, gold_answer, rag_answer):
        prompt = f"""
        Act as an impartial judge. Evaluate the AI generated answer based on the Ground Truth.

        Question: {question}
        Ground Truth: {gold_answer}
        AI Answer: {rag_answer}

        Score the AI Answer on two metrics (0-10):
        1. Faithfulness: Does it contradict the ground truth?
        2. Completeness: Does it miss key details?

        Output JSON:
        {{
            "faithfulness_score": 0-10,
            "completeness_score": 0-10,
            "reasoning": "Short explanation"
        }}
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(response.text)
        except Exception as exc:
            logger.error("Evaluation error: %s", exc)
            return {"faithfulness_score": 0, "completeness_score": 0, "reasoning": "Error"}
