"""
Query Pipeline — Core Query Engine for RAGAnything.

Layer: Core
Primary Responsibility: QueryMixin — text/hybrid/graph/multimodal/VLM query
    orchestration, context building, LLM response formatting, citation enforcement.
Key Dependencies: lightrag (LightRAG, QueryParam), raganything.prompt (PROMPTS),
    raganything.citation_parser, raganything.utils

Call chain (main query paths):
    query() / aquery()
      ├── _aquery_rrf()          — hybrid vector+BM25+graph RRF fusion
      │     └── _ensure_citations()  — post-hoc citation block generation
      └── _aquery_graph()        — graph-only traversal (local/global)
    aquery_with_multimodal()     — text + multimodal content joint query
      └── _process_multimodal_query_content()
            └── _generate_query_content_description()
    aquery_vlm_enhanced()        — VLM-processed images + text query
      └── _process_image_paths_for_vlm() → _call_vlm_with_multimodal_content()
"""

import asyncio
import json
import hashlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field

import jieba
from datetime import datetime, timezone
from typing import Dict, List, Any
from pathlib import Path
from lightrag import QueryParam
from lightrag.utils import always_get_an_event_loop
from raganything.prompt import PROMPTS, INLINE_QUOTE_INSTRUCTION, ANSWER_FORMAT_INSTRUCTION

# Hint appended to LLM prompt when text chunk resolution fails (chunks=0)
DEGRADED_CONTEXT_HINT = (
    "\n\n⚠️ 注意：本次检索未能获取到关联的文档文本内容（仅获取到实体名称和关系路径），"
    "以下回答可能不够详细。请优先引用实体关系信息，并明确告知用户哪些信息来源自实体名而非原文。"
    "如果信息不足以回答问题，请如实说明。"
)
from raganything.citation_parser import has_citations
from raganything.utils import (
    get_processor_for_type,
    encode_image_to_base64,
    validate_image_file,
)
from raganything.services.query_execution import await_before_deadline

logger = logging.getLogger(__name__)
_RRF_PIPELINE_SETTLE_SECONDS = 0.05


def _scope_deadline(scope: object | None) -> float | None:
    if isinstance(scope, dict):
        return scope.get("deadline_monotonic")
    return getattr(scope, "deadline_monotonic", None)


def _settling_deadline(deadline_monotonic: float | None) -> float | None:
    """Reserve time for context formatting and return to the SSE watchdog."""
    if deadline_monotonic is None:
        return None
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        return deadline_monotonic
    return deadline_monotonic - min(
        _RRF_PIPELINE_SETTLE_SECONDS, remaining / 2
    )

