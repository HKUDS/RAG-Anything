from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from lightrag.llm.openai import openai_complete_if_cache

from src.config import ENV
from src.prompts import (
    LLM_STRICT_TOPK_SAFE_MERGE_USER_PROMPT,
    LLM_STRICT_TOPK_SYSTEM_PROMPT,
    LLM_STRICT_TOPK_USER_PROMPT,
)

logger = logging.getLogger("OpenAIPruning")


def _strip_json_fence(text: str) -> str:
    text = str(text).strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


@dataclass
class OpenAIPruningClient:
    api_key: str
    model: str

    def __post_init__(self):
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is missing.")
        if not self.model:
            raise RuntimeError("OpenAI pruning model is missing.")

    async def _complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = await openai_complete_if_cache(
            model=self.model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=self.api_key,
            base_url=None,
            timeout=300,
        )
        try:
            return json.loads(_strip_json_fence(response))
        except Exception as exc:
            logger.error("OpenAI pruning JSON parse failed: %s", exc)
            logger.error("Raw response: %s", response)
            raise

    async def select_nodes(
        self,
        *,
        candidate_json: str,
        top_k: int,
        allow_merge: bool,
    ) -> dict[str, Any]:
        user_prompt = (
            LLM_STRICT_TOPK_SAFE_MERGE_USER_PROMPT
            if allow_merge
            else LLM_STRICT_TOPK_USER_PROMPT
        ).format(top_k=top_k, candidate_json=candidate_json)
        return await self._complete_json(
            system_prompt=LLM_STRICT_TOPK_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )


def build_openai_pruning_client(model_name: str | None = None) -> OpenAIPruningClient:
    model = model_name or ENV.openai_eval_model or ENV.openai_llm or "gpt-4o-mini"
    return OpenAIPruningClient(api_key=ENV.openai_api_key, model=model)
