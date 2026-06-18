"""
Document processing functionality for RAGAnything

Contains methods for parsing documents and processing multimodal content
"""

from __future__ import annotations

import os
import time
import hashlib
import json
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path

from raganything.base import DocStatus
from raganything.parser import MineruParser, MineruExecutionError, get_parser
from raganything.utils import (
    separate_content,
    insert_text_content,
    insert_text_content_with_multimodal_content,
    get_processor_for_type,
    get_equation_text_and_format,
    get_table_body,
    normalize_caption_list,
)
import asyncio
from lightrag.utils import compute_mdhash_id



class ChunkProcessorMixin:
    """Chunk-to-document source mapping and BM25 index management."""
    # Batch debounce: coalesce multiple index rebuilds within 500ms
    _bm25_rebuild_timer: Any = None
    _bm25_pending_chunks: List[Dict[str, Any]] = []

    # to prevent class-level state leaking across KB instances.
    def _schedule_bm25_index_update(self, new_chunks: List[Dict[str, Any]] = None):
        """Schedule a BM25 index rebuild with 500ms debounce.

        Multiple rapid insertions are coalesced into a single rebuild.
        """
        import asyncio as _asyncio

        hybrid_engine = getattr(self, "hybrid_search_engine", None)
        if hybrid_engine is None:
            return

        # Accumulate pending chunks
        if new_chunks:
            self._bm25_pending_chunks.extend(new_chunks)

        # Cancel existing timer (debounce)
        if self._bm25_rebuild_timer is not None:
            self._bm25_rebuild_timer.cancel()

        # Schedule a single rebuild after 500ms
        async def _do_rebuild():
            await _asyncio.sleep(0.5)
            engine = getattr(self, "hybrid_search_engine", None)
            if engine is None:
                return
            pending = list(self._bm25_pending_chunks)
            self._bm25_pending_chunks = []
            if pending:
                await engine.update_bm25_index(pending)
            self._bm25_rebuild_timer = None

        try:
            loop = _asyncio.get_running_loop()
            self._bm25_rebuild_timer = loop.create_task(_do_rebuild())
        except RuntimeError:
            pass  # No event loop available, skip

    def _get_file_reference(self, file_path: str) -> str:
        """
        Get file reference based on use_full_path configuration.

        Args:
            file_path: Path to the file (can be absolute or relative)

        Returns:
            str: Full path if use_full_path is True, otherwise basename
        """
        if self.config.use_full_path:
            return str(file_path)
        else:
            return os.path.basename(file_path)

    def _register_chunk_sources(
        self, doc_id: str, file_path: str, chunk_ids: List[str]
    ):
        """Register chunk_id → document source mappings in the cache.

        Called whenever chunks are associated with a document during processing.
        This populates the reverse index used by get_doc_source_info.

        Args:
            doc_id: The document ID
            file_path: The source file path
            chunk_ids: List of chunk IDs belonging to this document
        """
        # Instance-level initialization (not class-level — avoids cross-instance leakage)
        if not hasattr(self, '_chunk_source_cache'):
            self._chunk_source_cache = {}
        document_name = self._get_file_reference(file_path)
        for chunk_id in chunk_ids:
            self._chunk_source_cache[chunk_id] = {
                "file_path": file_path,
                "document_name": document_name,
            }

    async def _ensure_chunk_source_cache(self):
        """Lazily build the chunk → doc source cache from doc_status records.

        This is a fallback for chunks that were processed before the cache was
        introduced, or for chunks added by LightRAG's internal mechanisms.

        Uses instance-level state (not class-level) to ensure each KB instance
        builds its own cache independently.
        """
        # Instance-level initialization (not class-level — avoids cross-instance leakage)
        if not hasattr(self, '_chunk_source_cache'):
            self._chunk_source_cache: Dict[str, Dict[str, str]] = {}
        if not hasattr(self, '_chunk_source_cache_built'):
            self._chunk_source_cache_built: bool = False

        if self._chunk_source_cache_built:
            return

        success = False
        try:
            # Access all doc_status records via the kv store's internal _data
            doc_status_store = self.lightrag.doc_status
            if hasattr(doc_status_store, '_data'):
                async with doc_status_store._storage_lock:
                    all_data = dict(doc_status_store._data)
            else:
                all_data = {}

            for doc_id, status in all_data.items():
                file_path = status.get("file_path", "")
                chunks_list = status.get("chunks_list", [])
                if file_path and chunks_list:
                    document_name = self._get_file_reference(file_path)
                    for chunk_id in chunks_list:
                        if chunk_id not in self._chunk_source_cache:
                            self._chunk_source_cache[chunk_id] = {
                                "file_path": file_path,
                                "document_name": document_name,
                            }
            success = True
        except Exception:
            pass  # Non-critical; source tracing degrades gracefully

        # Only mark as built on success — retry next time on failure
        if success:
            self._chunk_source_cache_built = True

    def get_doc_source_info(self, chunk_id: str) -> Dict[str, Any]:
        """Get source document info for a single chunk.

        Args:
            chunk_id: The chunk ID to look up

        Returns:
            Dict with file_path, document_name, or None values if not found
        """
        cache = getattr(self, '_chunk_source_cache', {})
        cached = cache.get(chunk_id)
        if cached:
            return {**cached}
        return {"file_path": None, "document_name": None}

    async def get_doc_source_info_async(self, chunk_id: str) -> Dict[str, Any]:
        """Async version that triggers cache build if needed.

        Args:
            chunk_id: The chunk ID to look up

        Returns:
            Dict with file_path, document_name, or None values if not found
        """
        cache = getattr(self, '_chunk_source_cache', {})
        built = getattr(self, '_chunk_source_cache_built', False)
        if chunk_id not in cache and not built:
            await self._ensure_chunk_source_cache()
        return self.get_doc_source_info(chunk_id)

    def batch_get_doc_source_info(
        self, chunk_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get source document info for multiple chunks in a single call.

        Args:
            chunk_ids: List of chunk IDs to look up

        Returns:
            Dict mapping chunk_id → {file_path, document_name}
            Unresolved chunk_ids are included with None values
        """
        result = {}
        for cid in chunk_ids:
            result[cid] = self.get_doc_source_info(cid)
        return result

    async def batch_get_doc_source_info_async(
        self, chunk_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Async version that triggers cache build if needed.

        Args:
            chunk_ids: List of chunk IDs to look up

        Returns:
            Dict mapping chunk_id → {file_path, document_name}
        """
        built = getattr(self, '_chunk_source_cache_built', False)
        if not built:
            await self._ensure_chunk_source_cache()
        return self.batch_get_doc_source_info(chunk_ids)
    def _convert_to_lightrag_chunks_type_aware(
        self, multimodal_data_list: List[Dict[str, Any]], file_path: str, doc_id: str
    ) -> Dict[str, Any]:
        """Convert multimodal data to LightRAG standard chunks format"""

        chunks = {}

        for data in multimodal_data_list:
            description = data["description"]
            entity_info = data["entity_info"]
            chunk_order_index = data["chunk_order_index"]
            content_type = data["content_type"]
            original_item = data["original_item"]

            # Apply the appropriate chunk template based on content type
            formatted_chunk_content = self._apply_chunk_template(
                content_type, original_item, description
            )

            # Calculate tokens
            tokens = len(self.lightrag.tokenizer.encode(formatted_chunk_content))

            # Truncate content exceeding the embedding model's input limit.
            # NOTE: LightRAG uses o200k_base (gpt-4o-mini) tokenizer which
            # counts ~2× fewer tokens for Chinese text than the actual qwen
            # embedding API.  Using a character-based limit avoids this mismatch.
            # 8000 chars keeps qwen well under its 8192-token ceiling even for
            # all-Chinese content (~1 char/token worst case).
            _MAX_CHUNK_CHARS = 8000
            if len(formatted_chunk_content) > _MAX_CHUNK_CHARS:
                formatted_chunk_content = (
                    formatted_chunk_content[:_MAX_CHUNK_CHARS]
                    + "\n\n[内容已截断，超出嵌入模型长度限制]"
                )
                tokens = len(
                    self.lightrag.tokenizer.encode(formatted_chunk_content)
                )
                self.logger.warning(
                    f"Truncated multimodal chunk: "
                    f"{len(formatted_chunk_content)} chars, {tokens} tokens "
                    f"(content_type={content_type})"
                )

            # Generate chunk_id from the (possibly truncated) content
            chunk_id = compute_mdhash_id(formatted_chunk_content, prefix="chunk-")

            # Use full path or basename based on config
            file_ref = self._get_file_reference(file_path)

            # Build LightRAG standard chunk format
            chunks[chunk_id] = {
                "content": formatted_chunk_content,  # Now uses the templated content
                "tokens": tokens,
                "full_doc_id": doc_id,
                "chunk_order_index": chunk_order_index,
                "file_path": file_ref,
                "llm_cache_list": [],  # LightRAG will populate this field
                # Multimodal-specific metadata
                "is_multimodal": True,
                "modal_entity_name": entity_info["entity_name"],
                "original_type": data["content_type"],
                "page_idx": data["item_info"].get("page_idx", 0),
            }

        self.logger.debug(
            f"Converted {len(chunks)} multimodal items to multimodal chunks format"
        )
        return chunks

    def _apply_chunk_template(
        self, content_type: str, original_item: Dict[str, Any], description: str
    ) -> str:
        """
        Apply the appropriate chunk template based on content type

        Args:
            content_type: Type of content (image, table, equation, generic)
            original_item: Original multimodal item data
            description: Enhanced description generated by the processor

        Returns:
            Formatted chunk content using the appropriate template
        """
        from raganything.prompt import PROMPTS

        try:
            if content_type == "image":
                image_path = original_item.get("img_path", "")
                captions = normalize_caption_list(
                    original_item.get(
                        "image_caption", original_item.get("img_caption", [])
                    )
                )
                footnotes = normalize_caption_list(
                    original_item.get(
                        "image_footnote", original_item.get("img_footnote", [])
                    )
                )
                section_path = original_item.get("_section_path", "")
                neighbor_text = original_item.get("_neighbor_text", "")

                return PROMPTS["image_chunk"].format(
                    section_path=section_path if section_path else "None",
                    neighbor_text=neighbor_text if neighbor_text else "None",
                    image_path=image_path,
                    captions=", ".join(captions) if captions else "None",
                    footnotes=", ".join(footnotes) if footnotes else "None",
                    enhanced_caption=description,
                )

            elif content_type == "table":
                table_img_path = original_item.get("img_path", "")
                table_caption = normalize_caption_list(
                    original_item.get("table_caption", [])
                )
                table_footnote = normalize_caption_list(
                    original_item.get("table_footnote", [])
                )
                # Simplify table body: strip bbox noise, keep text + position
                from raganything.utils import simplify_table_body as _simplify_table

                raw_body = get_table_body(original_item)
                table_body = _simplify_table(raw_body)

                return PROMPTS["table_chunk"].format(
                    table_img_path=table_img_path,
                    table_caption=", ".join(table_caption) if table_caption else "None",
                    table_body=table_body,
                    table_footnote=", ".join(table_footnote)
                    if table_footnote
                    else "None",
                    enhanced_caption=description,
                )

            elif content_type == "equation":
                equation_text, equation_format = get_equation_text_and_format(
                    original_item
                )

                return PROMPTS["equation_chunk"].format(
                    equation_text=equation_text,
                    equation_format=equation_format,
                    enhanced_caption=description,
                )

            elif content_type == "video":
                video_path = original_item.get("video_path", "")
                duration = original_item.get("duration", 0)
                frame_count = original_item.get("frame_count", "unknown")

                return PROMPTS["video_chunk"].format(
                    video_path=video_path,
                    duration=str(duration),
                    frame_count=str(frame_count),
                    transcript_summary=description[:200] + "..."
                    if len(description) > 200
                    else description,
                    enhanced_caption=description,
                )

            else:  # generic or unknown types
                content = str(original_item.get("content", original_item))

                return PROMPTS["generic_chunk"].format(
                    content_type=content_type.title(),
                    content=content,
                    enhanced_caption=description,
                )

        except Exception as e:
            self.logger.warning(
                f"Error applying chunk template for {content_type}: {e}"
            )
            # Fallback to just the description if template fails
            return description
    async def _update_doc_status_with_chunks_type_aware(
        self, doc_id: str, chunk_ids: List[str]
    ):
        """Update document status with multimodal chunks"""
        try:
            # Get current document status
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)

            # Register chunk → doc source mappings for citation tracing
            file_path = current_doc_status.get("file_path", "") if current_doc_status else ""
            if file_path and chunk_ids:
                self._register_chunk_sources(doc_id, file_path, chunk_ids)

            if current_doc_status:
                existing_chunks_list = current_doc_status.get("chunks_list", [])
                existing_chunks_count = current_doc_status.get("chunks_count", 0)

                # Add multimodal chunks to the standard chunks_list
                updated_chunks_list = existing_chunks_list + chunk_ids
                updated_chunks_count = existing_chunks_count + len(chunk_ids)

                # Update document status with integrated chunk list
                await self.lightrag.doc_status.upsert(
                    {
                        doc_id: {
                            **current_doc_status,  # Keep existing fields
                            "chunks_list": updated_chunks_list,  # Integrated chunks list
                            "chunks_count": updated_chunks_count,  # Updated total count
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                        }
                    }
                )

                # Ensure doc_status update is persisted to disk
                await self.lightrag.doc_status.index_done_callback()

                self.logger.info(
                    f"Updated doc_status: added {len(chunk_ids)} multimodal chunks to standard chunks_list "
                    f"(total chunks: {updated_chunks_count})"
                )

        except Exception as e:
            self.logger.warning(
                f"Error updating doc_status with multimodal chunks: {e}"
            )