class QueryMixin:
    """QueryMixin class containing query functionality for RAGAnything"""

    def _generate_multimodal_cache_key(
        self, query: str, multimodal_content: List[Dict[str, Any]], mode: str, **kwargs
    ) -> str:
        """
        Generate cache key for multimodal query

        Args:
            query: Base query text
            multimodal_content: List of multimodal content
            mode: Query mode
            **kwargs: Additional parameters

        Returns:
            str: Cache key hash
        """
        # Create a normalized representation of the query parameters
        cache_data = {
            "query": query.strip(),
            "mode": mode,
            "scope": dict(
                kwargs.get("query_execution_scope")
                or getattr(self, "query_cache_scope", {})
                or {}
            ),
        }

        # Normalize multimodal content for stable caching
        normalized_content = []
        if multimodal_content:
            for item in multimodal_content:
                if isinstance(item, dict):
                    normalized_item = {}
                    for key, value in item.items():
                        # For file paths, use basename to make cache more portable
                        if key in [
                            "img_path",
                            "image_path",
                            "file_path",
                        ] and isinstance(value, str):
                            normalized_item[key] = Path(value).name
                        # For large content, create a hash instead of storing directly
                        elif (
                            key in ["table_data", "table_body"]
                            and isinstance(value, str)
                            and len(value) > 200
                        ):
                            normalized_item[f"{key}_hash"] = hashlib.md5(
                                value.encode()
                            ).hexdigest()
                        else:
                            normalized_item[key] = value
                    normalized_content.append(normalized_item)
                else:
                    normalized_content.append(item)

        cache_data["multimodal_content"] = normalized_content

        # Add relevant kwargs to cache data
        relevant_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            in [
                "stream",
                "response_type",
                "top_k",
                "max_tokens",
                "temperature",
                "system_prompt",
                # "only_need_context",
                # "only_need_prompt",
            ]
        }
        cache_data.update(relevant_kwargs)

        # Generate hash from the cache data
        cache_str = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
        cache_hash = hashlib.md5(cache_str.encode()).hexdigest()

        return f"multimodal_query:{cache_hash}"

    async def _ensure_citations(
        self,
        answer: str,
        query: str,
        context: str,
        system_prompt: str | None = None,
    ) -> str:
        """Post-process: detect missing citations and optionally trigger follow-up.

        When ``enforce_citation`` is enabled and the answer lacks ``[来源 N]`` markers,
        logs a warning and attempts a lightweight follow-up to append citations.
        On failure, appends a visible note to the answer so the user is aware.

        Args:
            answer: The LLM-generated answer text.
            query: The original user query.
            context: The retrieved document context (used only for source doc names).
            system_prompt: Optional system prompt for the follow-up request.

        Returns:
            The original answer, supplemented answer, or answer with a warning note.
        """
        if not self.config.enforce_citation:
            return answer

        if has_citations(answer):
            return answer

        self.logger.warning(
            "Answer missing [来源 N] citation markers (enforce_citation=True)."
        )

        if self.llm_model_func is None:
            return (
                answer
                + "\n\n---\n⚠️ 此回答缺少来源引用，请核实检索结果。"
            )

        try:
            # Lightweight follow-up: include partial context so LLM can extract
            # actual document names and excerpts (was hallucinating without it).
            # Truncate context to ~2000 chars to keep token cost low.
            context_snippet = context[:2000] if context else ""
            supplement_prompt = (
                "以下回答缺少来源引用标记。请在**不改变原有回答内容**的前提下，"
                "仅在末尾追加一个参考文献块。\n\n"
                f"## 原始问题\n{query}\n\n"
                f"## 检索内容（节选）\n{context_snippet}\n\n"
                f"## 原始回答\n{answer}\n\n"
                "## 要求\n"
                "只输出 `📚 参考来源` 块，每行格式：\n"
                "`[来源 文档名] — \"原文摘录...\"`\n"
                "从检索内容中提取真实的 [来源 文档名] 和原文，严禁编造。"
                "不要重复输出原始回答。"
            )
            supplement = await self.llm_model_func(
                supplement_prompt, system_prompt=system_prompt
            )
            if supplement and isinstance(supplement, str):
                # Merge: original answer + citation block
                merged = answer.rstrip() + "\n\n" + supplement.strip()
                if has_citations(merged):
                    self.logger.info("Citation supplementation successful.")
                    return merged

            # Supplementation failed — append visible note
            self.logger.warning("Citation supplementation did not produce valid citations.")
            return (
                answer
                + "\n\n---\n⚠️ 此回答缺少来源引用，请核实检索结果。"
            )
        except Exception as exc:
            self.logger.error(f"Citation supplementation failed: {exc}")
            return (
                answer
                + "\n\n---\n⚠️ 此回答缺少来源引用，请核实检索结果。"
            )

    async def aquery(
        self, query: str, mode: str = "mix", system_prompt: str | None = None, **kwargs
    ):
        """
        Pure text query - directly calls LightRAG's query functionality

        Args:
            query: Query text
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass", "rrf")
            system_prompt: Optional system prompt to include.
            **kwargs: Other query parameters, will be passed to QueryParam
                - vlm_enhanced: bool, default True when vision_model_func is available.
                  If True, will parse image paths in retrieved context and replace them
                  with base64 encoded images for VLM processing.
                - stream: bool, if True returns AsyncIterator[str] for token-by-token streaming.

        Returns:
            str or AsyncIterator[str]: Query result (or token stream if stream=True)
        """
        if self.lightrag is None:
            raise ValueError(
                "No LightRAG instance available. Please process documents first or provide a pre-initialized LightRAG instance."
            )

        # Pop 'param' early — it's already resolved into mode, we don't forward it
        query_param = kwargs.pop("param", None)
        if query_param is not None:
            # If caller passed a QueryParam, extract mode and other fields into kwargs
            mode = query_param.mode if hasattr(query_param, 'mode') else mode
            for field in ('only_need_context', 'only_need_prompt', 'stream', 'top_k',
                          'chunk_top_k', 'max_entity_tokens', 'max_relation_tokens',
                          'max_total_tokens', 'response_type', 'hl_keywords', 'll_keywords',
                          'enable_rerank', 'include_references'):
                val = getattr(query_param, field, None)
                default = getattr(type(query_param)(), field, None)
                if val is not None and val != default:
                    kwargs.setdefault(field, val)

        # RRF hybrid search mode — three-channel parallel retrieval with RRF fusion
        if mode == "rrf":
            return await self._aquery_rrf(
                query, system_prompt=system_prompt, **kwargs
            )

        # ``hybrid`` is the legacy default. Once a caller supplies immutable
        # per-user retrieval options, execute the scoped hybrid implementation
        # instead of silently dropping those options in LightRAG.
        if mode == "hybrid" and kwargs.get("retrieval_options") is not None:
            return await self._aquery_rrf(
                query, system_prompt=system_prompt, **kwargs
            )

        # Graph-only mode — entity matching + neighbor traversal with path tracing
        if mode == "graph":
            return await self._aquery_graph(
                query, system_prompt=system_prompt, **kwargs
            )

        # Retrieval options configure the project RRF engine. LightRAG's
        # QueryParam does not accept them for its local/global/naive paths.
        kwargs.pop("retrieval_options", None)

        # Check if VLM enhanced query should be used
        vlm_enhanced = kwargs.pop("vlm_enhanced", None)
        stream = kwargs.pop("stream", False)

        # Auto-determine VLM enhanced based on availability
        if vlm_enhanced is None:
            vlm_enhanced = (
                hasattr(self, "vision_model_func")
                and self.vision_model_func is not None
            )

        # VLM enhanced is not compatible with streaming
        if stream and vlm_enhanced:
            self.logger.warning(
                "Streaming mode requested with VLM enhancement — "
                "VLM enhancement is incompatible with streaming and will be disabled"
            )
            vlm_enhanced = False

        # Use VLM enhanced query if enabled and available
        if (
            vlm_enhanced
            and hasattr(self, "vision_model_func")
            and self.vision_model_func
        ):
            return await self.aquery_vlm_enhanced(
                query, mode=mode, system_prompt=system_prompt, **kwargs
            )
        elif vlm_enhanced and (
            not hasattr(self, "vision_model_func") or not self.vision_model_func
        ):
            self.logger.warning(
                "VLM enhanced query requested but vision_model_func is not available, falling back to normal query"
            )

        callback_manager = getattr(self, "callback_manager", None)
        query_start_time = time.time()

        if callback_manager is not None:
            callback_manager.dispatch(
                "on_query_start",
                query=query,
                mode=mode,
            )

        # Create query parameters
        # Enable include_references by default so LightRAG returns source refs
        query_execution_scope = kwargs.pop("query_execution_scope", None)
        deadline_monotonic = _scope_deadline(query_execution_scope)
        kwargs.setdefault("include_references", True)
        query_param = QueryParam(mode=mode, **kwargs)

        # Query text is request content and must not enter server logs.
        self.logger.info("Executing text query mode=%s", mode)

        try:
            # Call LightRAG's query method
            result = await await_before_deadline(
                self.lightrag.aquery(
                    query, param=query_param, system_prompt=system_prompt
                ),
                deadline_monotonic,
            )

            # For streaming, return the async generator directly
            if stream:
                if result is None:
                    raise RuntimeError(
                        "Streaming query returned empty result. "
                        "The model may not support streaming. "
                        "Try switching to hybrid or naive mode."
                    )
                # LightRAG sometimes returns a plain string instead of an async generator
                if isinstance(result, str):
                    self.logger.warning(
                        "Streaming query returned string instead of generator, "
                        "falling back to non-streaming"
                    )
                    # Fall through to normal completion path below
                else:
                    self.logger.info("Streaming query started")
                    return result

        except Exception as exc:
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_query_error",
                    query=query,
                    mode=mode,
                    error=exc,
                )
            raise

        self.logger.info("Text query completed")
        if callback_manager is not None:
            duration = time.time() - query_start_time
            result_len = len(result) if isinstance(result, str) else 0
            callback_manager.dispatch(
                "on_query_complete",
                query=query,
                mode=mode,
                duration_seconds=duration,
                result_length=result_len,
            )
        return result

    async def _aquery_rrf(
        self, query: str, system_prompt: str | None = None, **kwargs
    ) -> str:
        """
        RRF hybrid search query — three-channel parallel retrieval + RRF fusion.

        Uses HybridSearchEngine for retrieval, then formats context and generates
        answer via the configured LLM model function.

        When only_need_context=True, returns raw context without LLM generation.
        """
        hybrid_engine = getattr(self, "hybrid_search_engine", None)
        only_need_context = kwargs.pop("only_need_context", False)
        query_execution_scope = kwargs.pop("query_execution_scope", None)
        retrieval_options = kwargs.pop("retrieval_options", None)
        # RRF is text-only. Keep this pipeline control flag out of the
        # LightRAG QueryParam used when RRF falls back to native hybrid.
        kwargs.pop("vlm_enhanced", None)
        deadline_monotonic = _scope_deadline(query_execution_scope)

        if hybrid_engine is None:
            self.logger.warning(
                "HybridSearchEngine not initialized — falling back to LightRAG hybrid mode"
            )
            query_param = QueryParam(mode="hybrid", only_need_context=only_need_context, **kwargs)
            return await await_before_deadline(
                self.lightrag.aquery(
                    query, param=query_param, system_prompt=system_prompt
                ),
                deadline_monotonic,
            )

        callback_manager = getattr(self, "callback_manager", None)
        query_start_time = time.time()

        if callback_manager is not None:
            callback_manager.dispatch("on_query_start", query=query, mode="rrf")

        self.logger.info("Executing RRF hybrid query")

        try:
            # Stage 1: Retrieve chunks via RRF fusion
            top_k = kwargs.get("top_k", 100)
            query_execution_scope = query_execution_scope or {}
            if retrieval_options is not None:
                # The settings service owns the public immutable shape, while
                # the retrieval layer owns execution-only options.  Convert by
                # value instead of mutating the shared engine or settings.
                from raganything.hybrid_search import RetrievalOptions
                if not isinstance(retrieval_options, RetrievalOptions):
                    scope = dict(query_execution_scope)
                    retrieval_options = RetrievalOptions(
                        channels=tuple(retrieval_options.channels),
                        bm25_top_k=retrieval_options.bm25_top_k,
                        vector_top_k=retrieval_options.vector_top_k,
                        graph_top_k=retrieval_options.graph_top_k,
                        graph_depth=retrieval_options.graph_depth,
                        rrf_k=retrieval_options.rrf_k,
                        bm25_tokenizer=retrieval_options.bm25_tokenizer,
                        bm25_k1=retrieval_options.bm25_k1,
                        bm25_b=retrieval_options.bm25_b,
                        workspace=scope.get("workspace"),
                        corpus_revision=scope.get("corpus_revision"),
                        permission_scope=scope.get("permission_scope"),
                        settings_fingerprint=scope.get("settings_fingerprint"),
                        deadline_monotonic=scope.get("deadline_monotonic"),
                        trace_id=scope.get("trace_id"),
                    )
            chunks = await await_before_deadline(
                hybrid_engine.search(query, top_k=top_k, options=retrieval_options),
                deadline_monotonic,
            )
            post_retrieval_deadline = _settling_deadline(deadline_monotonic)

            if not chunks:
                self.logger.warning("RRF search returned no chunks")
                return "No relevant documents found for your query."

            self.logger.info(
                f"RRF retrieved {len(chunks)} chunks"
            )

            # Filter out chunks that are LightRAG fail_response artifacts.
            # These get into the pipeline when the vector channel returns a
            # "no-context" response that _parse_lightrag_context mis-parses
            # as a valid chunk (defense-in-depth with the parser-level guard).
            before_filter = len(chunks)
            chunks = [c for c in chunks if "[no-context]" not in c.content]
            if before_filter != len(chunks):
                self.logger.warning(
                    f"Filtered out {before_filter - len(chunks)} fail_response "
                    f"artifact chunk(s)"
                )

            if not chunks:
                self.logger.warning("All RRF chunks were fail_response artifacts — no valid context")
                return "No relevant documents found for your query."

            # Stage 1.5: Rerank chunks (optional, enabled by RERANK_ENABLED=true)
            enable_rerank = kwargs.pop("enable_rerank", False)
            rerank_top_n = 15
            if enable_rerank:
                import os as _os
                rerank_model = _os.getenv("RERANK_MODEL", "qwen3-rerank")
                rerank_api_key = _os.getenv(
                    "LLM_BINDING_API_KEY",
                    _os.getenv("RERANK_BINDING_API_KEY", ""),
                )
                if rerank_api_key:
                    chunk_texts = [c.content for c in chunks]
                    try:
                        ranked = await await_before_deadline(
                            rerank_chunks(
                                query, chunk_texts,
                                api_key=rerank_api_key,
                                model=rerank_model,
                                top_n=rerank_top_n,
                            ),
                            post_retrieval_deadline,
                        )
                    except TimeoutError:
                        self.logger.info("RRF rerank deadline reached; using fused order")
                    else:
                        # Reorder chunks by rerank results.
                        idx_map = {idx: chunks[idx] for idx, _ in ranked}
                        chunks = [idx_map[i] for i in range(len(ranked)) if i in idx_map]
                        self.logger.info(
                            f"Reranked {len(chunks)} chunks -> top {rerank_top_n}"
                        )
                else:
                    self.logger.warning("Rerank enabled but no API key found")

            # Agent retrieval first requests context-only data for its own
            # request-scoped generation step. It does not use entity annotations,
            # so avoid the full graph scan and debug-only tokenization below.
            # Source lookup remains bounded because it supplies citation labels.
            if only_need_context:
                chunk_ids = [c.chunk_id for c in chunks[:15]]
                try:
                    source_infos = await await_before_deadline(
                        self.batch_get_doc_source_info_async(chunk_ids),
                        post_retrieval_deadline,
                    )
                except Exception:
                    source_infos = {}
                context_parts = []
                doc_name_counts: dict[str, int] = {}
                for chunk in chunks[:15]:
                    info = source_infos.get(chunk.chunk_id, {})
                    document_name = chunk.document_name or info.get("document_name")
                    source_name = document_name or f"未知文档-{chunk.chunk_id[:8]}"
                    count = doc_name_counts.get(source_name, 0)
                    doc_name_counts[source_name] = count + 1
                    source_label = (
                        source_name if count == 0 else f"{source_name} (片段{count + 1})"
                    )
                    context_parts.append(f"[来源 {source_label}]\n{chunk.content}")
                context = "\n\n".join(context_parts)
                self.logger.info("RRF query completed (context-only mode)")
                if callback_manager is not None:
                    callback_manager.dispatch(
                        "on_query_complete",
                        query=query,
                        mode="rrf",
                        duration_seconds=time.time() - query_start_time,
                        result_length=len(context),
                    )
                return context

            # Stage 2: Build context from retrieved chunks with entity annotation
            # Collect entity names + types from the knowledge graph, filtered
            # by type relevance to avoid noise (framework names, generic terms, etc.)
            RELEVANT_ENTITY_TYPES = {
                "模块", "功能", "组件", "系统", "子系统",
                "MODULE", "FUNCTION", "COMPONENT", "SYSTEM",
            }
            entity_data = {}  # name -> type
            try:
                graph = getattr(hybrid_engine._lightrag, "chunk_entity_relation_graph", None)
                if graph:
                    all_nodes = await await_before_deadline(
                        graph.get_all_nodes(), post_retrieval_deadline
                    )
                    for node in (all_nodes or []):
                        name = node.get("entity_name") or node.get("id", "")
                        etype = (node.get("entity_type") or node.get("type", "")).strip()
                        if name and isinstance(name, str) and len(name) >= 4:
                            entity_data[name] = etype
            except Exception as e:
                self.logger.warning(f"Failed to collect entity names: {e}")

            # Build entity name set for matching: include ALL entity types first,
            # then prioritize RELEVANT_ENTITY_TYPES when displaying
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                entity_data.clear()
            all_entity_names = set(entity_data.keys())

            # Enrich chunks with source document info for citation tracing
            chunk_ids = [c.chunk_id for c in chunks[:15]]
            try:
                source_infos = await await_before_deadline(
                    self.batch_get_doc_source_info_async(chunk_ids),
                    post_retrieval_deadline,
                )
            except Exception:
                source_infos = {}
            for chunk in chunks[:15]:
                info = source_infos.get(chunk.chunk_id, {})
                chunk.file_path = chunk.file_path or info.get("file_path")
                chunk.document_name = chunk.document_name or info.get("document_name")

            # Track doc names to deduplicate same-document chunks
            doc_name_counts: dict[str, int] = {}
            context_parts = []
            for chunk in chunks[:15]:  # top-15 for context window
                doc_name = chunk.document_name or f"未知文档-{chunk.chunk_id[:8]}"
                # Deduplicate: append number suffix if same doc name appears multiple times
                count = doc_name_counts.get(doc_name, 0)
                doc_name_counts[doc_name] = count + 1
                source_label = doc_name if count == 0 else f"{doc_name} (片段{count + 1})"
                # Annotate chunks with relevant entity names using word-boundary matching
                matched_relevant = []   # entities with relevant types (模块/功能/组件/系统)
                matched_other = []      # other entities (fallback)
                chunk_lower = chunk.content.lower()
                for entity_name in all_entity_names:
                    ename_lower = entity_name.lower()
                    # Use word-boundary matching to reduce false positives
                    pattern = re.compile(r'(?<![a-zA-Z0-9一-鿿])' + re.escape(ename_lower) + r'(?![a-zA-Z0-9一-鿿])')
                    if pattern.search(chunk_lower):
                        etype = entity_data.get(entity_name, "")
                        if etype in RELEVANT_ENTITY_TYPES:
                            matched_relevant.append(entity_name)
                        else:
                            matched_other.append(entity_name)

                # Prioritize relevant-type entities, fall back to others
                display_entities = (matched_relevant[:5] or matched_other[:5])
                context_parts.append(
                    f"[来源 {source_label}]\n"
                    f"{chunk.content}"
                )
                if display_entities:
                    context_parts.append(
                        f"[关联实体（来源 {source_label}）：{', '.join(display_entities)}]"
                    )
            context = "\n\n".join(context_parts)

            # Debug: show entity names related to query keywords
            deadline_reached = False
            if deadline_monotonic is not None:
                try:
                    # Reuse the await boundary used above so this post-processing
                    # guard follows the same monotonic clock and timeout semantics.
                    await await_before_deadline(asyncio.sleep(0), deadline_monotonic)
                except TimeoutError:
                    deadline_reached = True
            if deadline_reached:
                related_entities = []
            else:
                query_keywords = set(jieba.lcut(query))
                related_entities = [e for e in all_entity_names
                                   if any(kw in e for kw in query_keywords if len(kw) >= 2)]
            self.logger.info(f"RRF related-entities ({len(related_entities)}): {related_entities[:15]}")

            # Debug: log top-3 retrieved chunks for context traceability
            for i, chunk in enumerate(chunks[:3]):
                preview = chunk.content[:100].replace("\n", " ")
                self.logger.info(
                    f"RRF top-{i+1}: [{','.join(chunk.sources)}] "
                    f"id={chunk.chunk_id[:24]}... score={chunk.score:.4f} "
                    f"preview={preview}..."
                )
            # Debug: show entity annotations in top-5 context
            for i in range(min(5, len(context_parts))):
                part = context_parts[i]
                if "[关联实体" in part:
                    m = re.search(r'\[关联实体[^\]]*\][：:](.+)', part)
                    names = m.group(1) if m else "?"
                    self.logger.info(
                        f"RRF doc-{i+1} 关联实体: {names}"
                    )
            if not any("[关联实体" in p for p in context_parts):
                self.logger.info("RRF entity-annotation: NONE in top-15 context")

            # Stage 3: Generate answer via LLM
            citation_instruction = (
                ANSWER_FORMAT_INSTRUCTION if self.config.enforce_citation
                else INLINE_QUOTE_INSTRUCTION
            )
            # Detect degraded context: has entities/relations but no text chunks
            has_chunks = "[来源 " in context and len(context.strip()) > 200
            prompt = (
                f"以下是知识库中检索到的相关内容。你必须严格基于这些内容回答问题，不得使用你自己的知识。\n\n"
                f"## 检索内容\n{context}\n\n"
                f"## 问题\n{query}\n\n"
                f"{citation_instruction}"
                f"{'' if has_chunks else DEGRADED_CONTEXT_HINT}"
            )

            if not has_chunks and context.strip():
                self.logger.warning(
                    "[RRF_DEGRADED] Context has no text chunks. "
                    "LLM answer quality may be degraded."
                )

            if self.llm_model_func is None:
                self.logger.error("llm_model_func is None, returning context only")
                return context

            llm_timeout = float(os.getenv("LLM_QUERY_TIMEOUT", "60"))
            answer = await asyncio.wait_for(
                self.llm_model_func(prompt, system_prompt=system_prompt),
                timeout=llm_timeout,
            )

            # Guard against None return from LLM
            if answer is None:
                self.logger.warning("LLM returned None, falling back to context only")
                return context
            if not isinstance(answer, str):
                answer = str(answer)

            # Post-process: ensure citations are present (if enforce_citation enabled)
            answer = await self._ensure_citations(answer, query, context, system_prompt)

            self.logger.info("RRF query completed")
            if callback_manager is not None:
                duration = time.time() - query_start_time
                callback_manager.dispatch(
                    "on_query_complete",
                    query=query,
                    mode="rrf",
                    duration_seconds=duration,
                    result_length=len(answer),
                )

            return answer

        except Exception as exc:
            self.logger.error("RRF query failed")
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_query_error", query=query, mode="rrf", error=exc
                )
            # Fallback to LightRAG hybrid mode
            self.logger.warning("Falling back to LightRAG hybrid mode")
            query_param = QueryParam(mode="hybrid", only_need_context=only_need_context, **kwargs)
            return await await_before_deadline(
                self.lightrag.aquery(
                    query, param=query_param, system_prompt=system_prompt
                ),
                deadline_monotonic,
            )

    async def _aquery_graph(
        self, query: str, system_prompt: str | None = None, **kwargs
    ) -> str:
        """Graph-only query — entity matching + neighbor traversal with paths.

        Uses :class:`GraphRetriever` directly for explainable entity-centric
        retrieval.  Results include matched entity names, traversal paths, and
        graph statistics alongside retrieved chunks.

        When ``only_need_context=True``, returns raw context without LLM generation.
        """
        hybrid_engine = getattr(self, "hybrid_search_engine", None)
        only_need_context = kwargs.pop("only_need_context", False)
        deadline_monotonic = _scope_deadline(
            kwargs.pop("query_execution_scope", None)
        )

        if hybrid_engine is None:
            return "Graph query unavailable — no knowledge graph initialized."

        # Access GraphRetriever through HybridSearchEngine
        graph_retriever = hybrid_engine.graph_retriever
        if graph_retriever is None or graph_retriever._lightrag is None:
            return "Graph query unavailable — knowledge graph is empty."

        top_k = kwargs.get("top_k", None)
        result = await await_before_deadline(
            graph_retriever.search_with_paths(query, top_k=top_k),
            deadline_monotonic,
        )

        matched = result.get("matched_entities", [])
        results = result.get("results", [])
        stats = result.get("graph_stats", {})

        # --- No entities matched: return diagnostic info ---
        if not matched and not results:
            # Sample available entities to help user/agent reformulate
            sample_entities = ""
            try:
                graph = getattr(
                    graph_retriever._lightrag, "chunk_entity_relation_graph", None
                )
                if graph:
                    all_nodes = await await_before_deadline(
                        graph.get_all_nodes(), deadline_monotonic
                    )
                    if all_nodes:
                        entity_samples = []
                        for nd in all_nodes[:50]:
                            en = nd.get("entity_name", nd.get("entity_id", ""))
                            et = nd.get("entity_type", "unknown")
                            if en and isinstance(en, str):
                                entity_samples.append(f"{en}({et})")
                        if entity_samples:
                            sample_entities = (
                                f"\nAvailable entities (sample): "
                                f"{', '.join(entity_samples[:20])}"
                            )
                            if len(entity_samples) > 20:
                                sample_entities += (
                                    f" ... and {len(entity_samples) - 20} more"
                                )
            except Exception:
                pass

            total = stats.get("total_entities", 0)
            if total == 0:
                return (
                    "Knowledge graph is empty — no entities have been extracted "
                    "yet. Please process documents first to build the knowledge "
                    "graph."
                )

            return (
                f"No entities matched query '{query}' in knowledge graph "
                f"({total} total entities).\n"
                f"Try using entity names that appear in your documents."
                f"{sample_entities}"
            )

        # Handle edge case: entities matched but no reachable chunks
        if not results:
            entities_str = ", ".join(
                f"{e['name']}({e['type']})" for e in matched[:10]
            )
            return (
                f"Matched {len(matched)} entity(s) in the knowledge graph: "
                f"{entities_str}\n"
                f"No document chunks reachable from these entities via "
                f"{stats.get('traversal_depth', '?')}-hop traversal."
            )

        # Build context with path annotations
        # Enrich chunks with source document info for citation tracing
        chunk_ids = [item["chunk"].chunk_id for item in results[:15]]
        try:
            source_infos = await await_before_deadline(
                self.batch_get_doc_source_info_async(chunk_ids), deadline_monotonic
            )
        except Exception:
            source_infos = {}

        context_parts = []
        for i, item in enumerate(results[:15]):
            chunk = item["chunk"]
            # Fill source info
            info = source_infos.get(chunk.chunk_id, {})
            chunk.file_path = chunk.file_path or info.get("file_path")
            chunk.document_name = chunk.document_name or info.get("document_name")
            doc_name = chunk.document_name or f"未知文档-{chunk.chunk_id[:8]}"

            paths = item.get("paths", [])
            paths_str = ""
            if paths:
                path_lines = []
                for p in paths[:5]:
                    hop_label = f"hop-{p['depth']}" if p["depth"] > 0 else "direct"
                    path_lines.append(
                        f"  ├ {p['entity']} →[{p['relation']}] ({hop_label})"
                    )
                paths_str = "\n".join(path_lines)
            chunk_text = chunk.content[:800] if chunk.content else "(empty)"
            context_parts.append(
                f"[来源 {doc_name}] score={chunk.score:.3f}\n"
                f"Entity paths:\n{paths_str}\n"
                f"Content: {chunk_text}"
            )

        context = "\n\n".join(context_parts)

        # Entity match summary
        entity_list = ", ".join(
            f"{e['name']}({e['type']}, deg={e['degree']})" for e in matched[:10]
        )

        if only_need_context:
            return (
                f"=== Graph Query Results ===\n"
                f"Total entities: {stats.get('total_entities', '?')}\n"
                f"Matched: {len(matched)} ({entity_list})\n"
                f"Traversal depth: {stats.get('traversal_depth', '?')}\n"
                f"\n{context}"
            )

        # Stage 3: Generate answer via LLM
        if self.llm_model_func is None:
            return context

        citation_instruction = (
            ANSWER_FORMAT_INSTRUCTION if self.config.enforce_citation
            else INLINE_QUOTE_INSTRUCTION
        )
        # Detect degraded context: has entities/relations but no text chunks
        has_chunks = "Content:" in context and len(context.strip()) > 200
        prompt = (
            f"以下是知识图谱遍历检索结果。你必须严格基于这些内容回答问题，不得使用你自己的知识。\n\n"
            f"图谱统计：共 {stats.get('total_entities', '?')} 个实体，"
            f"匹配 {len(matched)} 个（{entity_list}）。\n"
            f"遍历深度：{stats.get('traversal_depth', '?')} 跳。\n\n"
            f"## 检索内容（含实体关系路径）\n{context}\n\n"
            f"## 问题\n{query}\n\n"
            f"请基于检索内容回答，回答中可引用相关实体关系。\n\n"
            f"{citation_instruction}"
            f"{'' if has_chunks else DEGRADED_CONTEXT_HINT}"
        )

        if not has_chunks and context.strip():
            self.logger.warning(
                "[GRAPH_DEGRADED] Graph context has entity paths but no text chunks. "
                "LLM answer quality may be degraded."
            )

        answer = await await_before_deadline(
            self.llm_model_func(prompt, system_prompt=system_prompt),
            deadline_monotonic,
        )

        if answer is None:
            return context
        if not isinstance(answer, str):
            answer = str(answer)

        # Post-process: ensure citations are present (if enforce_citation enabled)
        answer = await await_before_deadline(
            self._ensure_citations(answer, query, context, system_prompt),
            deadline_monotonic,
        )

        return answer

    async def aquery_with_multimodal(
        self,
        query: str,
        multimodal_content: List[Dict[str, Any]] = None,
        mode: str = "mix",
        system_prompt: str | None = None,
        **kwargs,
    ) -> str:
        """
        Multimodal query - combines text and multimodal content for querying

        Args:
            query: Base query text
            multimodal_content: List of multimodal content, each element contains:
                - type: Content type ("image", "table", "equation", etc.)
                - Other fields depend on type (e.g., img_path, table_data, latex, etc.)
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass", "rrf")
            system_prompt: Optional system prompt to include in the query
            **kwargs: Other query parameters, will be passed to QueryParam

        Returns:
            str: Query result

        Examples:
            # Pure text query
            result = await rag.query_with_multimodal("What is machine learning?")

            # Image query
            result = await rag.query_with_multimodal(
                "Analyze the content in this image",
                multimodal_content=[{
                    "type": "image",
                    "img_path": "./image.jpg"
                }]
            )

            # Table query
            result = await rag.query_with_multimodal(
                "Analyze the data trends in this table",
                multimodal_content=[{
                    "type": "table",
                    "table_data": "Name,Age\nAlice,25\nBob,30"
                }]
            )
        """
        # Ensure LightRAG is initialized
        init_result = await self._ensure_lightrag_initialized()
        if not init_result or not init_result.get("success"):
            raise RuntimeError(
                f"LightRAG initialization failed: {(init_result or {}).get('error', 'unknown error')}"
            )

        self.logger.info("Executing multimodal query mode=%s", mode)

        # If no multimodal content, fallback to pure text query
        if not multimodal_content:
            self.logger.info("No multimodal content provided, executing text query")
            return await self.aquery(
                query, mode=mode, system_prompt=system_prompt, **kwargs
            )

        # Generate cache key for multimodal query
        cache_key = self._generate_multimodal_cache_key(
            query,
            multimodal_content,
            mode,
            system_prompt=system_prompt,
            **kwargs,
        )

        # Check cache if available and enabled
        cached_result = None
        if (
            hasattr(self, "lightrag")
            and self.lightrag
            and hasattr(self.lightrag, "llm_response_cache")
            and self.lightrag.llm_response_cache
        ):
            if self.lightrag.llm_response_cache.global_config.get(
                "enable_llm_cache", True
            ):
                try:
                    cached_result = await self.lightrag.llm_response_cache.get_by_id(
                        cache_key
                    )
                    if cached_result and isinstance(cached_result, dict):
                        result_content = cached_result.get("return")
                        if result_content:
                            self.logger.info(
                                f"Multimodal query cache hit: {cache_key[:16]}..."
                            )
                            return result_content
                except Exception as e:
                    self.logger.debug(f"Error accessing multimodal query cache: {e}")

        # Process multimodal content to generate enhanced query text
        enhanced_query = await self._process_multimodal_query_content(
            query, multimodal_content
        )

        self.logger.info(
            f"Generated enhanced query length: {len(enhanced_query)} characters"
        )

        # Execute enhanced query
        result = await self.aquery(
            enhanced_query, mode=mode, system_prompt=system_prompt, **kwargs
        )

        # Save to cache if available and enabled
        if (
            hasattr(self, "lightrag")
            and self.lightrag
            and hasattr(self.lightrag, "llm_response_cache")
            and self.lightrag.llm_response_cache
        ):
            if self.lightrag.llm_response_cache.global_config.get(
                "enable_llm_cache", True
            ):
                try:
                    # Create cache entry for multimodal query
                    cache_entry = {
                        "return": result,
                        "cache_type": "multimodal_query",
                        "original_query": query,
                        "multimodal_content_count": len(multimodal_content),
                        "mode": mode,
                    }

                    await self.lightrag.llm_response_cache.upsert(
                        {cache_key: cache_entry}
                    )
                    self.logger.info(
                        f"Saved multimodal query result to cache: {cache_key[:16]}..."
                    )
                except Exception as e:
                    self.logger.debug(f"Error saving multimodal query to cache: {e}")

        # Ensure cache is persisted to disk
        if (
            hasattr(self, "lightrag")
            and self.lightrag
            and hasattr(self.lightrag, "llm_response_cache")
            and self.lightrag.llm_response_cache
        ):
            try:
                await self.lightrag.llm_response_cache.index_done_callback()
            except Exception as e:
                self.logger.debug(f"Error persisting multimodal query cache: {e}")

        self.logger.info("Multimodal query completed")
        return result

    async def aquery_vlm_enhanced(
        self,
        query: str,
        mode: str = "mix",
        system_prompt: str | None = None,
        extra_safe_dirs: List[str] = None,
        **kwargs,
    ) -> str:
        """
        VLM enhanced query - replaces image paths in retrieved context with base64 encoded images for VLM processing

        Args:
            query: User query
            mode: Underlying LightRAG query mode
            system_prompt: Optional system prompt to include
            extra_safe_dirs: Optional list of additional safe directories to allow images from
            **kwargs: Other query parameters

        Returns:
            str: VLM query result
        """
        deadline_monotonic = _scope_deadline(
            kwargs.pop("query_execution_scope", None)
        )

        # Ensure VLM is available
        if not hasattr(self, "vision_model_func") or not self.vision_model_func:
            raise ValueError(
                "VLM enhanced query requires vision_model_func. "
                "Please provide a vision model function when initializing RAGAnything."
            )

        # Ensure LightRAG is initialized
        init_result = await self._ensure_lightrag_initialized()
        if not init_result or not init_result.get("success"):
            raise RuntimeError(
                f"LightRAG initialization failed: {(init_result or {}).get('error', 'unknown error')}"
            )

        self.logger.info("Executing VLM enhanced query mode=%s", mode)

        # Clear previous image cache
        if hasattr(self, "_current_images_base64"):
            delattr(self, "_current_images_base64")

        # 1. Get original retrieval prompt (without generating final answer)
        query_param = QueryParam(mode=mode, only_need_prompt=True, **kwargs)
        raw_prompt = await await_before_deadline(
            self.lightrag.aquery(query, param=query_param), deadline_monotonic
        )

        self.logger.debug("Retrieved raw prompt from LightRAG")

        # 2. Extract and process image paths
        enhanced_prompt, images_found = await self._process_image_paths_for_vlm(
            raw_prompt, extra_safe_dirs=extra_safe_dirs
        )

        if not images_found:
            self.logger.info("No valid images found, falling back to normal query")
            # Fallback to normal query
            query_param = QueryParam(mode=mode, **kwargs)
            return await await_before_deadline(
                self.lightrag.aquery(
                    query, param=query_param, system_prompt=system_prompt
                ),
                deadline_monotonic,
            )

        self.logger.info(f"Processed {images_found} images for VLM")

        # 3. Build VLM message format
        messages = self._build_vlm_messages_with_images(
            enhanced_prompt, query, system_prompt
        )

        # 4. Call VLM for question answering
        result = await await_before_deadline(
            self._call_vlm_with_multimodal_content(messages), deadline_monotonic
        )

        self.logger.info("VLM enhanced query completed")
        return result

    async def _process_multimodal_query_content(
        self, base_query: str, multimodal_content: List[Dict[str, Any]]
    ) -> str:
        """
        Process multimodal query content to generate enhanced query text

        Args:
            base_query: Base query text
            multimodal_content: List of multimodal content

        Returns:
            str: Enhanced query text
        """
        self.logger.info("Starting multimodal query content processing...")

        enhanced_parts = [f"User query: {base_query}"]

        for i, content in enumerate(multimodal_content):
            content_type = content.get("type", "unknown")
            self.logger.info(
                f"Processing {i + 1}/{len(multimodal_content)} multimodal content: {content_type}"
            )

            try:
                # Get appropriate processor
                processor = get_processor_for_type(self.modal_processors, content_type)

                if processor:
                    # Generate content description
                    description = await self._generate_query_content_description(
                        processor, content, content_type
                    )
                    enhanced_parts.append(
                        f"\nRelated {content_type} content: {description}"
                    )
                else:
                    # If no appropriate processor, use basic description
                    basic_desc = str(content)[:200]
                    enhanced_parts.append(
                        f"\nRelated {content_type} content: {basic_desc}"
                    )

            except Exception as e:
                self.logger.error(f"Error processing multimodal content: {str(e)}")
                # Continue processing other content
                continue

        enhanced_query = "\n".join(enhanced_parts)
        enhanced_query += PROMPTS["QUERY_ENHANCEMENT_SUFFIX"]

        self.logger.info("Multimodal query content processing completed")
        return enhanced_query

    async def _generate_query_content_description(
        self, processor, content: Dict[str, Any], content_type: str
    ) -> str:
        """
        Generate content description for query

        Args:
            processor: Multimodal processor
            content: Content data
            content_type: Content type

        Returns:
            str: Content description
        """
        try:
            if content_type == "image":
                return await self._describe_image_for_query(processor, content)
            elif content_type == "table":
                return await self._describe_table_for_query(processor, content)
            elif content_type == "equation":
                return await self._describe_equation_for_query(processor, content)
            else:
                return await self._describe_generic_for_query(
                    processor, content, content_type
                )

        except Exception as e:
            self.logger.error(f"Error generating {content_type} description: {str(e)}")
            return f"{content_type} content: {str(content)[:100]}"

    async def _describe_image_for_query(
        self, processor, content: Dict[str, Any]
    ) -> str:
        """Generate image description for query"""
        image_path = content.get("img_path")
        captions = content.get("image_caption", content.get("img_caption", []))
        footnotes = content.get("image_footnote", content.get("img_footnote", []))

        if image_path and Path(image_path).exists():
            # If image exists, use vision model to generate description
            image_base64 = processor._encode_image_to_base64(image_path)
            if image_base64:
                prompt = PROMPTS["QUERY_IMAGE_DESCRIPTION"]
                description = await processor.modal_caption_func(
                    prompt,
                    image_data=image_base64,
                    system_prompt=PROMPTS["QUERY_IMAGE_ANALYST_SYSTEM"],
                )
                return description

        # If image doesn't exist or processing failed, use existing information
        parts = []
        if image_path:
            parts.append(f"Image path: {image_path}")
        if captions:
            parts.append(f"Image captions: {', '.join(captions)}")
        if footnotes:
            parts.append(f"Image footnotes: {', '.join(footnotes)}")

        return "; ".join(parts) if parts else "Image content information incomplete"

    async def _describe_table_for_query(
        self, processor, content: Dict[str, Any]
    ) -> str:
        """Generate table description for query"""
        table_data = content.get("table_data", "")
        table_caption = content.get("table_caption", "")

        prompt = PROMPTS["QUERY_TABLE_ANALYSIS"].format(
            table_data=table_data, table_caption=table_caption
        )

        description = await processor.modal_caption_func(
            prompt, system_prompt=PROMPTS["QUERY_TABLE_ANALYST_SYSTEM"]
        )

        return description

    async def _describe_equation_for_query(
        self, processor, content: Dict[str, Any]
    ) -> str:
        """Generate equation description for query"""
        latex = content.get("latex", "")
        equation_caption = content.get("equation_caption", "")

        prompt = PROMPTS["QUERY_EQUATION_ANALYSIS"].format(
            latex=latex, equation_caption=equation_caption
        )

        description = await processor.modal_caption_func(
            prompt, system_prompt=PROMPTS["QUERY_EQUATION_ANALYST_SYSTEM"]
        )

        return description

    async def _describe_generic_for_query(
        self, processor, content: Dict[str, Any], content_type: str
    ) -> str:
        """Generate generic content description for query"""
        content_str = str(content)

        prompt = PROMPTS["QUERY_GENERIC_ANALYSIS"].format(
            content_type=content_type, content_str=content_str
        )

        description = await processor.modal_caption_func(
            prompt,
            system_prompt=PROMPTS["QUERY_GENERIC_ANALYST_SYSTEM"].format(
                content_type=content_type
            ),
        )

        return description

    async def _process_image_paths_for_vlm(
        self, prompt: str, extra_safe_dirs: List[str] = None
    ) -> tuple[str, int]:
        """
        Process image paths in prompt, keeping original paths and adding VLM markers

        Args:
            prompt: Original prompt
            extra_safe_dirs: Optional list of additional safe directories

        Returns:
            tuple: (processed prompt, image count)
        """
        enhanced_prompt = prompt
        images_processed = 0

        # Initialize image cache
        self._current_images_base64 = []

        # Enhanced regex pattern for matching image paths
        # Matches only the path ending with image file extensions
        image_path_pattern = (
            r"Image Path:\s*([^\r\n]*?\.(?:jpg|jpeg|png|gif|bmp|webp|tiff|tif))"
        )

        # First, let's see what matches we find
        matches = re.findall(image_path_pattern, prompt)
        self.logger.info("Image path scan completed: matches=%d", len(matches))

        def replace_image_path(match):
            nonlocal images_processed

            image_path = match.group(1).strip()
            self.logger.debug("Processing controlled image reference")

            # Validate path format (basic check)
            if not image_path or len(image_path) < 3:
                self.logger.warning("Invalid image path format")
                return match.group(0)  # Keep original

            # Use utility function to validate image file
            is_valid = validate_image_file(image_path)

            # Security check: only allow images from the workspace or output directories
            # to prevent indirect prompt injection from reading arbitrary system files.
            if is_valid:
                abs_image_path = Path(image_path).resolve()
                # Check if it's in the current working directory or subdirectories
                try:
                    is_in_cwd = abs_image_path.is_relative_to(Path.cwd())
                except ValueError:
                    is_in_cwd = False

                # If a config is available, check against working_dir and parser_output_dir
                is_in_safe_dir = is_in_cwd
                if hasattr(self, "config") and self.config:
                    try:
                        is_in_working = abs_image_path.is_relative_to(
                            Path(self.config.working_dir).resolve()
                        )
                        is_in_output = abs_image_path.is_relative_to(
                            Path(self.config.parser_output_dir).resolve()
                        )
                        is_in_safe_dir = is_in_safe_dir or is_in_working or is_in_output
                    except Exception:
                        pass

                # Check against extra safe directories if provided
                if not is_in_safe_dir and extra_safe_dirs:
                    for safe_dir in extra_safe_dirs:
                        try:
                            if abs_image_path.is_relative_to(Path(safe_dir).resolve()):
                                is_in_safe_dir = True
                                break
                        except Exception:
                            continue

                if not is_in_safe_dir:
                    self.logger.warning("Blocking image outside approved directories")
                    is_valid = False

            if not is_valid:
                self.logger.warning("Image validation failed or path unsafe")
                return match.group(0)  # Keep original if validation fails

            try:
                # Encode image to base64 using utility function
                self.logger.debug("Encoding controlled image reference")
                image_base64 = encode_image_to_base64(image_path)
                if image_base64:
                    images_processed += 1
                    # Save base64 to instance variable for later use
                    self._current_images_base64.append(image_base64)

                    # Keep original path info and add VLM marker
                    result = f"Image Path: {image_path}\n[VLM_IMAGE_{images_processed}]"
                    self.logger.debug(
                        "Controlled image reference processed: count=%d",
                        images_processed,
                    )
                    return result
                else:
                    self.logger.error("Controlled image encoding failed")
                    return match.group(0)  # Keep original if encoding failed

            except Exception:
                self.logger.error("Controlled image processing failed")
                return match.group(0)  # Keep original

        # Execute replacement
        enhanced_prompt = re.sub(
            image_path_pattern, replace_image_path, enhanced_prompt
        )

        return enhanced_prompt, images_processed

    def _build_vlm_messages_with_images(
        self, enhanced_prompt: str, user_query: str, system_prompt: str
    ) -> List[Dict]:
        """
        Build VLM message format, using markers to correspond images with text positions

        Args:
            enhanced_prompt: Enhanced prompt with image markers
            user_query: User query

        Returns:
            List[Dict]: VLM message format
        """
        images_base64 = getattr(self, "_current_images_base64", [])

        if not images_base64:
            # Pure text mode
            return [
                {
                    "role": "user",
                    "content": f"Context:\n{enhanced_prompt}\n\nUser Question: {user_query}",
                }
            ]

        # Build multimodal content
        content_parts = []

        # Split text at image markers and insert images
        text_parts = enhanced_prompt.split("[VLM_IMAGE_")

        for i, text_part in enumerate(text_parts):
            if i == 0:
                # First text part
                if text_part.strip():
                    content_parts.append({"type": "text", "text": text_part})
            else:
                # Find marker number and insert corresponding image
                marker_match = re.match(r"(\d+)\](.*)", text_part, re.DOTALL)
                if marker_match:
                    image_num = (
                        int(marker_match.group(1)) - 1
                    )  # Convert to 0-based index
                    remaining_text = marker_match.group(2)

                    # Insert corresponding image
                    if 0 <= image_num < len(images_base64):
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{images_base64[image_num]}"
                                },
                            }
                        )

                    # Insert remaining text
                    if remaining_text.strip():
                        content_parts.append({"type": "text", "text": remaining_text})

        # Add user question
        content_parts.append(
            {
                "type": "text",
                "text": f"\n\nUser Question: {user_query}\n\nPlease answer based on the context and images provided.",
            }
        )
        base_system_prompt = "You are a helpful assistant that can analyze both text and image content to provide comprehensive answers."

        if system_prompt:
            full_system_prompt = base_system_prompt + " " + system_prompt
        else:
            full_system_prompt = base_system_prompt

        return [
            {
                "role": "system",
                "content": full_system_prompt,
            },
            {
                "role": "user",
                "content": content_parts,
            },
        ]

    async def _call_vlm_with_multimodal_content(self, messages: List[Dict]) -> str:
        """
        Call VLM to process multimodal content

        Args:
            messages: VLM message format

        Returns:
            str: VLM response result
        """
        try:
            user_message = messages[1]
            content = user_message["content"]
            system_prompt = messages[0]["content"]

            if isinstance(content, str):
                # Pure text mode
                result = await self.vision_model_func(
                    content, system_prompt=system_prompt
                )
            else:
                # Multimodal mode - pass complete messages directly to VLM
                result = await self.vision_model_func(
                    "",  # Empty prompt since we're using messages format
                    messages=messages,
                )

            return result

        except Exception as e:
            self.logger.error(f"VLM call failed: {e}")
            raise

    # Synchronous versions of query methods
    def query(self, query: str, mode: str = "mix", **kwargs) -> str:
        """
        Synchronous version of pure text query

        Args:
            query: Query text
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass", "rrf")
            **kwargs: Other query parameters, will be passed to QueryParam
                - vlm_enhanced: bool, default True when vision_model_func is available.
                  If True, will parse image paths in retrieved context and replace them
                  with base64 encoded images for VLM processing.

        Returns:
            str: Query result
        """
        loop = always_get_an_event_loop()
        return loop.run_until_complete(self.aquery(query, mode=mode, **kwargs))

    def query_with_multimodal(
        self,
        query: str,
        multimodal_content: List[Dict[str, Any]] = None,
        mode: str = "mix",
        **kwargs,
    ) -> str:
        """
        Synchronous version of multimodal query

        Args:
            query: Base query text
            multimodal_content: List of multimodal content, each element contains:
                - type: Content type ("image", "table", "equation", etc.)
                - Other fields depend on type (e.g., img_path, table_data, latex, etc.)
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass", "rrf")
            **kwargs: Other query parameters, will be passed to QueryParam

        Returns:
            str: Query result
        """
        loop = always_get_an_event_loop()
        return loop.run_until_complete(
            self.aquery_with_multimodal(query, multimodal_content, mode=mode, **kwargs)
        )

