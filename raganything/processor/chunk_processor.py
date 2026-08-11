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
    beijing_now,
    separate_content,
    insert_text_content,
    insert_text_content_with_multimodal_content,
    get_processor_for_type,
    get_equation_text_and_format,
    get_table_body,
    normalize_caption_list,
    display_document_name,
)
import asyncio
from lightrag.utils import compute_mdhash_id


# ── Unified chunk ID computation ──────────────────────────────
# ALL code paths MUST use this function — never compute_mdhash_id directly.
# This ensures the chunk_id key matches what is stored in text_chunks_db.

def compute_chunk_id(content: str) -> str:
    """Compute a deterministic chunk ID from content with truncation.

    Truncates content exceeding the embedding model's input limit before
    hashing, so the resulting chunk ID matches the key used in
    ``text_chunks_db``.

    Truncation note: LightRAG uses o200k_base (gpt-4o-mini) tokenizer
    which counts ~2× fewer tokens for Chinese text than the actual qwen
    embedding API.  Using a character-based limit avoids this mismatch.
    8000 chars keeps qwen well under its 8192-token ceiling even for
    all-Chinese content (~1 char/token worst case).
    """
    _MAX_CHUNK_CHARS = 8000
    if len(content) > _MAX_CHUNK_CHARS:
        content = content[:_MAX_CHUNK_CHARS] + "\n\n[内容已截断，超出嵌入模型长度限制]"
    return compute_mdhash_id(content, prefix="chunk-")


