import inspect
import json
import logging
import re
from pathlib import Path
from typing import Any

from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig

from src.config import ENV
from src.workbench.experiments.pipeline.definitions import PIPELINE_EXPERIMENTS
from src.workbench.runtime import get_model_funcs

try:
    from lightrag import QueryParam
except Exception:  # pragma: no cover
    QueryParam = None

logger = logging.getLogger("QA_Engine")


QUALITY_FIRST_SYSTEM_PROMPT = (
    "You are a document-grounded QA assistant. "
    "Answer only from the retrieved evidence. "
    "Answer the user's question directly and briefly. "
    "Do not add headings, summaries, or extra background unless the question asks for them. "
    "Prefer precise facts, numbers, table values, and named entities when available. "
    "If the evidence is insufficient or ambiguous, say so explicitly instead of guessing. "
    "When multiple retrieved snippets disagree, state the conflict briefly and give the most supported answer."
)

CONTEXT_GROUNDED_USER_PROMPT = (
    "Use only the retrieved context below to answer the question.\n"
    "Output rules:\n"
    "- Start with the answer immediately.\n"
    "- Keep the answer as short as the question allows.\n"
    "- Do not add headings, overviews, summaries, or unrelated findings.\n"
    "- For name/list/which questions, return only the requested names or items.\n"
    "- For definition/why/how questions, use at most 2 concise paragraphs.\n"
    "- Do not use outside knowledge.\n"
    "- If the context is insufficient, say that explicitly.\n"
    "- Prefer precise wording grounded in the retrieved evidence.\n\n"
    "Question:\n{question}\n\n"
    "Retrieved Context:\n{context}"
)

CONTEXT_DISTILL_USER_PROMPT = (
    "Extract only the facts from the retrieved context that are directly needed to answer the question.\n"
    "Rules:\n"
    "- Keep exact names, benchmark titles, metrics, dates, and technical terms when present.\n"
    "- Ignore background, comparisons, methodology, and unrelated sections.\n"
    "- Output at most 6 short bullet points.\n"
    "- If the context does not explicitly support the answer, output exactly: INSUFFICIENT EVIDENCE\n\n"
    "Question:\n{question}\n\n"
    "Retrieved Context:\n{context}"
)


