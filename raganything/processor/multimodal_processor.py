"""
Document processing functionality for RAGAnything

Contains methods for parsing documents and processing multimodal content
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Any, Optional

from raganything.base import DocStatus
from raganything.utils import (
    beijing_now,
    get_processor_for_type,
    is_multimodal_processed,
)
import asyncio



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

    async def _set_multimodal_status_record(self, doc_id: str, processed: bool) -> bool:
        """Persist multimodal completion state in doc-status metadata when possible."""
        try:
            doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if doc_status:
                existing_metadata = doc_status.get("metadata") or {}
                metadata = (
                    dict(existing_metadata)
                    if isinstance(existing_metadata, dict)
                    else {}
                )
                metadata["multimodal_processed"] = processed
                await self.lightrag.doc_status.upsert(
                    {
                        doc_id: {
                            **doc_status,
                            "metadata": metadata,
                            "updated_at": self._current_doc_status_timestamp(),
                        }
                    }
                )
                await self.lightrag.doc_status.index_done_callback()
                return True
        except Exception as exc:
            self.logger.debug(
                "Unable to persist multimodal status in doc metadata for %s: %s",
                doc_id,
                exc,
            )

        # Legacy non-PG backend fallback. This is intentionally optional: PGKV
        # cannot store arbitrary namespaces, so it may be unavailable.
        if (
            not hasattr(self, "multimodal_status_cache")
            or self.multimodal_status_cache is None
        ):
            return False

        try:
            await self.multimodal_status_cache.upsert(
                {
                    doc_id: {
                        "multimodal_processed": processed,
                        "updated_at": self._current_doc_status_timestamp(),
                    }
                }
            )
            await self.multimodal_status_cache.index_done_callback()
            return True
        except Exception as exc:
            self.logger.warning(
                "Unable to persist multimodal compatibility status for %s: %s",
                doc_id,
                exc,
            )
            return False

    async def _get_multimodal_processed_flag(
        self, doc_id: str, doc_status: Dict[str, Any] | None = None
    ) -> bool:
        """Read multimodal completion state from doc_status or compatibility cache."""
        if is_multimodal_processed(doc_status):
            return True

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
            raise RuntimeError(
                "LightRAG initialization failed before multimodal processing"
            )
        # A later failure must not retry after chunks/entities have been
        # persisted, because a second pass can create duplicate graph data.
        self._multimodal_storage_started = False

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

        has_video = False
        try:
            # Video owns its chunk creation because one source item becomes
            # several time-bounded chunks. The generic batch path only calls
            # generate_description_only(), which cannot persist video segment
            # records and must never be an ingestion fallback.
            has_video = any(item.get("type") == "video" for item in multimodal_items)
            if has_video:
                processed = await self._process_multimodal_content_individual(
                    multimodal_items, file_path, doc_id
                )
            else:
                processed = await self._process_multimodal_content_batch_type_aware(
                    multimodal_items=multimodal_items, file_path=file_path, doc_id=doc_id
                )
            if processed is not True:
                raise RuntimeError(
                    "multimodal processing completed without processing every item"
                )

            # Mark multimodal content as processed and update final status
            if not await self._mark_multimodal_processing_complete(doc_id):
                raise RuntimeError(
                    "multimodal processing completed but its status marker could not be persisted"
                )

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
            # A v2 video is an atomic indexing unit: its own compensation
            # cleanup already removed partial artifacts, and the generic batch
            # fallback would silently index a competing whole-video chunk.
            # Surface the failure so the Worker can retry the same snapshot.
            if has_video:
                raise
            if getattr(self, "_multimodal_storage_started", False):
                await self._set_multimodal_status_record(doc_id, False)
                raise RuntimeError(
                    "multimodal processing failed after persistence started; retry suppressed"
                ) from e
            # Step 1: Retry in smaller batches (4 per batch) before individual fallback
            try:
                self.logger.warning("Retrying multimodal processing in small batches (4/batch)")
                batch_size = 4
                for batch_start in range(0, len(multimodal_items), batch_size):
                    batch_items = multimodal_items[batch_start:batch_start + batch_size]
                    processed = await self._process_multimodal_content_batch_type_aware(
                        batch_items,
                        file_path,
                        doc_id,
                        defer_odl_media_audit=True,
                    )
                    if processed is not True:
                        raise RuntimeError(
                            "multimodal retry did not process every item in its batch"
                        )
                recovered = True
            except Exception as e2:
                self.logger.error(f"Batch retry also failed: {e2}")
                if getattr(self, "_multimodal_storage_started", False):
                    await self._set_multimodal_status_record(doc_id, False)
                    raise RuntimeError(
                        "multimodal retry failed after persistence started; fallback suppressed"
                    ) from e2
                self.logger.warning("Falling back to individual multimodal processing")
                recovered = await self._process_multimodal_content_individual(
                    multimodal_items, file_path, doc_id
                )

            if recovered:
                if not await self._finalize_odl_image_media_contract(
                    doc_id, multimodal_items
                ):
                    raise RuntimeError("image_media_incomplete")
                if not await self._mark_multimodal_processing_complete(doc_id):
                    raise RuntimeError(
                        "multimodal retry completed but its status marker could not be persisted"
                    )
            else:
                # Keep the explicit incomplete marker so degraded/tagging paths
                # cannot treat partial multimodal chunks as a complete document.
                await self._set_multimodal_status_record(doc_id, False)
                raise RuntimeError(
                    "multimodal processing failed before all items were completed"
                )

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
        completed = False
        try:
            self.logger.info(
                f"Background multimodal processing started: {len(multimodal_items)} items for doc {doc_id}"
            )
            await self._process_multimodal_content(
                multimodal_items, file_ref, doc_id
            )
            completed = True
            self.logger.info(
                f"Background multimodal processing completed for doc {doc_id}"
            )
        except asyncio.CancelledError:
            self.logger.warning(
                "Background multimodal processing cancelled for doc %s", doc_id
            )
            raise
        except Exception as exc:
            self.logger.error(
                f"Background multimodal processing failed for doc {doc_id}: {exc}"
            )
            try:
                failure_metadata = {
                    "content_ready": False,
                    "multimodal_processed": False,
                    "failure_stage": "multimodal",
                    "cleanup_pending": True,
                    "residual_data": True,
                    "last_error": str(exc)[:4000],
                }
                current_status = None
                doc_status_store = getattr(
                    getattr(self, "lightrag", None), "doc_status", None
                )
                if doc_status_store is not None:
                    current_status = await doc_status_store.get_by_id(doc_id)
                existing_metadata = (
                    current_status.get("metadata")
                    if isinstance(current_status, dict) else {}
                )
                if isinstance(existing_metadata, dict):
                    multimodal_chunks = existing_metadata.get("multimodal_chunks")
                    if isinstance(multimodal_chunks, dict):
                        failure_metadata["residual_multimodal_chunk_ids"] = [
                            str(value) for value in multimodal_chunks if value
                        ]
                await self._upsert_doc_status(
                    doc_id,
                    file_ref,
                    status=DocStatus.FAILED,
                    error_msg=str(exc),
                    metadata=failure_metadata,
                )
            except Exception as status_exc:
                self.logger.error(
                    "Failed to persist background multimodal error state for doc %s: %s",
                    doc_id,
                    status_exc,
                )
            raise
        finally:
            if completed:
                if not await self._mark_multimodal_processing_complete(doc_id):
                    raise RuntimeError(
                        "multimodal completion marker could not be persisted"
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

        processed_count = 0
        failed_count = 0
        next_chunk_order_index = existing_chunks_count
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
                    result = await processor.process_multimodal_content(
                        modal_content=item,
                        content_type=content_type,
                        file_path=file_name,
                        item_info=item_info,  # Pass item info for context extraction
                        batch_mode=True,
                        doc_id=doc_id,  # Pass doc_id for proper association
                        chunk_order_index=next_chunk_order_index,
                    )
                    if not isinstance(result, tuple) or len(result) != 3:
                        raise RuntimeError(
                            "multimodal processor returned an invalid result contract"
                        )
                    _, entity_info, chunk_results = result
                    chunk_ids = (
                        entity_info.get("chunk_ids")
                        if isinstance(entity_info, dict) else None
                    )
                    if not isinstance(chunk_ids, list):
                        chunk_ids = [entity_info.get("chunk_id")] if isinstance(entity_info, dict) else []
                    chunk_ids = [str(chunk_id) for chunk_id in chunk_ids if chunk_id]
                    if not chunk_ids:
                        raise RuntimeError(
                            "multimodal processor did not persist an indexable chunk"
                        )

                    # Collect chunk results for batch processing
                    all_chunk_results.extend(chunk_results)

                    multimodal_chunk_ids.extend(chunk_ids)
                    next_chunk_order_index += len(chunk_ids)

                    self.logger.info(
                        f"{content_type} processing complete: {entity_info.get('entity_name', 'Unknown')}"
                    )
                    processed_count += 1
                else:
                    self.logger.warning(
                        f"No suitable processor found for {content_type} type content"
                    )
                    failed_count += 1

            except Exception as e:
                # Native video failures are retryable Worker failures, not a
                # partial multimodal success that could leave segments indexed.
                from raganything.video_processor import VideoProcessingError
                if isinstance(e, VideoProcessingError):
                    raise
                self.logger.error(f"Error processing multimodal content: {str(e)}")
                self.logger.debug("Exception details:", exc_info=True)
                failed_count += 1
                continue

        # The individual fallback is only a recovery path for providers that
        # cannot handle a batch.  Do not persist a partial set: the document
        # status can only describe one complete multimodal attempt, and
        # retaining successful items here would make every later retry append
        # duplicate chunks to the same document.
        if failed_count:
            self.logger.warning(
                "Individual multimodal fallback failed for %d/%d items; "
                "discarding collected results before persistence",
                failed_count,
                len(multimodal_items),
            )
            return False

        # Update doc_status to include multimodal chunks in the standard chunks_list
        if multimodal_chunk_ids:
            try:
                self._multimodal_storage_started = True
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
            self._multimodal_storage_started = True
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

        completed = failed_count == 0 and processed_count == len(multimodal_items)
        if completed:
            self.logger.info("Individual multimodal content processing complete")
        else:
            self.logger.error(
                "Individual multimodal content processing incomplete: processed=%d failed=%d total=%d",
                processed_count,
                failed_count,
                len(multimodal_items),
            )
        return completed

    async def _process_multimodal_content_batch_type_aware(
        self,
        multimodal_items: List[Dict[str, Any]],
        file_path: str,
        doc_id: str,
        *,
        defer_odl_media_audit: bool = False,
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
        # Uses MULTIMODAL_MAX_CONCURRENT env var (default 16), capped by
        # LightRAG's llm_model_max_async so we don't overwhelm the HTTP pool.
        try:
            _mm_concurrency = int(os.getenv("MULTIMODAL_MAX_CONCURRENT", "16"))
        except (TypeError, ValueError):
            _mm_concurrency = 16
        _mm_concurrency = max(1, min(_mm_concurrency, 128))
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
                        doc_id=doc_id,
                        file_path=file_path,
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

                    if (
                        isinstance(entity_info, dict)
                        and entity_info.get("non_indexable", False)
                    ):
                        self.logger.warning(
                            "Skipping non-indexable %s fallback item %d (source=%s)",
                            content_type,
                            index,
                            entity_info.get("analysis_source", "unknown"),
                        )
                        return {
                            "index": index,
                            "content_type": content_type,
                            "description": "",
                            "entity_info": entity_info,
                            "original_item": item,
                            "item_info": item_info,
                            "chunk_order_index": existing_chunks_count + index,
                            "processor": processor,
                            "file_path": file_path,
                            "skipped": True,
                        }

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

        multimodal_data_list = []
        try:
            _batch_size = int(os.getenv("MULTIMODAL_TASK_BATCH_SIZE", "32"))
        except (TypeError, ValueError):
            _batch_size = 32
        _batch_size = max(1, min(_batch_size, 128))
        self.logger.info(
            "Processing multimodal descriptions in batches of %d", _batch_size
        )

        # Keep the semaphore for API concurrency, but also bound the number of
        # coroutine/result objects retained at once. This matters for manuals
        # with hundreds of images and prevents a large gather() from retaining
        # every input payload until the whole description stage completes.
        for batch_start in range(0, total_items, _batch_size):
            batch_items = multimodal_items[batch_start:batch_start + _batch_size]
            batch_tasks = [
                asyncio.create_task(
                    process_single_item_with_correct_processor(
                        item, batch_start + offset, file_path
                    )
                )
                for offset, item in enumerate(batch_items)
            ]
            try:
                batch_results = await asyncio.gather(
                    *batch_tasks, return_exceptions=True
                )
                for result in batch_results:
                    if isinstance(result, Exception):
                        self.logger.error(f"Task failed: {result}")
                        continue
                    if result is not None:
                        multimodal_data_list.append(result)
            finally:
                # Explicitly release completed task references before starting
                # the next batch; gather() has already collected exceptions.
                for task in batch_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*batch_tasks, return_exceptions=True)
                batch_tasks.clear()
                batch_items = None
                if "batch_results" in locals():
                    batch_results = None

        if len(multimodal_data_list) != total_items:
            self.logger.warning(
                "Only %d/%d multimodal descriptions generated; "
                "skip storage to avoid partial document residue",
                len(multimodal_data_list),
                total_items,
            )
            return False

        skipped_count = sum(
            1 for result in multimodal_data_list if result.get("skipped")
        )
        if skipped_count:
            self.logger.info(
                "Skipped %d non-indexable multimodal items while processing %d total",
                skipped_count,
                total_items,
            )
        multimodal_data_list = [
            result for result in multimodal_data_list if not result.get("skipped")
        ]
        if not multimodal_data_list:
            self.logger.info(
                "All multimodal items were valid non-indexable fallbacks; no chunks to store"
            )
            return True
        self.logger.info(
            f"Generated descriptions for {len(multimodal_data_list)}/{len(multimodal_items)} multimodal items using correct processors"
        )

        # Stage 2: Convert to LightRAG chunks format
        lightrag_chunks = self._convert_to_lightrag_chunks_type_aware(
            multimodal_data_list, file_path, doc_id
        )

        # Stage 3: Store chunks to LightRAG storage
        self._multimodal_storage_started = True
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
        status_updated = await self._update_doc_status_with_chunks_type_aware(
            doc_id, chunk_ids, lightrag_chunks
        )
        if status_updated is not True:
            raise RuntimeError(
                "multimodal chunks persisted but document status could not be updated"
            )
        if not await self._bind_and_audit_odl_image_media(
            doc_id,
            multimodal_data_list,
            lightrag_chunks,
            finalize=not defer_odl_media_audit,
        ):
            raise RuntimeError("image_media_incomplete")
        return True

    async def _bind_and_audit_odl_image_media(
        self,
        doc_id: str,
        multimodal_data_list: List[Dict[str, Any]],
        lightrag_chunks: Dict[str, Any],
        *,
        finalize: bool = True,
    ) -> bool:
        """Bind ODL image chunks only after storage, then audit completion.

        Non-ODL parsers do not carry the private ``_odl_media`` marker and
        retain their existing completion behavior.  An ODL media mismatch is
        explicit and prevents ``multimodal_processed`` from becoming true.
        """
        expected: dict[str, str] = {}
        manifest_paths: set[str] = set()
        chunk_by_order = {
            int(chunk.get("chunk_order_index", -1)): chunk_id
            for chunk_id, chunk in lightrag_chunks.items()
        }
        for item in multimodal_data_list:
            original = item.get("original_item") or {}
            media = original.get("_odl_media")
            manifest_path = original.get("_odl_media_manifest_path")
            if not isinstance(media, dict) and not manifest_path:
                continue
            media_id = media.get("media_id") if isinstance(media, dict) else None
            chunk_id = chunk_by_order.get(int(item.get("chunk_order_index", -1)))
            if not isinstance(media_id, str) or not isinstance(manifest_path, str) or not chunk_id:
                return await self._record_odl_image_media_incomplete(doc_id, 0, 0, 0)
            expected[media_id] = chunk_id
            manifest_paths.add(manifest_path)

        if not expected:
            return True

        from raganything.services.odl_media_manifest import bind_persisted_image_chunk

        for item in multimodal_data_list:
            original = item.get("original_item") or {}
            media = original.get("_odl_media")
            manifest_path = original.get("_odl_media_manifest_path")
            if not isinstance(media, dict) or not isinstance(manifest_path, str):
                continue
            media_id = media.get("media_id")
            chunk_id = expected.get(media_id)
            if not chunk_id or not bind_persisted_image_chunk(
                manifest_path,
                media_id=media_id,
                document_id=doc_id,
                chunk_id=chunk_id,
            ):
                return await self._record_odl_image_media_incomplete(
                    doc_id, len(expected), 0, 0
                )

        if not finalize:
            # Retry batches bind durable chunk IDs, but a document-level
            # catalog must be written only after every batch has succeeded.
            return True
        return await self._finalize_odl_image_media_contract(
            doc_id, multimodal_data_list
        )

    async def _finalize_odl_image_media_contract(
        self,
        doc_id: str,
        items: List[Dict[str, Any]],
    ) -> bool:
        """Audit all ODL image entries and persist one catalog per document."""
        expected_media_ids: set[str] = set()
        manifest_paths: set[str] = set()
        for item in items:
            original = item.get("original_item") or item
            if not isinstance(original, dict):
                continue
            media = original.get("_odl_media")
            manifest_path = original.get("_odl_media_manifest_path")
            if not isinstance(media, dict) and not manifest_path:
                continue
            media_id = media.get("media_id") if isinstance(media, dict) else None
            if not isinstance(media_id, str) or not isinstance(manifest_path, str):
                return await self._record_odl_image_media_incomplete(doc_id, 0, 0, 0)
            expected_media_ids.add(media_id)
            manifest_paths.add(manifest_path)

        if not expected_media_ids:
            return True

        from raganything.services.odl_media_manifest import audit_persisted_entries

        persisted_ids = await self._persisted_chunk_ids_for_completion(doc_id)
        if persisted_ids is None:
            # The contract requires a durable storage proof.  This backend
            # cannot provide one, so it must not claim ODL image completion.
            return await self._record_odl_image_media_incomplete(
                doc_id, len(expected_media_ids), 0, 0
            )
        complete, counts = audit_persisted_entries(
            manifest_paths,
            document_id=doc_id,
            expected_media_ids=expected_media_ids,
            persisted_chunk_ids=persisted_ids,
        )
        if not complete:
            return await self._record_odl_image_media_incomplete(
                doc_id, counts["expected"], counts["valid"], counts["chunks"]
            )
        from raganything.services.odl_media_delivery import build_persisted_media_catalog

        workspace = str(getattr(self.lightrag, "workspace", ""))
        normalized_workspace = workspace.replace("\\", "/")
        if normalized_workspace == "./rag_storage":
            catalog_kb = "default"
        elif normalized_workspace.startswith("./rag_storage_"):
            catalog_kb = normalized_workspace[len("./rag_storage_"):]
        else:
            # A non-standard workspace cannot be safely reverse-mapped to a
            # KB name, so do not mint a catalog that an endpoint could serve.
            return await self._record_odl_image_media_incomplete(
                doc_id, counts["expected"], counts["valid"], counts["chunks"]
            )
        catalog = build_persisted_media_catalog(
            manifest_paths,
            kb_name=catalog_kb,
            document_id=doc_id,
            workspace=workspace,
        )
        if catalog is None or len(catalog) != counts["expected"]:
            return await self._record_odl_image_media_incomplete(
                doc_id, counts["expected"], counts["valid"], counts["chunks"]
            )
        try:
            status = await self.lightrag.doc_status.get_by_id(doc_id)
            if not status:
                return await self._record_odl_image_media_incomplete(
                    doc_id, counts["expected"], counts["valid"], counts["chunks"]
                )
            metadata = status.get("metadata") or {}
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            metadata.update({
                "odl_media_catalog": catalog,
                "image_media_incomplete": False,
                "image_media_counts": {
                    "eligible_elements": counts["expected"],
                    "valid_manifest_media": counts["valid"],
                    "persisted_image_chunks": counts["chunks"],
                    "catalog_media": len(catalog),
                },
            })
            await self.lightrag.doc_status.upsert(
                {
                    doc_id: {
                        **status,
                        "metadata": metadata,
                        "updated_at": self._current_doc_status_timestamp(),
                    }
                }
            )
            await self.lightrag.doc_status.index_done_callback()
        except Exception:
            return await self._record_odl_image_media_incomplete(
                doc_id, counts["expected"], counts["valid"], counts["chunks"]
            )
        return True

    async def _record_odl_image_media_incomplete(
        self, doc_id: str, expected: int, valid: int, chunks: int,
    ) -> bool:
        """Persist the explicit failure state without leaking media paths."""
        try:
            status = await self.lightrag.doc_status.get_by_id(doc_id)
            if not status:
                return False
            metadata = status.get("metadata") or {}
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            metadata.update({
                "multimodal_processed": False,
                "image_media_incomplete": True,
                "image_media_counts": {
                    "eligible_elements": expected,
                    "valid_manifest_media": valid,
                    "persisted_image_chunks": chunks,
                },
                "failure_stage": "multimodal",
            })
            await self.lightrag.doc_status.upsert({
                doc_id: {
                    **status,
                    "metadata": metadata,
                    "updated_at": self._current_doc_status_timestamp(),
                }
            })
            await self.lightrag.doc_status.index_done_callback()
        except Exception as exc:
            self.logger.warning(
                "Unable to record image_media_incomplete for %s: error_type=%s",
                doc_id,
                type(exc).__name__,
            )
        self.logger.error(
            "ODL image media contract incomplete for %s: expected=%d valid=%d chunks=%d",
            doc_id,
            expected,
            valid,
            chunks,
        )
        return False

    async def _persisted_chunk_ids_for_completion(
        self, doc_id: str,
    ) -> set[str] | None:
        """Read the authoritative PG chunk set when the backend supports it."""
        try:
            from lightrag.kg.postgres_impl import PGKVStorage, namespace_to_table_name

            store = getattr(self.lightrag, "text_chunks", None)
            if not isinstance(store, PGKVStorage):
                return None
            table_name = namespace_to_table_name(store.namespace)
            rows = await store.db.query(
                f"SELECT id FROM {table_name} WHERE workspace=$1 AND full_doc_id=$2",
                [store.workspace, doc_id],
                multirows=True,
            )
            return {
                str(row["id"])
                for row in (rows or [])
                if isinstance(row, dict) and row.get("id")
            }
        except Exception as exc:
            self.logger.warning(
                "Unable to verify persisted multimodal chunks for %s: %s",
                doc_id,
                exc,
            )
            # A PG-backed document must not be reported complete when its
            # authoritative chunk set cannot be checked.
            return set()

    async def _mark_multimodal_processing_complete(self, doc_id: str) -> bool:
        """Mark multimodal content processing as complete in the document status."""
        try:
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            if current_doc_status:
                declared_ids = {
                    str(value)
                    for value in current_doc_status.get("chunks_list") or []
                    if value
                }
                persisted_ids = await self._persisted_chunk_ids_for_completion(doc_id)
                if persisted_ids is not None and persisted_ids != declared_ids:
                    failure_metadata = current_doc_status.get("metadata") or {}
                    failure_metadata = (
                        dict(failure_metadata)
                        if isinstance(failure_metadata, dict)
                        else {}
                    )
                    failure_metadata.update({
                        "content_ready": False,
                        "multimodal_processed": False,
                        "failure_stage": "multimodal",
                        "cleanup_pending": True,
                        "residual_data": True,
                        "last_error": (
                            "multimodal chunk set does not match document status: "
                            f"declared={len(declared_ids)}, persisted={len(persisted_ids)}"
                        ),
                    })
                    failed_payload = {
                        **current_doc_status,
                        "status": DocStatus.FAILED,
                        "error_msg": failure_metadata["last_error"],
                        "metadata": failure_metadata,
                        "updated_at": self._current_doc_status_timestamp(),
                    }
                    await self.lightrag.doc_status.upsert({doc_id: failed_payload})
                    await self.lightrag.doc_status.index_done_callback()
                    await self._set_multimodal_status_record(doc_id, False)
                    self.logger.error(
                        "Refusing multimodal completion for %s: declared=%d persisted=%d",
                        doc_id,
                        len(declared_ids),
                        len(persisted_ids),
                    )
                    return False
                final_status = current_doc_status.get("status") or DocStatus.PROCESSED
                if final_status != DocStatus.FAILED:
                    final_status = DocStatus.PROCESSED
                existing_metadata = current_doc_status.get("metadata") or {}
                metadata = (
                    dict(existing_metadata)
                    if isinstance(existing_metadata, dict)
                    else {}
                )
                declared_chunk_ids = {
                    str(value)
                    for value in current_doc_status.get("chunks_list") or []
                    if value
                }
                multimodal_chunks = metadata.get("multimodal_chunks")
                if isinstance(multimodal_chunks, dict):
                    residual_ids = [
                        str(value)
                        for value in multimodal_chunks
                        if value and str(value) not in declared_chunk_ids
                    ]
                    if residual_ids:
                        # A prior attempt left multimodal rows that are not
                        # represented by the authoritative doc-status list.
                        # Do not claim completion or enqueue automatic tags.
                        metadata.update({
                            "multimodal_processed": False,
                            "content_ready": False,
                            "failure_stage": "multimodal",
                            "cleanup_pending": True,
                            "residual_data": True,
                            "residual_multimodal_chunk_ids": residual_ids,
                        })
                        await self.lightrag.doc_status.upsert(
                            {
                                doc_id: {
                                    **current_doc_status,
                                    "metadata": metadata,
                                    "updated_at": self._current_doc_status_timestamp(),
                                }
                            }
                        )
                        await self.lightrag.doc_status.index_done_callback()
                        self.logger.warning(
                            "Refusing multimodal completion for %s: %d residual chunks are not declared",
                            doc_id,
                            len(residual_ids),
                        )
                        return False
                metadata["multimodal_processed"] = True
                update_payload = {
                    **current_doc_status,
                    "status": final_status,
                    "metadata": metadata,
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
                    if not await self._set_multimodal_status_record(doc_id, True):
                        return False
                await self.lightrag.doc_status.index_done_callback()
                self.logger.debug(
                    f"Marked multimodal content processing as complete for document {doc_id}"
                )
                return True
            return await self._set_multimodal_status_record(doc_id, True)
        except Exception as e:
            self.logger.warning(
                f"Error marking multimodal processing as complete for document {doc_id}: {e}"
            )
            return False

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
