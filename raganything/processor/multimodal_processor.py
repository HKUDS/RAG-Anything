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
)
import asyncio
from lightrag.utils import compute_mdhash_id



class MultimodalProcessorMixin:
    """Multimodal content processing and document status queries."""
    async def _get_multimodal_status_record(self, doc_id: str) -> Dict[str, Any] | None:
        """Get compatibility multimodal completion state when doc_status cannot store it."""
        if (
            not hasattr(self, "multimodal_status_cache")
            or self.multimodal_status_cache is None
        ):
            return None

        return await self.multimodal_status_cache.get_by_id(doc_id)

    async def _set_multimodal_status_record(self, doc_id: str, processed: bool) -> None:
        """Persist multimodal completion state in a separate KV namespace."""
        if (
            not hasattr(self, "multimodal_status_cache")
            or self.multimodal_status_cache is None
        ):
            return

        await self.multimodal_status_cache.upsert(
            {
                doc_id: {
                    "multimodal_processed": processed,
                    "updated_at": self._current_doc_status_timestamp(),
                }
            }
        )
        await self.multimodal_status_cache.index_done_callback()

    async def _get_multimodal_processed_flag(
        self, doc_id: str, doc_status: Dict[str, Any] | None = None
    ) -> bool:
        """Read multimodal completion state from doc_status or compatibility cache."""
        if doc_status is not None and "multimodal_processed" in doc_status:
            return bool(doc_status.get("multimodal_processed", False))

        compatibility_status = await self._get_multimodal_status_record(doc_id)
        if compatibility_status is not None:
            return bool(compatibility_status.get("multimodal_processed", False))

        return False
    async def _process_multimodal_content(
        self,
        multimodal_items: List[Dict[str, Any]],
        file_path: str,
        doc_id: str,
        pipeline_status: Optional[Any] = None,
        pipeline_status_lock: Optional[Any] = None,
    ):
        """
        Process multimodal content (using specialized processors)

        Args:
            multimodal_items: List of multimodal items
            file_path: File path (for reference)
            doc_id: Document ID for proper chunk association
            pipeline_status: Pipeline status object
            pipeline_status_lock: Pipeline status lock
        """

        if not multimodal_items:
            self.logger.debug("No multimodal content to process")
            return

        callback_manager = getattr(self, "callback_manager", None)
        mm_start_time = time.time()
        if callback_manager is not None:
            callback_manager.dispatch(
                "on_multimodal_start",
                file_path=file_path,
                item_count=len(multimodal_items),
                doc_id=doc_id,
            )

        # Ensure LightRAG is initialized before accessing its storages
        init_result = await self._ensure_lightrag_initialized()
        if not init_result or not init_result.get("success"):
            self.logger.error(
                "LightRAG initialization failed; skipping multimodal processing"
            )
            return

        # Check multimodal processing status - handle LightRAG's early DocStatus.PROCESSED marking
        try:
            existing_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if existing_doc_status:
                # Check if multimodal content is already processed
                multimodal_processed = await self._get_multimodal_processed_flag(
                    doc_id, existing_doc_status
                )

                if multimodal_processed:
                    self.logger.info(
                        f"Document {doc_id} multimodal content is already processed"
                    )
                    return

                # Even if status is DocStatus.PROCESSED (text processing done),
                # we still need to process multimodal content if not yet done
                doc_status = existing_doc_status.get("status", "")
                if doc_status == DocStatus.PROCESSED and not multimodal_processed:
                    self.logger.info(
                        f"Document {doc_id} text processing is complete, but multimodal content still needs processing"
                    )
                    # Continue with multimodal processing
                elif doc_status == DocStatus.PROCESSED and multimodal_processed:
                    self.logger.info(
                        f"Document {doc_id} is fully processed (text + multimodal)"
                    )
                    return

        except Exception as e:
            self.logger.debug(f"Error checking document status for {doc_id}: {e}")
            # Continue with processing if cache check fails

        # Use ProcessorMixin's own batch processing that can handle multiple content types
        log_message = "Starting multimodal content processing..."
        self.logger.info(log_message)
        if pipeline_status_lock and pipeline_status:
            async with pipeline_status_lock:
                pipeline_status["latest_message"] = log_message
                pipeline_status["history_messages"].append(log_message)

        try:
            await self._process_multimodal_content_batch_type_aware(
                multimodal_items=multimodal_items, file_path=file_path, doc_id=doc_id
            )

            # Mark multimodal content as processed and update final status
            await self._mark_multimodal_processing_complete(doc_id)

            log_message = "Multimodal content processing complete"
            self.logger.info(log_message)
            if pipeline_status_lock and pipeline_status:
                async with pipeline_status_lock:
                    pipeline_status["latest_message"] = log_message
                    pipeline_status["history_messages"].append(log_message)

            if callback_manager is not None:
                duration = time.time() - mm_start_time
                callback_manager.dispatch(
                    "on_multimodal_complete",
                    file_path=file_path,
                    processed_count=len(multimodal_items),
                    duration_seconds=duration,
                    doc_id=doc_id,
                )

        except Exception as e:
            self.logger.error(f"Error in multimodal processing: {e}")
            # Step 1: Retry in smaller batches (4 per batch) before individual fallback
            try:
                self.logger.warning("Retrying multimodal processing in small batches (4/batch)")
                batch_size = 4
                for batch_start in range(0, len(multimodal_items), batch_size):
                    batch_items = multimodal_items[batch_start:batch_start + batch_size]
                    await self._process_multimodal_content_batch_type_aware(
                        batch_items, file_path, doc_id
                    )
            except Exception as e2:
                self.logger.error(f"Batch retry also failed: {e2}")
                self.logger.warning("Falling back to individual multimodal processing")
                await self._process_multimodal_content_individual(
                    multimodal_items, file_path, doc_id
                )

            # Mark multimodal content as processed even after fallback
            await self._mark_multimodal_processing_complete(doc_id)

    async def _process_multimodal_content_background(
        self,
        multimodal_items: List[Dict[str, Any]],
        file_ref: str,
        doc_id: str,
    ):
        """Background task: process multimodal content without blocking document insertion.

        Runs VLM/LLM calls asynchronously, marks completion when done.
        Failures are logged but don't affect the document's 'processed' status.
        """
        try:
            self.logger.info(
                f"Background multimodal processing started: {len(multimodal_items)} items for doc {doc_id}"
            )
            await self._process_multimodal_content(
                multimodal_items, file_ref, doc_id
            )
            self.logger.info(
                f"Background multimodal processing completed for doc {doc_id}"
            )
        except Exception as exc:
            self.logger.error(
                f"Background multimodal processing failed for doc {doc_id}: {exc}"
            )
        finally:
            try:
                await self._mark_multimodal_processing_complete(doc_id)
            except Exception as exc:
                self.logger.error(
                    f"Failed to mark multimodal complete for doc {doc_id}: {exc}"
                )

    async def _process_multimodal_content_individual(
        self, multimodal_items: List[Dict[str, Any]], file_path: str, doc_id: str
    ):
        """
        Process multimodal content individually (fallback method)

        Args:
            multimodal_items: List of multimodal items
            file_path: File path (for reference)
            doc_id: Document ID for proper chunk association
        """
        # Use full path or basename based on config
        file_name = self._get_file_reference(file_path)

        # Collect all chunk results for batch processing (similar to text content processing)
        all_chunk_results = []
        multimodal_chunk_ids = []

        # Get current text chunks count to set proper order indexes for multimodal chunks
        existing_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
        existing_chunks_count = (
            existing_doc_status.get("chunks_count", 0) if existing_doc_status else 0
        )

        for i, item in enumerate(multimodal_items):
            try:
                content_type = item.get("type", "unknown")
                self.logger.info(
                    f"Processing item {i + 1}/{len(multimodal_items)}: {content_type} content"
                )

                # Select appropriate processor
                processor = get_processor_for_type(self.modal_processors, content_type)

                if processor:
                    # Prepare item info for context extraction
                    item_info = {
                        "page_idx": item.get("page_idx", 0),
                        "index": item.get("_content_list_index", i),
                        "type": content_type,
                    }

                    # Process content and get chunk results instead of immediately merging
                    (
                        _,
                        entity_info,
                        chunk_results,
                    ) = await processor.process_multimodal_content(
                        modal_content=item,
                        content_type=content_type,
                        file_path=file_name,
                        item_info=item_info,  # Pass item info for context extraction
                        batch_mode=True,
                        doc_id=doc_id,  # Pass doc_id for proper association
                        chunk_order_index=existing_chunks_count
                        + i,  # Proper order index
                    )

                    # Collect chunk results for batch processing
                    all_chunk_results.extend(chunk_results)

                    # Extract chunk ID from the entity_info (actual chunk_id created by processor)
                    if entity_info and "chunk_id" in entity_info:
                        chunk_id = entity_info["chunk_id"]
                        multimodal_chunk_ids.append(chunk_id)

                    self.logger.info(
                        f"{content_type} processing complete: {entity_info.get('entity_name', 'Unknown')}"
                    )
                else:
                    self.logger.warning(
                        f"No suitable processor found for {content_type} type content"
                    )

            except Exception as e:
                self.logger.error(f"Error processing multimodal content: {str(e)}")
                self.logger.debug("Exception details:", exc_info=True)
                continue

        # Update doc_status to include multimodal chunks in the standard chunks_list
        if multimodal_chunk_ids:
            try:
                # Get current document status
                current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)

                if current_doc_status:
                    existing_chunks_list = current_doc_status.get("chunks_list", [])
                    existing_chunks_count = current_doc_status.get("chunks_count", 0)

                    # Add multimodal chunks to the standard chunks_list
                    updated_chunks_list = existing_chunks_list + multimodal_chunk_ids
                    updated_chunks_count = existing_chunks_count + len(
                        multimodal_chunk_ids
                    )

                    # Update document status with integrated chunk list
                    await self.lightrag.doc_status.upsert(
                        {
                            doc_id: {
                                **current_doc_status,  # Keep existing fields
                                "chunks_list": updated_chunks_list,  # Integrated chunks list
                                "chunks_count": updated_chunks_count,  # Updated total count
                                "updated_at": beijing_now(),
                            }
                        }
                    )

                    # Ensure doc_status update is persisted to disk
                    await self.lightrag.doc_status.index_done_callback()

                    self.logger.info(
                        f"Updated doc_status with {len(multimodal_chunk_ids)} multimodal chunks integrated into chunks_list"
                    )

            except Exception as e:
                self.logger.warning(
                    f"Error updating doc_status with multimodal chunks: {e}"
                )

        # Batch merge all multimodal content results (similar to text content processing)
        if all_chunk_results:
            from lightrag.operate import merge_nodes_and_edges
            from lightrag.kg.shared_storage import (
                get_namespace_data,
                get_pipeline_status_lock,
            )

            # Get pipeline status and lock from shared storage
            pipeline_status = await get_namespace_data("pipeline_status")
            pipeline_status_lock = get_pipeline_status_lock()

            await merge_nodes_and_edges(
                chunk_results=all_chunk_results,
                knowledge_graph_inst=self.lightrag.chunk_entity_relation_graph,
                entity_vdb=self.lightrag.entities_vdb,
                relationships_vdb=self.lightrag.relationships_vdb,
                global_config=self.lightrag.__dict__,
                full_entities_storage=self.lightrag.full_entities,
                full_relations_storage=self.lightrag.full_relations,
                doc_id=doc_id,
                pipeline_status=pipeline_status,
                pipeline_status_lock=pipeline_status_lock,
                llm_response_cache=self.lightrag.llm_response_cache,
                entity_chunks_storage=self.lightrag.entity_chunks,
                relation_chunks_storage=self.lightrag.relation_chunks,
                current_file_number=1,
                total_files=1,
                file_path=file_name,
            )

            await self.lightrag._insert_done()

        self.logger.info("Individual multimodal content processing complete")

        # Mark multimodal content as processed
        await self._mark_multimodal_processing_complete(doc_id)

    async def _process_multimodal_content_batch_type_aware(
        self, multimodal_items: List[Dict[str, Any]], file_path: str, doc_id: str
    ):
        """
        Type-aware batch processing that selects correct processors based on content type.
        This is the corrected implementation that handles different modality types properly.

        Args:
            multimodal_items: List of multimodal items with different types
            file_path: File path for citation
            doc_id: Document ID for proper association
        """
        if not multimodal_items:
            self.logger.debug("No multimodal content to process")
            return

        # Get existing chunks count for proper order indexing
        try:
            existing_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            existing_chunks_count = (
                existing_doc_status.get("chunks_count", 0) if existing_doc_status else 0
            )
        except Exception:
            existing_chunks_count = 0

        # Concurrency control for VLM/LLM description generation.
        # Uses MULTIMODAL_MAX_CONCURRENT env var (default 8), capped by
        # LightRAG's llm_model_max_async so we don't overwhelm the HTTP pool.
        _mm_concurrency = int(os.getenv("MULTIMODAL_MAX_CONCURRENT", "8"))
        _llm_max_async = getattr(self.lightrag, "llm_model_max_async", None)
        if _llm_max_async is not None and _llm_max_async > 0:
            _mm_concurrency = max(1, min(_mm_concurrency, _llm_max_async))
        semaphore = asyncio.Semaphore(_mm_concurrency)

        # Progress tracking variables
        total_items = len(multimodal_items)
        completed_count = 0
        progress_lock = asyncio.Lock()

        # Log processing start
        self.logger.info(f"Starting to process {total_items} multimodal content items")

        # Stage 1: Concurrent generation of descriptions using correct processors for each type
        async def process_single_item_with_correct_processor(
            item: Dict[str, Any], index: int, file_path: str
        ):
            """Process single item using the correct processor for its type"""
            nonlocal completed_count
            async with semaphore:
                try:
                    content_type = item.get("type", "unknown")

                    # Select the correct processor based on content type
                    processor = get_processor_for_type(
                        self.modal_processors, content_type
                    )

                    item_info = {
                        "page_idx": item.get("page_idx", 0),
                        "index": item.get("_content_list_index", index),
                        "type": content_type,
                    }

                    if not processor:
                        self.logger.warning(
                            f"No processor found for type: {content_type} — "
                            f"检查 ENABLE_{content_type.upper()}_PROCESSING 环境变量"
                        )
                        # ── 图片路径保留（防御纵深）：即使没有处理器，
                        # 也创建最小 result 写入 "Image Path:" 行 ──
                        if content_type == "image":
                            img_path = item.get("img_path", "")
                            if img_path:
                                fallback_caption = item.get(
                                    "image_caption",
                                    item.get("img_caption", [])
                                )
                                caption_text = (
                                    fallback_caption[0] if isinstance(fallback_caption, list) and fallback_caption
                                    else str(fallback_caption) if fallback_caption else ""
                                )
                                return {
                                    "index": index,
                                    "content_type": "image",
                                    "description": f"Image Path: {img_path}\n[Image: {caption_text or img_path}]",
                                    "entity_info": {
                                        "entity_name": f"image_{index}",
                                        "entity_type": "image",
                                        "summary": caption_text or f"Image at {img_path}",
                                    },
                                    "original_item": item,
                                    "item_info": item_info,
                                    "chunk_order_index": existing_chunks_count + index,
                                    "processor": None,
                                    "file_path": file_path,
                                }
                        return None

                    # ── processor is not None, proceed with normal processing ──
                    # (item_info already defined above)

                    # Call the correct processor's description generation method
                    (
                        description,
                        entity_info,
                    ) = await processor.generate_description_only(
                        modal_content=item,
                        content_type=content_type,
                        item_info=item_info,
                        entity_name=None,  # Let LLM auto-generate
                    )

                    # Update progress (non-blocking)
                    async with progress_lock:
                        completed_count += 1
                        if (
                            completed_count % max(1, total_items // 10) == 0
                            or completed_count == total_items
                        ):
                            progress_percent = (completed_count / total_items) * 100
                            self.logger.info(
                                f"Multimodal chunk generation progress: {completed_count}/{total_items} ({progress_percent:.1f}%)"
                            )

                    return {
                        "index": index,
                        "content_type": content_type,
                        "description": description,
                        "entity_info": entity_info,
                        "original_item": item,
                        "item_info": item_info,
                        "chunk_order_index": existing_chunks_count + index,
                        "processor": processor,  # Keep reference to the processor used
                        "file_path": file_path,  # Add file_path to the result
                    }

                except Exception as e:
                    # Update progress even on error (non-blocking)
                    async with progress_lock:
                        completed_count += 1
                        if (
                            completed_count % max(1, total_items // 10) == 0
                            or completed_count == total_items
                        ):
                            progress_percent = (completed_count / total_items) * 100
                            self.logger.info(
                                f"Multimodal chunk generation progress: {completed_count}/{total_items} ({progress_percent:.1f}%)"
                            )

                    self.logger.error(
                        f"Error generating description for {content_type} item {index}: {e}"
                    )
                    return None

        # Process all items concurrently with correct processors
        tasks = [
            asyncio.create_task(
                process_single_item_with_correct_processor(item, i, file_path)
            )
            for i, item in enumerate(multimodal_items)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful results
        multimodal_data_list = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Task failed: {result}")
                continue
            if result is not None:
                multimodal_data_list.append(result)

        if not multimodal_data_list:
            self.logger.warning("No valid multimodal descriptions generated")
            return

        self.logger.info(
            f"Generated descriptions for {len(multimodal_data_list)}/{len(multimodal_items)} multimodal items using correct processors"
        )

        # Stage 2: Convert to LightRAG chunks format
        lightrag_chunks = self._convert_to_lightrag_chunks_type_aware(
            multimodal_data_list, file_path, doc_id
        )

        # Stage 3: Store chunks to LightRAG storage
        await self._store_chunks_to_lightrag_storage_type_aware(lightrag_chunks)

        # Stage 3.5: Store multimodal main entities to entities_vdb and full_entities
        await self._store_multimodal_main_entities(
            multimodal_data_list, lightrag_chunks, file_path, doc_id
        )

        # Track chunk IDs for doc_status update
        chunk_ids = list(lightrag_chunks.keys())

        # Stage 4: Use LightRAG's batch entity relation extraction
        chunk_results = await self._batch_extract_entities_lightrag_style_type_aware(
            lightrag_chunks
        )

        # Stage 5: Add belongs_to relations (multimodal-specific)
        enhanced_chunk_results = await self._batch_add_belongs_to_relations_type_aware(
            chunk_results, multimodal_data_list
        )

        # Stage 6: Use LightRAG's batch merge
        await self._batch_merge_lightrag_style_type_aware(
            enhanced_chunk_results, file_path, doc_id
        )

        # Stage 6.5: Connectivity filtering (remove low-degree entities)
        removed_count = await self._filter_low_degree_entities(doc_id)
        if removed_count > 0:
            self.logger.info(
                "Removed %d low-degree entities from knowledge graph", removed_count
            )

        # Stage 7: Update doc_status with integrated chunks_list
        await self._update_doc_status_with_chunks_type_aware(doc_id, chunk_ids)
    async def _mark_multimodal_processing_complete(self, doc_id: str):
        """Mark multimodal content processing as complete in the document status."""
        try:
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if current_doc_status:
                final_status = current_doc_status.get("status") or DocStatus.PROCESSED
                if final_status != DocStatus.FAILED:
                    final_status = DocStatus.PROCESSED
                update_payload = {
                    **current_doc_status,
                    "status": final_status,
                    "multimodal_processed": True,
                    "updated_at": self._current_doc_status_timestamp(),
                }
                try:
                    await self.lightrag.doc_status.upsert({doc_id: update_payload})
                except Exception as exc:
                    # Older LightRAG versions reject unknown doc_status fields such as
                    # multimodal_processed. Fall back to a schema-compatible status-only
                    # update so image-only and multimodal documents still complete.
                    self.logger.debug(
                        "Falling back to schema-compatible doc_status update for %s: %s",
                        doc_id,
                        exc,
                    )
                    fallback_payload = {
                        **current_doc_status,
                        "status": final_status,
                        "updated_at": self._current_doc_status_timestamp(),
                    }
                    await self.lightrag.doc_status.upsert({doc_id: fallback_payload})
                    await self._set_multimodal_status_record(doc_id, True)
                await self.lightrag.doc_status.index_done_callback()
                self.logger.debug(
                    f"Marked multimodal content processing as complete for document {doc_id}"
                )
        except Exception as e:
            self.logger.warning(
                f"Error marking multimodal processing as complete for document {doc_id}: {e}"
            )

    async def is_document_fully_processed(self, doc_id: str) -> bool:
        """
        Check if a document is fully processed (both text and multimodal content).

        Args:
            doc_id: Document ID to check

        Returns:
            bool: True if both text and multimodal content are processed
        """
        try:
            doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if not doc_status:
                return False

            text_processed = doc_status.get("status") == DocStatus.PROCESSED
            multimodal_processed = await self._get_multimodal_processed_flag(
                doc_id, doc_status
            )

            return text_processed and multimodal_processed

        except Exception as e:
            self.logger.error(
                f"Error checking document processing status for {doc_id}: {e}"
            )
            return False

    async def get_document_processing_status(self, doc_id: str) -> Dict[str, Any]:
        """
        Get detailed processing status for a document.

        Args:
            doc_id: Document ID to check

        Returns:
            Dict with processing status details
        """
        try:
            doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if not doc_status:
                return {
                    "exists": False,
                    "text_processed": False,
                    "multimodal_processed": False,
                    "fully_processed": False,
                    "chunks_count": 0,
                }

            text_processed = doc_status.get("status") == DocStatus.PROCESSED
            multimodal_processed = await self._get_multimodal_processed_flag(
                doc_id, doc_status
            )
            fully_processed = text_processed and multimodal_processed

            return {
                "exists": True,
                "text_processed": text_processed,
                "multimodal_processed": multimodal_processed,
                "fully_processed": fully_processed,
                "chunks_count": doc_status.get("chunks_count", 0),
                "chunks_list": doc_status.get("chunks_list", []),
                "status": doc_status.get("status", ""),
                "updated_at": doc_status.get("updated_at", ""),
                "raw_status": doc_status,
            }

        except Exception as e:
            self.logger.error(
                f"Error getting document processing status for {doc_id}: {e}"
            )
            return {
                "exists": False,
                "error": str(e),
                "text_processed": False,
                "multimodal_processed": False,
                "fully_processed": False,
                "chunks_count": 0,
            }