class RAGQueryEngine:
    def __init__(self, experiment_id: str):
        if experiment_id not in PIPELINE_EXPERIMENTS:
            raise ValueError(f"Unknown experiment_id: {experiment_id}")

        self.experiment_id = experiment_id
        self.exp_def = PIPELINE_EXPERIMENTS[experiment_id]
        self.exp_dir = Path(ENV.output_base_dir) / experiment_id
        self.storage_dir = self.exp_dir / "rag_storage"
        self.parser_name = self.exp_def.parser or ENV.parser
        self.parse_method = self.exp_def.parse_method or ENV.parse_method

        self.llm_f, _, self.embed_f = get_model_funcs(self.exp_def.provider)
        self.rag = None

    async def initialize(self):
        config = RAGAnythingConfig(
            working_dir=str(self.storage_dir),
            parser=self.parser_name,
            parse_method=self.parse_method,
        )

        self.embed_f = self._align_embedding_dim_with_storage(self.storage_dir, self.embed_f)

        self.rag = RAGAnything(
            config=config,
            llm_model_func=self.llm_f,
            embedding_func=self.embed_f,
            lightrag_kwargs=self.exp_def.lightrag_kwargs,
        )
        await self.rag._ensure_lightrag_initialized()

    async def query(self, question: str, mode: str | None = None):
        trace = await self.query_with_trace(question, mode=mode)
        return trace["answer"]

    def close(self) -> None:
        try:
            if self.rag is not None and hasattr(self.rag, "close"):
                self.rag.close()
        except Exception as exc:
            logger.warning("Failed to close RAGQueryEngine for %s: %s", self.experiment_id, exc)

    async def query_with_trace(self, question: str, mode: str | None = None) -> dict:
        if self.rag is None:
            await self.initialize()

        resolved_mode = mode or ENV.query_default_mode
        normalized_question = self._normalize_user_query(question)
        query_kwargs = self._build_quality_query_kwargs()

        logger.info(
            "Querying via core RAG retrieval: %s (normalized=%s, mode=%s, kwargs=%s)",
            question,
            normalized_question,
            resolved_mode,
            query_kwargs,
        )

        retrieved_context = await self._retrieve_core_context(
            normalized_question,
            mode=resolved_mode,
            query_kwargs=query_kwargs,
        )
        if retrieved_context:
            logger.info(
                "Using core retrieval context for grounded synthesis (context chars=%d)",
                len(retrieved_context),
            )
            distilled_context = await self._distill_core_context(
                normalized_question,
                retrieved_context,
            )
            answer = await self._answer_from_core_context(
                normalized_question,
                distilled_context or retrieved_context,
            )
            return {
                "question": question,
                "normalized_question": normalized_question,
                "mode": resolved_mode,
                "query_kwargs": query_kwargs,
                "retrieved_context": retrieved_context,
                "distilled_context": distilled_context or retrieved_context,
                "answer": str(answer).strip(),
                "fallback_used": False,
            }

        logger.warning(
            "Could not fetch core retrieval context directly for query '%s'. Falling back to LightRAG mode '%s'.",
            normalized_question,
            resolved_mode,
        )
        answer = await self.rag.aquery(
            normalized_question,
            mode=resolved_mode,
            system_prompt=QUALITY_FIRST_SYSTEM_PROMPT,
            **query_kwargs,
        )
        return {
            "question": question,
            "normalized_question": normalized_question,
            "mode": resolved_mode,
            "query_kwargs": query_kwargs,
            "retrieved_context": "",
            "distilled_context": "",
            "answer": str(answer).strip(),
            "fallback_used": True,
        }

    def _normalize_user_query(self, question: str) -> str:
        normalized = " ".join(str(question).strip().split())
        if not normalized:
            return normalized

        normalized = re.sub(r"(?i)^(?:q(?:uestion)?\s*\d+\s*[:.)-]\s*)", "", normalized)
        normalized = re.sub(r"(?i)\brag[\s-]*anything\b", "RAG-Anything", normalized)
        normalized = re.sub(
            r"(?i)\bretrieval augmented generation\b",
            "Retrieval-Augmented Generation",
            normalized,
        )
        return normalized

    async def _retrieve_core_context(self, question: str, mode: str, query_kwargs: dict) -> str | None:
        supported = self._get_supported_queryparam_fields()
        if supported is None:
            logger.warning("QueryParam signature unavailable; skip direct context retrieval")
            return None

        retrieval_attempts = []
        if "only_need_context" in supported:
            retrieval_attempts.append("only_need_context")
        if "only_need_prompt" in supported:
            retrieval_attempts.append("only_need_prompt")
        if not retrieval_attempts:
            logger.warning(
                "Current LightRAG runtime does not expose only_need_context/only_need_prompt; cannot perform separate context retrieval"
            )
            return None

        retrieval_modes = [mode]
        if mode != "naive":
            retrieval_modes.append("naive")

        contexts_by_flag: dict[str, list[str]] = {flag_name: [] for flag_name in retrieval_attempts}
        seen = set()
        for retrieval_mode in retrieval_modes:
            for flag_name in retrieval_attempts:
                attempt_kwargs = dict(query_kwargs)
                attempt_kwargs[flag_name] = True
                try:
                    raw_result = await self.rag.aquery(
                        question,
                        mode=retrieval_mode,
                        system_prompt=None,
                        **attempt_kwargs,
                    )
                except Exception as exc:
                    logger.warning(
                        "Core retrieval context attempt failed (flag=%s, mode=%s): %s",
                        flag_name,
                        retrieval_mode,
                        exc,
                    )
                    continue

                context = self._sanitize_retrieved_context(raw_result, flag_name=flag_name)
                if not context:
                    continue

                key = re.sub(r"\s+", " ", context[:1000]).strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                logger.info(
                    "Retrieved core context successfully via %s/%s (chars=%d)",
                    retrieval_mode,
                    flag_name,
                    len(context),
                )
                contexts_by_flag[flag_name].append(f"[{retrieval_mode}]\n{context}")

        preferred_contexts = contexts_by_flag.get("only_need_context") or []
        if not preferred_contexts:
            preferred_contexts = contexts_by_flag.get("only_need_prompt") or []
        if not preferred_contexts:
            return None

        merged = "\n\n".join(preferred_contexts[:2]).strip()
        if len(merged) > 10000:
            merged = merged[:10000].rstrip()
        return merged

    @staticmethod
    def _sanitize_retrieved_context(raw_result: Any, *, flag_name: str | None = None) -> str | None:
        if raw_result is None:
            return None

        if isinstance(raw_result, (dict, list)):
            context = json.dumps(raw_result, ensure_ascii=False, indent=2).strip()
        else:
            context = str(raw_result).strip()
        if not context:
            return None

        if "---Context---" in context:
            context = context.split("---Context---", 1)[1].strip()

        cleanup_patterns = [
            r"(?im)^system prompt:.*$",
            r"(?im)^instructions?:.*$",
            r"(?im)^you are .*assistant.*$",
            r"(?im)^answer using the provided context.*$",
            r"(?im)^image path:.*$",
            r"(?im)^content:\s*\{'type':\s*'discarded'.*$",
            r"(?im)^---role---\s*$",
            r"(?im)^---goal---\s*$",
            r"(?im)^---instructions---\s*$",
            r"(?im)^additional instructions:.*$",
        ]
        for pattern in cleanup_patterns:
            context = re.sub(pattern, "", context)

        context = re.sub(r"(?is)discarded content analysis:\s*", "", context)
        context = re.sub(r"(?im)^---+\s*context\s*---+\s*$", "", context)
        context = re.sub(r"(?im)^knowledge graph data\s*\((?:entity|relationship)\)\s*:\s*$", "", context)
        context = re.sub(r"(?im)^document chunks?\s*:\s*$", "", context)
        context = re.sub(r"(?im)^reference document list\s*:\s*$", "", context)
        context = re.sub(r"(?im)^sources?\s*:\s*$", "", context)
        context = re.sub(r"(?im)^```(?:json)?\s*$", "", context)
        context = re.sub(r"(?im)^#{1,6}\s*references\s*$", "", context)
        context = re.sub(r"(?im)^\s*-\s*\[\d+\]\s+.*$", "", context)
        context = re.sub(r"(?im)^\s*\*\s*\[\d+\]\s+.*$", "", context)
        context = re.sub(r"(?im)^\[(?:mix|naive|local|global|hybrid|default)[^\]]*\]\s*$", "", context)

        if flag_name == "only_need_prompt" and "Knowledge Graph Data" in context:
            # only_need_prompt often returns full answer-instruction wrappers; after trimming
            # we still keep only evidence-like content.
            context = re.sub(r"(?is)^.*?(knowledge graph data.*)$", r"\1", context).strip()

        context = re.sub(r"\n{3,}", "\n\n", context).strip()
        if len(context) > 8000:
            context = context[:8000].rstrip()
        return context or None

    async def _distill_core_context(self, question: str, retrieved_context: str) -> str:
        prompt = CONTEXT_DISTILL_USER_PROMPT.format(
            question=question,
            context=retrieved_context,
        )
        try:
            distilled = await self.llm_f(prompt, system_prompt=QUALITY_FIRST_SYSTEM_PROMPT)
        except Exception as exc:
            logger.warning("Context distillation failed: %s", exc)
            return retrieved_context

        distilled = str(distilled).strip()
        if not distilled or distilled == "INSUFFICIENT EVIDENCE":
            return retrieved_context
        return distilled

    async def _answer_from_core_context(self, question: str, retrieved_context: str) -> str:
        prompt = CONTEXT_GROUNDED_USER_PROMPT.format(
            question=question,
            context=retrieved_context,
        )
        return await self.llm_f(prompt, system_prompt=QUALITY_FIRST_SYSTEM_PROMPT)

    @staticmethod
    def _align_embedding_dim_with_storage(storage_dir: Path, embed_func: EmbeddingFunc) -> EmbeddingFunc:
        vdb_file = storage_dir / "vdb_entities.json"
        if not vdb_file.exists():
            return embed_func

        try:
            with open(vdb_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored_dim = data.get("embedding_dim")
            if not stored_dim:
                return embed_func
        except Exception:
            return embed_func

        current_dim = getattr(embed_func, "embedding_dim", None)
        if current_dim == stored_dim:
            return embed_func

        original = embed_func.func

        async def aligned_embed(texts):
            vectors = await original(texts)
            aligned = []
            for vector in vectors:
                vector = list(vector)
                if len(vector) > stored_dim:
                    vector = vector[:stored_dim]
                elif len(vector) < stored_dim:
                    vector = vector + [0.0] * (stored_dim - len(vector))
                aligned.append(vector)
            return aligned

        return EmbeddingFunc(
            embedding_dim=stored_dim,
            max_token_size=getattr(embed_func, "max_token_size", 8192),
            func=aligned_embed,
        )

    @staticmethod
    def _get_supported_queryparam_fields() -> set[str] | None:
        if QueryParam is None:
            return None
        try:
            signature = inspect.signature(QueryParam)
        except (TypeError, ValueError):
            return None
        return set(signature.parameters.keys())

    def _build_quality_query_kwargs(self) -> dict:
        supported = self._get_supported_queryparam_fields()
        if supported is None:
            return {}

        candidates = {
            "vlm_enhanced": False,
            "top_k": ENV.query_top_k,
            "chunk_top_k": ENV.query_chunk_top_k,
            "response_type": ENV.query_response_type,
            "enable_rerank": ENV.query_enable_rerank,
        }
        return {key: value for key, value in candidates.items() if key in supported}
