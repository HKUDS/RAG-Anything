import logging
import json
import inspect
import math
import re
import unicodedata
from pathlib import Path
from raganything import RAGAnything, RAGAnythingConfig
from .models import get_model_funcs
from .config import ENV
from .definitions import EXPERIMENTS
from lightrag.utils import EmbeddingFunc

try:
    from lightrag import QueryParam
except Exception:  # pragma: no cover - fallback for environments that lazy-install LightRAG
    QueryParam = None

logger = logging.getLogger("QA_Engine")


QUALITY_FIRST_SYSTEM_PROMPT = (
    "You are a document-grounded QA assistant. "
    "Answer only from the retrieved evidence. "
    "Prefer precise facts, numbers, table values, and named entities when available. "
    "If the evidence is insufficient or ambiguous, say so explicitly instead of guessing. "
    "When multiple retrieved snippets disagree, state the conflict briefly and give the most supported answer."
)

LEXICAL_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "to", "of", "for", "in",
    "on", "at", "by", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "does", "do", "did",
    "can", "could", "should", "would", "will", "may", "might", "about", "into", "through", "across",
    "this", "that", "these", "those", "it", "its", "their", "them", "they", "he", "she", "we", "you",
    "your", "our", "ours", "his", "her", "than", "such", "more", "most", "other", "some", "any",
    "all", "each", "both", "between", "during", "over", "under", "also", "there", "here", "very",
    "aim", "aims", "address", "addresses",
}

