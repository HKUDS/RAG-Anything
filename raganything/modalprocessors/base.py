# -*- coding: utf-8 -*-
"""
Base Modal Processor.

Layer: Core
Primary Responsibility: BaseModalProcessor — shared foundation for all modal
    processors. Provides JSON parsing, entity/chunk creation, context retrieval,
    and entity/relation extraction orchestration.
Key Dependencies: lightrag (LightRAG, storage, operate), raganything.prompt

Call chain: generate_description_only() → _create_entity_and_chunk()
    → _process_chunk_for_extraction() → extract_entities() → merge_nodes_and_edges()
"""

import asyncio
import base64
import inspect
import json
import os
import re
import time
from typing import Dict, Any, Tuple, List

from lightrag.utils import (
    logger,
    compute_mdhash_id,
)
from lightrag.lightrag import LightRAG
from dataclasses import asdict
from lightrag.kg.shared_storage import get_namespace_data, get_pipeline_status_lock
from lightrag.operate import extract_entities, merge_nodes_and_edges

from raganything.modalprocessors.context import ContextExtractor


_DEFAULT_MODAL_CAPTION_TIMEOUT = 90.0
_MAX_MODAL_CAPTION_TIMEOUT = 300.0


def _modal_caption_timeout_seconds() -> float:
    """Return a bounded timeout for non-critical modal description calls."""
    raw_timeout = os.getenv(
        "MULTIMODAL_CAPTION_TIMEOUT", str(_DEFAULT_MODAL_CAPTION_TIMEOUT)
    )
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid MULTIMODAL_CAPTION_TIMEOUT=%r; using %.0fs",
            raw_timeout,
            _DEFAULT_MODAL_CAPTION_TIMEOUT,
        )
        return _DEFAULT_MODAL_CAPTION_TIMEOUT

    if timeout <= 0:
        logger.warning(
            "MULTIMODAL_CAPTION_TIMEOUT must be positive; using %.0fs",
            _DEFAULT_MODAL_CAPTION_TIMEOUT,
        )
        return _DEFAULT_MODAL_CAPTION_TIMEOUT
    return min(timeout, _MAX_MODAL_CAPTION_TIMEOUT)


