import inspect
import json
import logging
import re
from pathlib import Path

from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig

from .config import ENV
from .definitions import EXPERIMENTS
from .models import get_model_funcs

try:
    from lightrag import QueryParam
except Exception:  # pragma: no cover - fallback for environments that lazy-install LightRAG
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
        if experiment_id not in EXPERIMENTS:
            raise ValueError(f"Unknown experiment_id: {experiment_id}")

        self.experiment_id = experiment_id
        self.exp_def = EXPERIMENTS[experiment_id]
        self.exp_dir = Path(ENV.output_base_dir) / experiment_id
        self.storage_dir = self.exp_dir / "rag_storage"
        self.parser_name = self.exp_def.parser or ENV.parser
        self.parse_method = self.exp_def.parse_method or ENV.parse_method

        # Query nên dùng cùng provider/embedding family với experiment để giữ retrieval ổn định.
        self.llm_f, _, self.embed_f = get_model_funcs(self.exp_def.provider)
        self.rag = None

    async def initialize(self):
        """Khởi tạo RAGAnything ở chế độ query-only, không parse lại tài liệu."""
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
        """
        Query pipeline ưu tiên core retrieval của RAGAnything/LightRAG:
        1. Lấy retrieved context từ chính LightRAG (nếu runtime hỗ trợ only_need_context/only_need_prompt).
        2. Chạy grounded answer synthesis từ context đó.
        3. Nếu runtime hiện tại không hỗ trợ lấy context thô, fallback về rag.aquery(...) mặc định.
        """
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
            return await self._answer_from_core_context(
                normalized_question,
                distilled_context or retrieved_context,
            )

        logger.warning(
            "Could not fetch core retrieval context directly for query '%s'. Falling back to LightRAG mode '%s'.",
            normalized_question,
            resolved_mode,
        )
        return await self.rag.aquery(
            normalized_question,
            mode=resolved_mode,
            system_prompt=QUALITY_FIRST_SYSTEM_PROMPT,
            **query_kwargs,
        )

    def _normalize_user_query(self, question: str) -> str:
        normalized = " ".join(str(question).strip().split())
        if not normalized:
            return normalized

        # Bỏ các quiz prefixes kiểu "Q2:" để retrieval tập trung vào semantic query.
        normalized = re.sub(r"(?i)^(?:q(?:uestion)?\s*\d+\s*[:.)-]\s*)", "", normalized)

        # Chỉ giữ alias normalization tối thiểu cho proper nouns phổ biến của repo/paper.
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

        if "only_need_prompt" in supported:
            retrieval_attempts = ["only_need_prompt"]
        else:
            retrieval_attempts = []
        if "only_need_context" in supported:
            retrieval_attempts.append("only_need_context")

        if not retrieval_attempts:
            logger.warning(
                "Current LightRAG runtime does not expose only_need_context/only_need_prompt; "
                "cannot perform separate context retrieval"
            )
            return None

        retrieval_modes = [mode]
        if mode != "naive":
            retrieval_modes.append("naive")

        contexts: list[str] = []
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

                context = self._sanitize_retrieved_context(raw_result)
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
                contexts.append(f"[{retrieval_mode}/{flag_name}]\n{context}")

        if not contexts:
            return None

        merged = "\n\n".join(contexts[:2]).strip()
        if len(merged) > 10000:
            merged = merged[:10000].rstrip()
        return merged

    @staticmethod
    def _sanitize_retrieved_context(raw_result) -> str | None:
        if raw_result is None:
            return None

        if isinstance(raw_result, (dict, list)):
            context = json.dumps(raw_result, ensure_ascii=False, indent=2).strip()
        else:
            context = str(raw_result).strip()
        if not context:
            return None

        # Nếu only_need_prompt trả về nguyên prompt, loại bớt một số marker chỉ thị phổ biến
        # để answer model tập trung hơn vào retrieved evidence.
        cleanup_patterns = [
            r"(?im)^system prompt:.*$",
            r"(?im)^instructions?:.*$",
            r"(?im)^you are .*assistant.*$",
            r"(?im)^answer using the provided context.*$",
            r"(?im)^image path:.*$",
            r"(?im)^content:\s*\{'type':\s*'discarded'.*$",
        ]
        for pattern in cleanup_patterns:
            context = re.sub(pattern, "", context)

        context = re.sub(r"(?is)discarded content analysis:\s*", "", context)

        # Nếu LightRAG trả về prompt đầy đủ có nhiều sections, ưu tiên giữ phần Sources/Chunks
        # vì đây thường là evidence trực tiếp nhất cho answer synthesis.
        prioritized_section_patterns = [
            r"(?is)(?:^|\n)-{2,}\s*sources\s*-{2,}\s*\n(.*)$",
            r"(?is)(?:^|\n)-{2,}\s*source chunks?\s*-{2,}\s*\n(.*)$",
            r"(?is)(?:^|\n)-{2,}\s*chunks?\s*-{2,}\s*\n(.*)$",
            r"(?is)(?:^|\n)sources?:\s*\n(.*)$",
        ]
        for pattern in prioritized_section_patterns:
            matched = re.search(pattern, context)
            if matched:
                context = matched.group(1).strip()
                break

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
        """
        Đọc embedding_dim từ VDB lưu trữ; nếu khác với embed_func hiện tại
        thì tạo wrapper cắt/padding để khớp, tránh lỗi mismatch khi load kho cũ.
        """
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
        if current_dim == stored_dim or not current_dim:
            return embed_func

        logger.warning(
            "Embedding dim mismatch detected. Storage: %s, current: %s. "
            "Auto-adjusting query embedding to match storage.",
            stored_dim,
            current_dim,
        )

        async def _wrapper(texts):
            maybe = embed_func.func(texts)
            if hasattr(maybe, "__await__"):
                vectors = await maybe
            else:
                vectors = maybe
            adjusted = []
            for vec in vectors:
                if len(vec) > stored_dim:
                    adjusted.append(vec[:stored_dim])
                elif len(vec) < stored_dim:
                    adjusted.append(vec + [0.0] * (stored_dim - len(vec)))
                else:
                    adjusted.append(vec)
            return adjusted

        return EmbeddingFunc(
            embedding_dim=stored_dim,
            max_token_size=embed_func.max_token_size,
            func=_wrapper,
        )

    @staticmethod
    def _get_supported_queryparam_fields() -> set[str] | None:
        if QueryParam is None:
            return None
        try:
            signature = inspect.signature(QueryParam)
            return set(signature.parameters.keys())
        except Exception:
            return None

    def _build_quality_query_kwargs(self) -> dict:
        """
        Chỉ truyền các tham số QueryParam mà runtime LightRAG hiện tại thực sự hỗ trợ.
        Điều này giữ cho workspace tương thích giữa các version LightRAG khác nhau.
        """
        supported = self._get_supported_queryparam_fields()
        if supported is None:
            return {"vlm_enhanced": False}

        proposed = {
            "vlm_enhanced": False,
            "top_k": ENV.query_top_k,
            "chunk_top_k": ENV.query_chunk_top_k,
            "response_type": ENV.query_response_type,
            "enable_rerank": ENV.query_enable_rerank,
        }

        query_kwargs = {"vlm_enhanced": False}
        for key, value in proposed.items():
            if key == "vlm_enhanced":
                continue
            if key in supported:
                query_kwargs[key] = value

        return query_kwargs