DEFINITION_CUES = (
    "what is",
    "what are",
    "define",
    "definition",
    "core idea",
    "main idea",
    "primary limitation",
    "main limitation",
    "challenge",
    "contribution",
    "purpose",
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
        self._text_chunks = None
        self._chunk_token_df = None

    async def initialize(self):
        """Khởi tạo LightRAG ở chế độ Query (không parse lại)"""
        config = RAGAnythingConfig(
            working_dir=str(self.storage_dir),
            parser=self.parser_name,
            parse_method=self.parse_method,
        )

        # Đồng bộ embedding_dim với storage nếu khác ENV (tránh lỗi mismatch khi query kho cũ)
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
        Query pipeline theo hướng chất lượng:
        1. Ưu tiên lexical evidence retrieval trên text chunks để lấy đoạn chứng cứ sát câu hỏi.
        2. Tổng hợp câu trả lời grounded trực tiếp từ các evidence blocks đã chọn.
        3. Chỉ fallback về LightRAG query mode khi evidence quá yếu.
        """
        if self.rag is None:
            await self.initialize()

        resolved_mode = mode or ENV.query_default_mode
        query_kwargs = self._build_quality_query_kwargs()
        normalized_question = self._normalize_user_query(question)

        logger.info(
            "Querying: %s (Normalized: %s, Fallback mode: %s, QueryKwargs: %s)",
            question,
            normalized_question,
            resolved_mode,
            query_kwargs,
        )

        evidence_blocks = self._retrieve_text_evidence_blocks(normalized_question)
        if evidence_blocks:
            logger.info(
                "Using evidence-first QA with %d blocks: %s",
                len(evidence_blocks),
                ", ".join(block["label"] for block in evidence_blocks),
            )
            return await self._answer_from_evidence(normalized_question, evidence_blocks)

        logger.warning(
            "Lexical evidence retrieval was weak for query '%s'. Falling back to LightRAG mode '%s'.",
            normalized_question,
            resolved_mode,
        )
        return await self.rag.aquery(
            normalized_question,
            mode=resolved_mode,
            system_prompt=QUALITY_FIRST_SYSTEM_PROMPT,
            **query_kwargs,
        )

    def _load_text_chunks(self) -> list[dict]:
        if self._text_chunks is not None:
            return self._text_chunks

        chunks_file = self.storage_dir / "kv_store_text_chunks.json"
        if not chunks_file.exists():
            logger.warning("Text chunk store not found: %s", chunks_file)
            self._text_chunks = []
            self._chunk_token_df = {}
            return self._text_chunks

        with open(chunks_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        chunks = []
        token_df = {}
        for chunk_id, chunk in raw_data.items():
            content = str(chunk.get("content", "")).strip()
            if not content:
                continue
            # Skip parser artifact analyses; they inject layout noise into QA retrieval.
            if content.startswith("Discarded Content Analysis:") or "Content: {'type': 'discarded'" in content:
                continue
            norm = self._normalize_text(content)
            tokens = self._tokenize(content)
            token_set = set(tokens)
            for token in token_set:
                token_df[token] = token_df.get(token, 0) + 1
            chunks.append(
                {
                    "id": chunk_id,
                    "content": content,
                    "chunk_order_index": chunk.get("chunk_order_index", 0),
                    "norm": norm,
                    "compact": self._compact_text(norm),
                    "tokens": tokens,
                }
            )

        self._text_chunks = sorted(chunks, key=lambda x: (x["chunk_order_index"], x["id"]))
        self._chunk_token_df = token_df
        return self._text_chunks

    def _normalize_user_query(self, question: str) -> str:
        normalized = " ".join(str(question).strip().split())
        if not normalized:
            return normalized

        normalized = re.sub(
            r"(?i)\brag[\s-]*anything\b",
            "RAG-Anything",
            normalized,
        )
        normalized = re.sub(
            r"(?i)\bretrieval augmented generation\b",
            "Retrieval-Augmented Generation",
            normalized,
        )
        return normalized

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = unicodedata.normalize("NFKC", str(text)).lower()
        text = text.replace("\u2013", "-").replace("\u2014", "-")
        text = re.sub(r"[^a-z0-9\s-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _compact_text(text: str) -> str:
        return re.sub(r"[\s\-]+", "", text)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9][a-z0-9\-]*", RAGQueryEngine._normalize_text(text))
        return [t for t in tokens if len(t) > 1 and t not in LEXICAL_STOPWORDS]

    @staticmethod
    def _generate_query_phrases(query_tokens: list[str]) -> list[str]:
        phrases = []
        max_n = min(4, len(query_tokens))
        for n in range(max_n, 1, -1):
            for i in range(len(query_tokens) - n + 1):
                phrase_tokens = query_tokens[i : i + n]
                if len(phrase_tokens) < 2:
                    continue
                phrase = " ".join(phrase_tokens)
                if phrase not in phrases:
                    phrases.append(phrase)
        return phrases[:20]

    def _idf(self, token: str) -> float:
        token_df = self._chunk_token_df or {}
        total_docs = max(len(self._text_chunks or []), 1)
        df = token_df.get(token, 0)
        return math.log(1 + (total_docs / (1 + df)))

    def _score_block(
        self,
        block_text: str,
        query_norm: str,
        query_compact: str,
        query_tokens: list[str],
        query_phrases: list[str],
        order_index: int = 0,
        definition_like: bool = False,
    ) -> tuple[float, dict]:
        block_norm = self._normalize_text(block_text)
        if not block_norm:
            return 0.0, {}

        block_compact = self._compact_text(block_norm)
        block_tokens = set(self._tokenize(block_text))

        token_score = sum(self._idf(token) for token in query_tokens if token in block_tokens)
        phrase_hits = [phrase for phrase in query_phrases if phrase in block_norm]
        bigram_hits = max(len([p for p in phrase_hits if len(p.split()) == 2]), 0)

        exact_compact_hit = query_compact and query_compact in block_compact
        full_query_hit = query_norm and query_norm in block_norm

        score = token_score
        if phrase_hits:
            score += 3.0 * len(phrase_hits)
        if bigram_hits:
            score += 1.5 * bigram_hits
        if exact_compact_hit:
            score += 8.0
        if full_query_hit:
            score += 10.0
        if definition_like and order_index <= 2:
            score += max(0.0, 3.0 - order_index)
        if definition_like and ("abstract" in block_norm or "introduction" in block_norm):
            score += 2.0

        details = {
            "token_score": round(token_score, 3),
            "phrase_hits": phrase_hits[:6],
            "exact_compact_hit": exact_compact_hit,
            "full_query_hit": full_query_hit,
        }
        return score, details

    def _retrieve_text_evidence_blocks(self, question: str) -> list[dict]:
        chunks = self._load_text_chunks()
        if not chunks:
            return []

        query_norm = self._normalize_text(question)
        query_compact = self._compact_text(query_norm)
        query_tokens = self._tokenize(question)
        if not query_tokens:
            return []
        query_phrases = self._generate_query_phrases(query_tokens)
        definition_like = any(cue in query_norm for cue in DEFINITION_CUES)

        scored_chunks = []
        for chunk in chunks:
            score, details = self._score_block(
                chunk["content"],
                query_norm=query_norm,
                query_compact=query_compact,
                query_tokens=query_tokens,
                query_phrases=query_phrases,
                order_index=chunk["chunk_order_index"],
                definition_like=definition_like,
            )
            if score > 0:
                scored_chunks.append((score, details, chunk))

        scored_chunks.sort(key=lambda item: item[0], reverse=True)
        top_chunk_candidates = scored_chunks[: ENV.query_local_chunk_top_k]
        if not top_chunk_candidates:
            return []

        logger.info(
            "Top lexical chunks: %s",
            " | ".join(
                f"{item[2]['id']}@{item[2]['chunk_order_index']}={item[0]:.2f}"
                for item in top_chunk_candidates[:5]
            ),
        )

        evidence_blocks = []
        seen_paragraphs = set()
        for chunk_score, _, chunk in top_chunk_candidates:
            paragraphs = [
                p.strip()
                for p in re.split(r"\n\s*\n+", chunk["content"])
                if p.strip()
            ]
            if not paragraphs:
                paragraphs = [chunk["content"]]

            scored_paragraphs = []
            for paragraph in paragraphs:
                para_score, para_details = self._score_block(
                    paragraph,
                    query_norm=query_norm,
                    query_compact=query_compact,
                    query_tokens=query_tokens,
                    query_phrases=query_phrases,
                    order_index=chunk["chunk_order_index"],
                    definition_like=definition_like,
                )
                if para_score > 0:
                    combined_score = chunk_score * 0.35 + para_score
                    scored_paragraphs.append((combined_score, para_details, paragraph))

            scored_paragraphs.sort(key=lambda item: item[0], reverse=True)
            for combined_score, para_details, paragraph in scored_paragraphs[: ENV.query_local_paragraphs_per_chunk]:
                paragraph_key = self._normalize_text(paragraph)[:400]
                if paragraph_key in seen_paragraphs:
                    continue
                seen_paragraphs.add(paragraph_key)
                evidence_blocks.append(
                    {
                        "label": f"E{len(evidence_blocks) + 1}",
                        "chunk_id": chunk["id"],
                        "chunk_order_index": chunk["chunk_order_index"],
                        "score": round(combined_score, 3),
                        "details": para_details,
                        "text": paragraph[: ENV.query_local_evidence_max_chars].strip(),
                    }
                )
                if len(evidence_blocks) >= ENV.query_local_evidence_top_k:
                    break
            if len(evidence_blocks) >= ENV.query_local_evidence_top_k:
                break

        if not evidence_blocks:
            return []

        strongest_score = evidence_blocks[0]["score"]
        if strongest_score < ENV.query_local_min_score:
            logger.warning(
                "Best lexical evidence score %.2f is below threshold %.2f",
                strongest_score,
                ENV.query_local_min_score,
            )
            return []

        return evidence_blocks

    async def _answer_from_evidence(self, question: str, evidence_blocks: list[dict]) -> str:
        evidence_text = []
        for block in evidence_blocks:
            evidence_text.append(
                f"[{block['label']}] (chunk={block['chunk_id']}, order={block['chunk_order_index']}, score={block['score']})\n"
                f"{block['text']}"
            )

        prompt = (
            "Answer the question using only the evidence blocks below.\n"
            "Rules:\n"
            "- Give a direct answer in 1-3 sentences.\n"
            "- Do not use outside knowledge.\n"
            "- Do not answer from generic background knowledge about RAG or AI unless it is explicitly stated in the evidence.\n"
            "- If the evidence is insufficient, say so explicitly.\n"
            "- Prefer wording that stays close to the evidence.\n"
            "- Add short inline citations like [E1] or [E2] for the key supporting claims.\n\n"
            f"Question:\n{question}\n\n"
            f"Evidence Blocks:\n{chr(10).join(evidence_text)}"
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
            f"Embedding dim mismatch detected. Storage: {stored_dim}, current: {current_dim}. "
            "Auto-adjusting query embedding to match storage."
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
                    # pad with zeros to expected dim
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
            # Explicitly disable query-time VLM path in workspace answer pipeline.
            "vlm_enhanced": False,
            # Quality-first retrieval defaults.
            "top_k": ENV.query_top_k,
            "chunk_top_k": ENV.query_chunk_top_k,
            "response_type": ENV.query_response_type,
            "enable_rerank": ENV.query_enable_rerank,
        }

        # `vlm_enhanced` là tham số của RAGAnything.aquery, không thuộc QueryParam.
        query_kwargs = {"vlm_enhanced": False}

        for key, value in proposed.items():
            if key == "vlm_enhanced":
                continue
            if key in supported:
                query_kwargs[key] = value

        return query_kwargs