class BaseModalProcessor:
    """Base class for modal processors"""

    def __init__(
        self,
        lightrag: LightRAG,
        modal_caption_func,
        context_extractor: ContextExtractor = None,
    ):
        """Initialize base processor

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating descriptions
            context_extractor: Context extractor instance
        """
        self.lightrag = lightrag
        self.modal_caption_func = modal_caption_func

        # Use LightRAG's storage instances
        self.text_chunks_db = lightrag.text_chunks
        self.chunks_vdb = lightrag.chunks_vdb
        self.entities_vdb = lightrag.entities_vdb
        self.relationships_vdb = lightrag.relationships_vdb
        self.knowledge_graph_inst = lightrag.chunk_entity_relation_graph

        # Use LightRAG's configuration and functions
        self.embedding_func = lightrag.embedding_func
        self.llm_model_func = lightrag.llm_model_func
        self.global_config = asdict(lightrag)
        self.hashing_kv = lightrag.llm_response_cache
        self.tokenizer = lightrag.tokenizer

        # Initialize context extractor with tokenizer if not provided
        if context_extractor is None:
            self.context_extractor = ContextExtractor(tokenizer=self.tokenizer)
        else:
            self.context_extractor = context_extractor
            # Update tokenizer if context_extractor doesn't have one
            if self.context_extractor.tokenizer is None:
                self.context_extractor.tokenizer = self.tokenizer

        # Content source for context extraction
        self.content_source = None
        self.content_format = "auto"

    async def _call_modal_caption(self, *args, **kwargs):
        """Invoke a modal description provider without blocking ingestion indefinitely.

        Caption generation enriches a document but is not required for its core
        lifecycle. A stalled provider must therefore fall through to each
        processor's existing fallback instead of consuming the upload task's
        full timeout budget.
        """
        if self.modal_caption_func is None:
            raise RuntimeError("Modal caption function is not configured")

        result = self.modal_caption_func(*args, **kwargs)
        if not inspect.isawaitable(result):
            return result

        timeout = _modal_caption_timeout_seconds()
        try:
            return await asyncio.wait_for(result, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Modal caption generation timed out after %.1fs; using processor fallback",
                timeout,
            )
            raise

    def set_content_source(self, content_source: Any, content_format: str = "auto"):
        """Set content source for context extraction

        Args:
            content_source: Source content for context extraction
            content_format: Format of content source ("minerU", "text_chunks", "auto")
        """
        self.content_source = content_source
        self.content_format = content_format
        logger.info(f"Content source set with format: {content_format}")

    def _get_context_for_item(self, item_info: Dict[str, Any]) -> str:
        """Get context for current processing item

        Args:
            item_info: Information about current item (page_idx, index, etc.)

        Returns:
            Context text for the item
        """
        if not self.content_source:
            return ""

        try:
            context = self.context_extractor.extract_context(
                self.content_source, item_info, self.content_format
            )
            if context:
                logger.debug(
                    f"Extracted context of length {len(context)} for item: {item_info}"
                )
            return context
        except Exception as e:
            logger.error(f"Error getting context for item {item_info}: {e}")
            return ""

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
        doc_id: str = None,
        file_path: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate text description and entity info only, without entity relation extraction.
        Used for batch processing stage 1.

        Args:
            modal_content: Modal content to process
            content_type: Type of modal content
            item_info: Item information for context extraction
            entity_name: Optional predefined entity name
            doc_id: Optional document ID for entity association
            file_path: Optional source file path for citation

        Returns:
            Tuple of (description, entity_info)
        """
        raise NotImplementedError("Subclasses must implement this method")

    async def _create_entity_and_chunk(
        self,
        modal_chunk: str,
        entity_info: Dict[str, Any],
        file_path: str,
        batch_mode: bool = False,
        doc_id: str = None,
        chunk_order_index: int = 0,
        defer_flush: bool = False,
        defer_extraction: bool = False,
    ) -> Tuple[str, Dict[str, Any]]:
        """Create entity and text chunk"""
        # Truncate + hash via unified helper — ensures chunk_id matches
        # text_chunks_db key everywhere.  Never call compute_mdhash_id directly.
        from raganything.processor.chunk_processor import compute_chunk_id

        tokens = len(self.tokenizer.encode(str(modal_chunk)))
        if len(str(modal_chunk)) > 8000:
            modal_chunk = (
                str(modal_chunk)[:8000]
                + "\n\n[内容已截断，超出嵌入模型长度限制]"
            )
            tokens = len(self.tokenizer.encode(modal_chunk))
            logger.warning(
                f"Truncated multimodal chunk: "
                f"{len(str(modal_chunk))} chars, {tokens} tokens"
            )

        # Create chunk
        chunk_id = compute_chunk_id(str(modal_chunk))

        # Use provided doc_id or generate one from chunk_id for backward compatibility
        actual_doc_id = doc_id if doc_id else chunk_id

        chunk_data = {
            "tokens": tokens,
            "content": modal_chunk,
            "chunk_order_index": chunk_order_index,
            "full_doc_id": actual_doc_id,
            "file_path": file_path,
        }

        # Store chunk
        await self.text_chunks_db.upsert({chunk_id: chunk_data})

        # ── 持久化：确保 text_chunks 从内存刷到磁盘 ──
        # JsonKVStorage.upsert() 仅写入内存，index_done_callback() 才
        # 真正落盘。若不调用，服务器重启后所有多模态 chunk 数据丢失。
        # 注意：每次调用都会完整重写 JSON 文件；批量路径已在
        # _store_chunks_to_lightrag_storage_type_aware 中统一 flush，
        # v2 视频路径通过 defer_flush=True 跳过逐块落盘，最终由
        # 整文档 _insert_done() 一次性落盘。
        if not defer_flush:
            await self.text_chunks_db.index_done_callback()

        # Store chunk in vector database for retrieval
        chunk_vdb_data = {
            chunk_id: {
                "content": modal_chunk,
                "full_doc_id": actual_doc_id,
                "tokens": tokens,
                "chunk_order_index": chunk_order_index,
                "file_path": file_path,
            }
        }
        await self.chunks_vdb.upsert(chunk_vdb_data)

        # Create entity node
        node_data = {
            "entity_id": entity_info["entity_name"],
            "entity_type": entity_info["entity_type"],
            "description": entity_info["summary"],
            "source_id": chunk_id,
            "file_path": file_path,
            "created_at": int(time.time()),
        }

        await self.knowledge_graph_inst.upsert_node(
            entity_info["entity_name"], node_data
        )

        # Insert entity into vector database
        entity_vdb_data = {
            compute_mdhash_id(entity_info["entity_name"], prefix="ent-"): {
                "entity_name": entity_info["entity_name"],
                "entity_type": entity_info["entity_type"],
                "content": f"{entity_info['entity_name']}\n{entity_info['summary']}",
                "source_id": chunk_id,
                "file_path": file_path,
            }
        }
        await self.entities_vdb.upsert(entity_vdb_data)

        # Process entity and relationship extraction.  The v2 video path
        # defers extraction (defer_extraction=True) so independent segment
        # extractions can run concurrently and be timed separately.
        if defer_extraction:
            chunk_results = []
        else:
            chunk_results = await self._process_chunk_for_extraction(
                chunk_id, entity_info["entity_name"], batch_mode
            )

        return (
            entity_info["summary"],
            {
                "entity_name": entity_info["entity_name"],
                "entity_type": entity_info["entity_type"],
                "description": entity_info["summary"],
                "chunk_id": chunk_id,
            },
            chunk_results,
        )

    @staticmethod
    def _strip_thinking_tags(text: str) -> str:
        """Remove <think>/<thinking> tags produced by reasoning models.

        Models such as DeepSeek-R1 and Qwen2.5-think wrap their internal
        chain-of-thought in ``<think>…</think>`` or ``<thinking>…</thinking>``
        blocks before emitting the final answer.  When JSON parsing fails and
        the raw LLM response is used as a fallback, storing the entire response
        (including the reasoning preamble) pollutes the knowledge graph with
        internal model thoughts rather than actual content descriptions.

        This helper strips those blocks so that only the final answer text is
        stored or surfaced to callers.
        """
        import re as _re_strip

        cleaned = _re_strip.sub(
            r"<think>.*?</think>", "", text, flags=_re_strip.DOTALL | _re_strip.IGNORECASE
        )
        cleaned = _re_strip.sub(
            r"<thinking>.*?</thinking>", "", cleaned, flags=_re_strip.DOTALL | _re_strip.IGNORECASE
        )
        return cleaned.strip()

    def _parse_typed_response(
        self, response: str, entity_name: str | None, entity_type: str
    ) -> tuple:
        """Parse LLM/VLM response and return (description, entity_info).

        Shared by all modal processor subclasses.  Includes double-suffix
        prevention: if the LLM already returned "Foo (image)", the code will
        not append another "(image)" suffix.
        """
        response_data = self._robust_json_parse(response)

        description = response_data.get("detailed_description", "")
        entity_data = response_data.get("entity_info", {})

        if not description or not entity_data:
            raise ValueError("Missing required fields in response")

        if not all(
            key in entity_data for key in ["entity_name", "entity_type", "summary"]
        ):
            raise ValueError("Missing required fields in entity_info")

        # Prevent double suffix: if LLM already returned "Foo (image)",
        # don't make it "Foo (image) (image)"
        raw_name = entity_data["entity_name"]
        suffix = f" ({entity_data['entity_type']})"
        if not raw_name.endswith(suffix):
            entity_data["entity_name"] = raw_name + suffix

        if entity_name:
            entity_data["entity_name"] = entity_name

        return description, entity_data

    def _robust_json_parse(self, response: str) -> dict:
        """Robust JSON parsing with multiple fallback strategies"""

        # Strategy 1: Try direct parsing first
        for json_candidate in self._extract_all_json_candidates(response):
            result = self._try_parse_json(json_candidate)
            if result:
                return result

        # Strategy 2: Try with basic cleanup
        for json_candidate in self._extract_all_json_candidates(response):
            cleaned = self._basic_json_cleanup(json_candidate)
            result = self._try_parse_json(cleaned)
            if result:
                return result
            # Also try combining cleanup + quote fix (composed strategy)
            fixed = self._progressive_quote_fix(cleaned)
            result = self._try_parse_json(fixed)
            if result:
                return result

        # Strategy 3: Try progressive quote fixing (standalone)
        for json_candidate in self._extract_all_json_candidates(response):
            fixed = self._progressive_quote_fix(json_candidate)
            result = self._try_parse_json(fixed)
            if result:
                return result

        # Strategy 4: Fallback to regex field extraction
        return self._extract_fields_with_regex(response)

    def _extract_all_json_candidates(self, response: str) -> list:
        """Extract all possible JSON candidates from response"""
        candidates = []

        import re as _re_extract

        # Pre-process: Remove thinking/reasoning tags that some models use
        cleaned_response = _re_extract.sub(
            r"<think>.*?</think>", "", response, flags=_re_extract.DOTALL | _re_extract.IGNORECASE
        )
        cleaned_response = _re_extract.sub(
            r"<thinking>.*?</thinking>",
            "",
            cleaned_response,
            flags=_re_extract.DOTALL | _re_extract.IGNORECASE,
        )

        # Method 1: JSON in code blocks
        json_blocks = _re_extract.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```", cleaned_response, _re_extract.DOTALL
        )
        candidates.extend(json_blocks)

        # Method 2: Balanced braces
        brace_count = 0
        start_pos = -1

        for i, char in enumerate(cleaned_response):
            if char == "{":
                if brace_count == 0:
                    start_pos = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_pos != -1:
                    candidates.append(cleaned_response[start_pos : i + 1])

        # Method 3: Simple regex fallback
        simple_match = _re_extract.search(r"\{.*\}", cleaned_response, _re_extract.DOTALL)
        if simple_match:
            candidates.append(simple_match.group(0))

        return candidates

    def _try_parse_json(self, json_str: str) -> dict:
        """Try to parse JSON string, return None if failed"""
        if not json_str or not json_str.strip():
            return None

        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return None

    def _basic_json_cleanup(self, json_str: str) -> str:
        """Basic cleanup for common JSON issues"""
        # Remove extra whitespace
        json_str = json_str.strip()

        # Fix common quote issues
        json_str = json_str.replace('"', '"').replace('"', '"')  # Smart quotes
        json_str = json_str.replace(""", "'").replace(""", "'")  # Smart apostrophes

        # Fix trailing commas (simple case)
        json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)

        return json_str

    def _progressive_quote_fix(self, json_str: str) -> str:
        """Progressive fixing of quote and escape issues"""
        # Only escape unescaped backslashes before quotes
        json_str = re.sub(r'(?<!\\)\\(?=")', r"\\\\", json_str)

        # Fix unescaped backslashes in string values (more conservative)
        def fix_string_content(match):
            content = match.group(1)
            # Escape backslash-letter pairs that are NOT valid JSON escapes.
            # \n \t \r \b \f \u \/ \\ \" are valid — leave them alone.
            # \alpha \theta \beta etc. are LaTeX/domain escapes — double them.
            _VALID_JSON_ESCAPE = {'n', 't', 'r', 'b', 'f', 'u', '/', '\\', '"'}
            content = re.sub(
                r'\\([a-zA-Z])',
                lambda m: (
                    r'\\\\' if m.group(1) not in _VALID_JSON_ESCAPE
                    else m.group(0)
                ),
                content,
            )
            return f'"{content}"'

        json_str = re.sub(r'"([^"]*(?:\\.[^"]*)*)"', fix_string_content, json_str)
        return json_str

    def _extract_fields_with_regex(self, response: str) -> dict:
        """Extract required fields using regex as last resort.

        Uses atomic character-class alternation ``(?:[^\"\\\\]|\\\\.)*``
        instead of nested quantifiers to avoid catastrophic backtracking.
        """
        logger.warning("Using regex fallback for JSON parsing")

        # Strip thinking tags before regex extraction
        response = self._strip_thinking_tags(response)

        # Safe linear-time pattern: each character matches exactly one branch
        def _extract_field(field_name: str, text: str, default: str = "") -> str:
            pattern = rf'"{field_name}"\s*:\s*"((?:[^"\\]|\\.)*)"'
            match = re.search(pattern, text, re.DOTALL)
            return match.group(1) if match else default

        description = _extract_field("detailed_description", response)
        entity_name = _extract_field("entity_name", response, "unknown_entity")
        entity_type = _extract_field("entity_type", response, "unknown")
        summary = _extract_field("summary", response, description[:100] if description else "")

        return {
            "detailed_description": description,
            "entity_info": {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "summary": summary,
            },
        }

    def _extract_json_from_response(self, response: str) -> str:
        """Legacy method - now handled by _extract_all_json_candidates"""
        candidates = self._extract_all_json_candidates(response)
        return candidates[0] if candidates else None

    def _fix_json_escapes(self, json_str: str) -> str:
        """Legacy method - now handled by progressive strategies"""
        return self._progressive_quote_fix(json_str)

    async def _process_chunk_for_extraction(
        self, chunk_id: str, modal_entity_name: str, batch_mode: bool = False
    ):
        """Process chunk for entity and relationship extraction"""
        chunk_data = await self.text_chunks_db.get_by_id(chunk_id)
        if not chunk_data:
            logger.error(f"Chunk {chunk_id} not found")
            return

        # Create text chunk for vector database
        chunk_vdb_data = {
            chunk_id: {
                "content": chunk_data["content"],
                "full_doc_id": chunk_id,
                "tokens": chunk_data["tokens"],
                "chunk_order_index": chunk_data["chunk_order_index"],
                "file_path": chunk_data["file_path"],
            }
        }

        await self.chunks_vdb.upsert(chunk_vdb_data)

        pipeline_status = await get_namespace_data("pipeline_status")
        pipeline_status_lock = get_pipeline_status_lock()

        # Prepare chunk for extraction
        chunks = {chunk_id: chunk_data}

        # Extract entities and relationships
        chunk_results = await extract_entities(
            chunks=chunks,
            global_config=self.global_config,
            pipeline_status=pipeline_status,
            pipeline_status_lock=pipeline_status_lock,
            llm_response_cache=self.hashing_kv,
        )

        # Add "belongs_to" relationships for all extracted entities
        processed_chunk_results = []
        for maybe_nodes, maybe_edges in chunk_results:
            for entity_name in maybe_nodes.keys():
                if entity_name != modal_entity_name:  # Skip self-relationship
                    # Create belongs_to relationship
                    relation_data = {
                        "description": f"Entity {entity_name} belongs to {modal_entity_name}",
                        "keywords": "belongs_to,part_of,contained_in",
                        "source_id": chunk_id,
                        "weight": 10.0,
                        "file_path": chunk_data.get("file_path", "manual_creation"),
                    }
                    await self.knowledge_graph_inst.upsert_edge(
                        entity_name, modal_entity_name, relation_data
                    )

                    relation_id = compute_mdhash_id(
                        entity_name + modal_entity_name, prefix="rel-"
                    )
                    relation_vdb_data = {
                        relation_id: {
                            "src_id": entity_name,
                            "tgt_id": modal_entity_name,
                            "keywords": relation_data["keywords"],
                            "content": f"{relation_data['keywords']}\t{entity_name}\n{modal_entity_name}\n{relation_data['description']}",
                            "source_id": chunk_id,
                            "file_path": chunk_data.get("file_path", "manual_creation"),
                        }
                    }
                    await self.relationships_vdb.upsert(relation_vdb_data)

                    # Add to maybe_edges
                    maybe_edges[(entity_name, modal_entity_name)] = [relation_data]

            processed_chunk_results.append((maybe_nodes, maybe_edges))

        if not batch_mode:
            # Merge with correct file_path parameter
            file_path = chunk_data.get("file_path", "manual_creation")
            doc_id = chunk_data.get("full_doc_id")
            await merge_nodes_and_edges(
                chunk_results=chunk_results,
                knowledge_graph_inst=self.knowledge_graph_inst,
                entity_vdb=self.entities_vdb,
                relationships_vdb=self.relationships_vdb,
                global_config=self.global_config,
                full_entities_storage=self.lightrag.full_entities,
                full_relations_storage=self.lightrag.full_relations,
                doc_id=doc_id,
                pipeline_status=pipeline_status,
                pipeline_status_lock=pipeline_status_lock,
                llm_response_cache=self.hashing_kv,
                entity_chunks_storage=self.lightrag.entity_chunks,
                relation_chunks_storage=self.lightrag.relation_chunks,
                current_file_number=1,
                total_files=1,
                file_path=file_path,
            )

            # Ensure all storage updates are complete
            await self.lightrag._insert_done()

        return processed_chunk_results


__all__ = ["BaseModalProcessor"]
