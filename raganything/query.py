"""
Query functionality for RAGAnything

Contains all query-related methods for both text and multimodal queries
"""

import json
import hashlib
import re
import time
from typing import Dict, List, Any
from pathlib import Path
from lightrag import QueryParam
from lightrag.utils import always_get_an_event_loop
from raganything.prompt import PROMPTS
from raganything.utils import (
    get_processor_for_type,
    encode_image_to_base64,
    validate_image_file,
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

        # Graph-only mode — entity matching + neighbor traversal with path tracing
        if mode == "graph":
            return await self._aquery_graph(
                query, system_prompt=system_prompt, **kwargs
            )

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
        query_param = QueryParam(mode=mode, **kwargs)

        self.logger.info(f"Executing text query: {query[:100]}...")
        self.logger.info(f"Query mode: {mode}")

        try:
            # Call LightRAG's query method
            result = await self.lightrag.aquery(
                query, param=query_param, system_prompt=system_prompt
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

        if hybrid_engine is None:
            self.logger.warning(
                "HybridSearchEngine not initialized — falling back to LightRAG hybrid mode"
            )
            query_param = QueryParam(mode="hybrid", only_need_context=only_need_context, **kwargs)
            return await self.lightrag.aquery(
                query, param=query_param, system_prompt=system_prompt
            )

        callback_manager = getattr(self, "callback_manager", None)
        query_start_time = time.time()

        if callback_manager is not None:
            callback_manager.dispatch("on_query_start", query=query, mode="rrf")

        self.logger.info(f"Executing RRF hybrid query: {query[:100]}...")

        try:
            # Stage 1: Retrieve chunks via RRF fusion
            top_k = kwargs.get("top_k", 100)
            chunks = await hybrid_engine.search(query, top_k=top_k)

            if not chunks:
                self.logger.warning("RRF search returned no chunks")
                return "No relevant documents found for your query."

            self.logger.info(
                f"RRF retrieved {len(chunks)} chunks"
            )

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
                    ranked = await rerank_chunks(
                        query, chunk_texts,
                        api_key=rerank_api_key,
                        model=rerank_model,
                        top_n=rerank_top_n,
                    )
                    # Reorder chunks by rerank results
                    idx_map = {idx: chunks[idx] for idx, _ in ranked}
                    chunks = [idx_map[i] for i in range(len(ranked)) if i in idx_map]
                    self.logger.info(
                        f"Reranked {len(chunks)} chunks -> top {rerank_top_n}"
                    )
                else:
                    self.logger.warning("Rerank enabled but no API key found")

            # Stage 2: Build context from retrieved chunks
            context_parts = []
            for i, chunk in enumerate(chunks[:15]):  # top-15 for context window
                sources_str = ",".join(chunk.sources) if chunk.sources else "unknown"
                context_parts.append(
                    f"[Doc {i + 1}] (sources: {sources_str})\n{chunk.content}"
                )
            context = "\n\n".join(context_parts)

            # Debug: log top-3 retrieved chunks for context traceability
            for i, chunk in enumerate(chunks[:3]):
                preview = chunk.content[:100].replace("\n", " ")
                self.logger.info(
                    f"RRF top-{i+1}: [{','.join(chunk.sources)}] "
                    f"id={chunk.chunk_id[:24]}... score={chunk.score:.4f} "
                    f"preview={preview}..."
                )

            # If only_need_context, return raw context without LLM generation
            if only_need_context:
                self.logger.info("RRF query completed (context-only mode)")
                if callback_manager is not None:
                    duration = time.time() - query_start_time
                    callback_manager.dispatch(
                        "on_query_complete",
                        query=query,
                        mode="rrf",
                        duration_seconds=duration,
                        result_length=len(context),
                    )
                return context

            # Stage 3: Generate answer via LLM
            prompt = (
                f"Based on the following retrieved documents, answer the user's question.\n\n"
                f"Retrieved Documents:\n{context}\n\n"
                f"User Question: {query}\n\n"
                f"Please provide a comprehensive answer based only on the provided documents. "
                f"If the documents do not contain sufficient information, say so clearly."
            )

            if self.llm_model_func is None:
                self.logger.error("llm_model_func is None, returning context only")
                return context

            answer = await self.llm_model_func(
                prompt, system_prompt=system_prompt
            )

            # Guard against None return from LLM
            if answer is None:
                self.logger.warning("LLM returned None, falling back to context only")
                return context
            if not isinstance(answer, str):
                answer = str(answer)

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
            self.logger.error(f"RRF query failed: {exc}")
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_query_error", query=query, mode="rrf", error=exc
                )
            # Fallback to LightRAG hybrid mode
            self.logger.warning("Falling back to LightRAG hybrid mode")
            query_param = QueryParam(mode="hybrid", only_need_context=only_need_context, **kwargs)
            return await self.lightrag.aquery(
                query, param=query_param, system_prompt=system_prompt
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

        if hybrid_engine is None:
            return "Graph query unavailable — no knowledge graph initialized."

        # Access GraphRetriever through HybridSearchEngine
        graph_retriever = hybrid_engine.graph_retriever
        if graph_retriever is None or graph_retriever._lightrag is None:
            return "Graph query unavailable — knowledge graph is empty."

        top_k = kwargs.get("top_k", None)
        result = await graph_retriever.search_with_paths(query, top_k=top_k)

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
                    all_nodes = await graph.get_all_nodes()
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
        context_parts = []
        for i, item in enumerate(results[:15]):
            chunk = item["chunk"]
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
                f"[Doc {i + 1}] score={chunk.score:.3f}\n"
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

        prompt = (
            f"You are answering a question using knowledge graph traversal results.\n\n"
            f"Graph Stats: {stats.get('total_entities', '?')} total entities, "
            f"{len(matched)} matched ({entity_list}).\n"
            f"Traversal depth: {stats.get('traversal_depth', '?')} hops.\n\n"
            f"Retrieved Documents (with entity relation paths):\n{context}\n\n"
            f"User Question: {query}\n\n"
            f"Please answer based on the retrieved documents. "
            f"Reference entity relations in your answer when relevant."
        )

        answer = await self.llm_model_func(
            prompt, system_prompt=system_prompt
        )

        if answer is None:
            return context
        if not isinstance(answer, str):
            answer = str(answer)

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

        self.logger.info(f"Executing multimodal query: {query[:100]}...")
        self.logger.info(f"Query mode: {mode}")

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

        self.logger.info(f"Executing VLM enhanced query: {query[:100]}...")

        # Clear previous image cache
        if hasattr(self, "_current_images_base64"):
            delattr(self, "_current_images_base64")

        # 1. Get original retrieval prompt (without generating final answer)
        query_param = QueryParam(mode=mode, only_need_prompt=True, **kwargs)
        raw_prompt = await self.lightrag.aquery(query, param=query_param)

        self.logger.debug("Retrieved raw prompt from LightRAG")

        # 2. Extract and process image paths
        enhanced_prompt, images_found = await self._process_image_paths_for_vlm(
            raw_prompt, extra_safe_dirs=extra_safe_dirs
        )

        if not images_found:
            self.logger.info("No valid images found, falling back to normal query")
            # Fallback to normal query
            query_param = QueryParam(mode=mode, **kwargs)
            return await self.lightrag.aquery(
                query, param=query_param, system_prompt=system_prompt
            )

        self.logger.info(f"Processed {images_found} images for VLM")

        # 3. Build VLM message format
        messages = self._build_vlm_messages_with_images(
            enhanced_prompt, query, system_prompt
        )

        # 4. Call VLM for question answering
        result = await self._call_vlm_with_multimodal_content(messages)

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
        self.logger.info(f"Found {len(matches)} image path matches in prompt")

        def replace_image_path(match):
            nonlocal images_processed

            image_path = match.group(1).strip()
            self.logger.debug(f"Processing image path: '{image_path}'")

            # Validate path format (basic check)
            if not image_path or len(image_path) < 3:
                self.logger.warning(f"Invalid image path format: {image_path}")
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
                    self.logger.warning(
                        f"Blocking image path outside safe directories: {image_path}"
                    )
                    is_valid = False

            if not is_valid:
                self.logger.warning(
                    f"Image validation failed or path unsafe for: {image_path}"
                )
                return match.group(0)  # Keep original if validation fails

            try:
                # Encode image to base64 using utility function
                self.logger.debug(f"Attempting to encode image: {image_path}")
                image_base64 = encode_image_to_base64(image_path)
                if image_base64:
                    images_processed += 1
                    # Save base64 to instance variable for later use
                    self._current_images_base64.append(image_base64)

                    # Keep original path info and add VLM marker
                    result = f"Image Path: {image_path}\n[VLM_IMAGE_{images_processed}]"
                    self.logger.debug(
                        f"Successfully processed image {images_processed}: {image_path}"
                    )
                    return result
                else:
                    self.logger.error(f"Failed to encode image: {image_path}")
                    return match.group(0)  # Keep original if encoding failed

            except Exception as e:
                self.logger.error(f"Failed to process image {image_path}: {e}")
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


# ═══════════════════════════════════════════════════════════
# Rerank & Query Rewriting (独立工具函数)
# ═══════════════════════════════════════════════════════════


async def rerank_chunks(
    query: str,
    chunks: list[str],
    api_key: str = "",
    top_n: int = 10,
    model: str = "qwen3-rerank",
    base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
) -> list[tuple[int, str]]:
    """
    使用 DashScope Rerank API 对检索结果进行精排。

    默认使用 qwen3-rerank 模型，通过阿里云 DashScope 原生 rerank API。
    失败时返回原始顺序，不影响主流程。

    Returns:
        [(原始索引, chunk内容), ...] 按相关性降序
    """
    if not chunks or len(chunks) <= 1:
        return [(i, c) for i, c in enumerate(chunks)]

    import aiohttp

    payload = {
        "model": model,
        "input": {
            "query": query,
            "documents": [c[:500] for c in chunks],  # 截断避免超长
        },
        "parameters": {"top_n": min(top_n, len(chunks)), "return_documents": False},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Rerank API error {resp.status}: {text[:200]}")

                data = await resp.json()
                results = data.get("output", {}).get("results", [])

                # results = [{"index": 2, "relevance_score": 0.77}, ...]
                ranked = []
                seen = set()
                for item in sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True):
                    idx = item["index"]
                    if idx < len(chunks) and idx not in seen:
                        ranked.append((idx, chunks[idx]))
                        seen.add(idx)

                # 追加未被 rerank 返回的 chunk（排最后）
                for i, c in enumerate(chunks):
                    if i not in seen:
                        ranked.append((i, c))

                return ranked[:top_n]
    except Exception as e:
        import logging
        logging.getLogger("raganything").warning(f"Rerank failed, using original order: {e}")
        return [(i, c) for i, c in enumerate(chunks)][:top_n]


async def rewrite_query(
    query: str,
    llm_model_func,
    history: list[dict] = None,
    api_key: str = "",
    base_url: str = "",
) -> str:
    """
    查询改写：使用 LLM 将自然语言查询优化为更适合检索的表述。
    支持基于对话历史的上下文改写。

    Returns:
        改写后的查询字符串
    """
    history_context = ""
    if history:
        recent = history[-3:]  # 最近 3 轮
        history_context = "\n".join(
            f"用户: {h.get('content', '')[:100]}" for h in recent if h.get("role") == "user"
        )

    prompt = f"""你是查询优化助手。将用户的自然语言查询改写为更适合文档检索的表述。
规则：
1. 补充省略的上下文（如指代词"这个""它"替换为具体名词）
2. 扩展缩写和专业术语
3. 保持原意，不添加新信息
4. 只输出改写后的查询，不要解释

{"对话历史: " + history_context if history_context else ""}
原始查询: {query}

改写后的查询:"""

    try:
        from lightrag.llm.openai import openai_complete_if_cache

        response = await openai_complete_if_cache(
            "qwen-plus", prompt, system_prompt="你是查询优化助手。",
            api_key=api_key, base_url=base_url, max_tokens=200, temperature=0.3,
        )
        if response and isinstance(response, str) and len(response.strip()) > 2:
            return response.strip()
    except Exception:
        pass
    return query  # 改写失败时返回原查询