# TTL after which the chunk -> doc source cache is refreshed from the durable
# doc-status store so chunks added by other workers become visible.
_CHUNK_SOURCE_CACHE_TTL_SECONDS = 60.0


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
        document_name = display_document_name(file_path)
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
        if not hasattr(self, '_chunk_source_cache_lock'):
            self._chunk_source_cache_lock: asyncio.Lock = asyncio.Lock()

        if self._chunk_source_cache_fresh():
            return

        async with self._chunk_source_cache_lock:
            # Double-check under the lock: another coroutine may have rebuilt
            # the cache while we were waiting.
            if self._chunk_source_cache_fresh():
                return

            doc_status_store = self.lightrag.doc_status
            if getattr(doc_status_store, "db", None) is not None:
                rebuilt = await self._rebuild_chunk_source_cache_from_pg(
                    doc_status_store
                )
            else:
                rebuilt = await self._rebuild_chunk_source_cache_from_memory(
                    doc_status_store
                )

            # Only mark the cache as fresh on success — retry next time on failure
            if rebuilt:
                self._chunk_source_cache_built_at = time.monotonic()

    def _chunk_source_cache_fresh(self) -> bool:
        """Whether the chunk-source cache was rebuilt within the TTL window."""
        built_at = getattr(self, '_chunk_source_cache_built_at', 0.0)
        return (
            built_at > 0
            and (time.monotonic() - built_at) < _CHUNK_SOURCE_CACHE_TTL_SECONDS
        )

    async def _rebuild_chunk_source_cache_from_pg(self, doc_status_store) -> bool:
        """Rebuild chunk -> doc mappings from durable LIGHTRAG_DOC_STATUS rows."""
        try:
            workspace = getattr(doc_status_store, "workspace", "")
            sql = (
                "SELECT file_path, chunks_list FROM LIGHTRAG_DOC_STATUS "
                "WHERE workspace=$1 AND file_path <> '' AND chunks_list IS NOT NULL"
            )
            rows = await doc_status_store.db.query(
                sql, [workspace], multirows=True
            )
        except Exception:
            return False

        for row in rows or []:
            try:
                file_path = row.get("file_path", "")
                chunks_list = row.get("chunks_list")
                if isinstance(chunks_list, str):
                    try:
                        chunks_list = json.loads(chunks_list)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        chunks_list = []
                elif not isinstance(chunks_list, list):
                    chunks_list = []
                if not file_path or not chunks_list:
                    continue
                document_name = display_document_name(file_path)
                for chunk_id in chunks_list:
                    # Only fill missing mappings — never overwrite processing-time
                    # registrations made by _register_chunk_sources.
                    if chunk_id not in self._chunk_source_cache:
                        self._chunk_source_cache[chunk_id] = {
                            "file_path": file_path,
                            "document_name": document_name,
                        }
            except Exception:
                continue  # Skip a corrupt row without aborting the batch
        return True

    async def _rebuild_chunk_source_cache_from_memory(self, doc_status_store) -> bool:
        """Rebuild chunk -> doc mappings from the JSON store's in-memory _data."""
        try:
            data = getattr(doc_status_store, "_data", None)
            all_data = {}
            if data is not None:
                storage_lock = getattr(doc_status_store, "_storage_lock", None)
                if storage_lock is not None:
                    async with storage_lock:
                        all_data = dict(data)
                else:
                    all_data = dict(data)

            for doc_id, status in all_data.items():
                file_path = status.get("file_path", "")
                chunks_list = status.get("chunks_list", [])
                if file_path and chunks_list:
                    document_name = display_document_name(file_path)
                    for chunk_id in chunks_list:
                        if chunk_id not in self._chunk_source_cache:
                            self._chunk_source_cache[chunk_id] = {
                                "file_path": file_path,
                                "document_name": document_name,
                            }
            return True
        except Exception:
            return False  # Non-critical; source tracing degrades gracefully

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
        if chunk_id not in cache and not self._chunk_source_cache_fresh():
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
        if not self._chunk_source_cache_fresh():
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

            # Generate chunk_id via unified helper (includes truncation).
            # Always use _compute_chunk_id — never compute_mdhash_id directly —
            # so the resulting key matches text_chunks_db.
            _before = len(formatted_chunk_content)
            chunk_id = self._compute_chunk_id(formatted_chunk_content)
            if len(formatted_chunk_content) > 8000:
                formatted_chunk_content = (
                    formatted_chunk_content[:8000]
                    + "\n\n[内容已截断，超出嵌入模型长度限制]"
                )
                tokens = len(
                    self.lightrag.tokenizer.encode(formatted_chunk_content)
                )
                self.logger.warning(
                    f"Truncated multimodal chunk: "
                    f"{_before}→{len(formatted_chunk_content)} chars, {tokens} tokens "
                    f"(content_type={content_type})"
                )

            # Use full path or basename based on config
            file_ref = self._get_file_reference(file_path)
            media_path = (
                original_item.get("img_path")
                or original_item.get("video_path")
                or original_item.get("media_path")
                or ""
            )

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
                # PGKVStorage only persists its fixed schema. This value is
                # also copied into doc-status metadata for lossless API reads.
                "media_path": str(media_path),
            }

        self.logger.debug(
            f"Converted {len(chunks)} multimodal items to multimodal chunks format"
        )
        return chunks

    @staticmethod
    def _compute_chunk_id(content: str) -> str:
        """Compute a deterministic chunk ID from content (convenience wrapper).

        Delegates to the module-level :func:`compute_chunk_id` so every
        code path — whether inside or outside the mixin hierarchy — uses
        the same truncation + hash logic.
        """
        return compute_chunk_id(content)

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
                raise RuntimeError(
                    "Whole-video chunks are retired; video content must use v2 semantic segments"
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
        self,
        doc_id: str,
        chunk_ids: List[str],
        chunks: Dict[str, Any] | None = None,
    ) -> bool:
        """Update document status with multimodal chunks.

        The completion marker is only valid after this durable status update
        succeeds. Returning a boolean lets the caller keep an interrupted
        document out of the completed/tagging path when the status store is
        temporarily unavailable.
        """
        try:
            # Get current document status
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if not current_doc_status:
                self.logger.warning(
                    "Cannot update multimodal chunks: document status missing for %s",
                    doc_id,
                )
                return False

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

                # PGKVStorage's text-chunk schema intentionally retains only
                # LightRAG core fields. Preserve multimodal-only fields in the
                # durable doc-status metadata so /knowledge/.../chunks can
                # faithfully reconstruct the response after a PG round-trip.
                existing_metadata = current_doc_status.get("metadata") or {}
                metadata = dict(existing_metadata) if isinstance(existing_metadata, dict) else {}
                multimodal_chunks = metadata.get("multimodal_chunks") or {}
                multimodal_chunks = (
                    dict(multimodal_chunks)
                    if isinstance(multimodal_chunks, dict)
                    else {}
                )
                for chunk_id in chunk_ids:
                    chunk = (chunks or {}).get(chunk_id, {})
                    if not isinstance(chunk, dict):
                        continue
                    multimodal_chunks[chunk_id] = {
                        "is_multimodal": True,
                        "original_type": chunk.get("original_type"),
                        "modal_entity_name": chunk.get("modal_entity_name"),
                        "page_idx": chunk.get("page_idx"),
                        "media_path": chunk.get("media_path") or "",
                    }
                if multimodal_chunks:
                    metadata["multimodal_chunks"] = multimodal_chunks

                # Update document status with integrated chunk list
                await self.lightrag.doc_status.upsert(
                    {
                        doc_id: {
                            **current_doc_status,  # Keep existing fields
                            "chunks_list": updated_chunks_list,  # Integrated chunks list
                            "chunks_count": updated_chunks_count,  # Updated total count
                            "metadata": metadata,
                            "updated_at": beijing_now(),
                        }
                    }
                )

                # Ensure doc_status update is persisted to disk
                await self.lightrag.doc_status.index_done_callback()

                self.logger.info(
                    f"Updated doc_status: added {len(chunk_ids)} multimodal chunks to standard chunks_list "
                    f"(total chunks: {updated_chunks_count})"
                )
                return True

        except Exception as e:
            self.logger.warning(
                f"Error updating doc_status with multimodal chunks: {e}"
            )
        return False
