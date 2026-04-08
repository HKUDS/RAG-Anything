from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from src.config import ENV

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalRerankerConfig:
    name: str
    model_name_or_path: str
    device: str | None
    use_fp16: bool
    batch_size: int
    max_length: int
    cache_dir: str | None = None


class LocalHFSequenceRerankerService:
    def __init__(self, config: LocalRerankerConfig):
        self.config = config
        self._tokenizer = None
        self._model = None
        self._resolved_device = None
        self._init_lock = threading.Lock()

    def _resolve_device(self) -> str:
        requested = (self.config.device or "").strip().lower()
        if requested.startswith("cuda"):
            if torch.cuda.is_available():
                return self.config.device or "cuda"
            logger.warning(
                "CUDA reranker was requested but CUDA is unavailable. Falling back to CPU."
            )
        return "cpu"

    def _ensure_model(self):
        if self._model is not None and self._tokenizer is not None:
            return self._tokenizer, self._model, self._resolved_device

        with self._init_lock:
            if self._model is None or self._tokenizer is None:
                device = self._resolve_device()
                torch_dtype = None
                if device.startswith("cuda") and self.config.use_fp16:
                    torch_dtype = torch.float16

                logger.info(
                    "Loading reranker model %s on %s",
                    self.config.model_name_or_path,
                    device,
                )
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.config.model_name_or_path,
                    cache_dir=self.config.cache_dir,
                    trust_remote_code=True,
                )
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    self.config.model_name_or_path,
                    cache_dir=self.config.cache_dir,
                    torch_dtype=torch_dtype,
                    trust_remote_code=True,
                )
                self._model.eval()
                self._model.to(device)
                self._resolved_device = device

        return self._tokenizer, self._model, self._resolved_device

    def rerank_sync(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, float]]:
        if not documents:
            return []

        tokenizer, model, device = self._ensure_model()
        batch_size = max(1, self.config.batch_size)

        indexed_scores: list[dict[str, float]] = []
        with torch.no_grad():
            for start in range(0, len(documents), batch_size):
                batch_docs = [str(doc or "") for doc in documents[start : start + batch_size]]
                queries = [str(query or "")] * len(batch_docs)
                encoded = tokenizer(
                    queries,
                    batch_docs,
                    padding=True,
                    truncation=True,
                    max_length=self.config.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(device) for key, value in encoded.items()}
                logits = model(**encoded).logits.view(-1).float()
                scores = torch.sigmoid(logits).cpu().tolist()

                for offset, score in enumerate(scores):
                    indexed_scores.append(
                        {
                            "index": start + offset,
                            "relevance_score": float(score),
                        }
                    )

        indexed_scores.sort(key=lambda item: item["relevance_score"], reverse=True)
        return indexed_scores[:top_n] if top_n else indexed_scores

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int | None = None,
        **_: Any,
    ) -> list[dict[str, float]]:
        return await asyncio.to_thread(
            self.rerank_sync,
            query=query,
            documents=documents,
            top_n=top_n,
        )


def _canonical_reranker_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = str(name).strip().lower()
    aliases = {
        "baai/bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3",
        "bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3",
    }
    return aliases.get(normalized)


def _build_local_reranker_config(name: str) -> LocalRerankerConfig:
    if name != "BAAI/bge-reranker-v2-m3":
        raise ValueError(f"Unsupported reranker: {name}")

    return LocalRerankerConfig(
        name=name,
        model_name_or_path=ENV.reranker_model_name or name,
        device=ENV.reranker_device or None,
        use_fp16=ENV.reranker_use_fp16,
        batch_size=ENV.reranker_batch_size,
        max_length=ENV.reranker_max_length,
        cache_dir=ENV.reranker_cache_dir,
    )


@lru_cache(maxsize=4)
def _get_service(name: str) -> LocalHFSequenceRerankerService:
    return LocalHFSequenceRerankerService(_build_local_reranker_config(name))


def get_rerank_model_func(reranker_name: str | None) -> Callable[..., Any] | None:
    canonical_name = _canonical_reranker_name(reranker_name)
    if canonical_name is None:
        return None

    service = _get_service(canonical_name)

    async def rerank_model_func(query: str, documents: list[str], top_n: int | None = None, **kwargs):
        return await service.rerank(query=query, documents=documents, top_n=top_n, **kwargs)

    return rerank_model_func
