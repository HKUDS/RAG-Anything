"""
Multimodal content ingestion and Knowledge Graph integration mixin for RAGAnything.

Handles type-aware batch processing of multimodal items (images, tables, equations, etc.),
chunk templating, entity extraction, belongs-to relationship synthesis, and KG merging.
"""

from __future__ import annotations

import time
from typing import Any

from lightrag.utils import compute_mdhash_id

from raganything.base import DocStatus
from raganything.prompt import PROMPTS
from raganything.utils import (
    format_table_body,
    get_equation_text_and_format,
    get_processor_for_type,
    get_table_body,
    normalize_caption_list,
    table_image_paths,
)


class MultimodalIngestMixin:
    """Mixin responsible for multimodal batch processing, chunk templates, and KG integration."""

    async def _process_multimodal_content(
        self,
        multimodal_items: list[dict[str, Any]],
        file_path: str,
        doc_id: str,
        pipeline_status: Any | None = None,
        pipeline_status_lock: Any | None = None,
        force_reprocess: bool = False,
    ):
        """Process multimodal content using specialized processors."""
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

        init_result = await self._ensure_lightrag_initialized()
        if not init_result or not init_result.get("success"):
            self.logger.error(
                "LightRAG initialization failed; skipping multimodal processing"
            )
            return

        if force_reprocess:
            self.logger.info(
                f"force_reprocess=True: bypassing already-processed check for document {doc_id}"
            )
        else:
            try:
                existing_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
                if existing_doc_status:
                    multimodal_processed = await self._get_multimodal_processed_flag(
                        doc_id, existing_doc_status
                    )

                    if multimodal_processed:
                        self.logger.info(
                            f"Document {doc_id} multimodal content is already processed"
                        )
                        if existing_doc_status.get("status") == DocStatus.HANDLING:
                            await self._mark_multimodal_processing_complete(doc_id)
                        return

                    doc_status = existing_doc_status.get("status", "")
                    if doc_status == DocStatus.PROCESSED and not multimodal_processed:
                        self.logger.info(
                            f"Document {doc_id} text processing is complete, but multimodal content still needs processing"
                        )
                    elif doc_status == DocStatus.PROCESSED and multimodal_processed:
                        self.logger.info(
                            f"Document {doc_id} is fully processed (text + multimodal)"
                        )
                        return

            except Exception as e:
                self.logger.debug(f"Error checking document status for {doc_id}: {e}")

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
            self.logger.warning("Falling back to individual multimodal processing")
            try:
                await self._process_multimodal_content_individual(
                    multimodal_items, file_path, doc_id
                )
            except Exception as fallback_error:
                current = await self.lightrag.doc_status.get_by_id(doc_id)
                updates = {
                    "status": DocStatus.FAILED,
                    "error_msg": str(fallback_error),
                }
                if current and "multimodal_processed" in current:
                    updates["multimodal_processed"] = False
                await self._upsert_doc_status(doc_id, file_path, **updates)
                await self._set_multimodal_status_record(doc_id, False)
                raise

            await self._mark_multimodal_processing_complete(doc_id)

    async def _process_multimodal_content_individual(
        self, multimodal_items: list[dict[str, Any]], file_path: str, doc_id: str
    ):
        """Process multimodal content individually (fallback method)."""
        file_name = self._get_file_reference(file_path)

        all_chunk_results = []
        multimodal_chunk_ids = []
        failed_count = 0
        first_error = None

        existing_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
        existing_chunks_count = (
            existing_doc_status.get("chunks_count", 0) if existing_doc_status else 0
        )
        next_order = existing_chunks_count

        for i, item in enumerate(multimodal_items):
            try:
                content_type = item.get("type", "unknown")
                self.logger.info(
                    f"Processing item {i + 1}/{len(multimodal_items)}: {content_type} content"
                )

                processor = get_processor_for_type(self.modal_processors, content_type)

                if processor:
                    item_info = {
                        "page_idx": item.get("page_idx", 0),
                        "page_idx_end": item.get("page_idx_end"),
                        "index": item.get("_content_list_index", i),
                        "type": content_type,
                    }

                    (
                        enhanced_caption,
                        entity_info,
                        chunk_results,
                    ) = await processor.process_multimodal_content(
                        modal_content=item,
                        content_type=content_type,
                        file_path=file_name,
                        item_info=item_info,
                        batch_mode=True,
                        doc_id=doc_id,
                        chunk_order_index=next_order,
                    )

                    if entity_info and entity_info.get("chunk_ids"):
                        item_chunk_ids = entity_info["chunk_ids"]
                    elif entity_info and entity_info.get("chunk_id"):
                        item_chunk_ids = [entity_info["chunk_id"]]
                    else:
                        item_chunk_ids = []
                    if not item_chunk_ids:
                        raise RuntimeError(
                            f"No chunks stored for multimodal {content_type} item {i}"
                        )
                    all_chunk_results.extend(chunk_results)
                    multimodal_chunk_ids.extend(item_chunk_ids)
                    next_order += max(1, len(item_chunk_ids))

                    self.logger.info(
                        f"{content_type} processing complete: {entity_info.get('entity_name', 'Unknown')}"
                    )
                else:
                    self.logger.warning(
                        f"No suitable processor found for {content_type} type content"
                    )

            except Exception as e:
                failed_count += 1
                if first_error is None:
                    first_error = e
                self.logger.error(f"Error processing multimodal content: {e!s}")
                self.logger.debug("Exception details:", exc_info=True)
                continue

        if multimodal_chunk_ids:
            await self._update_doc_status_with_chunks_type_aware(
                doc_id, multimodal_chunk_ids
            )

        if all_chunk_results:
            from lightrag.kg.shared_storage import (
                get_namespace_data,
                get_pipeline_status_lock,
            )
            from lightrag.operate import merge_nodes_and_edges

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

        if failed_count:
            raise RuntimeError(
                f"Failed to process {failed_count}/{len(multimodal_items)} multimodal items"
            ) from first_error

        self.logger.info("Individual multimodal content processing complete")
        await self._mark_multimodal_processing_complete(doc_id)

    def _modal_description_only_text(self, data: dict[str, Any]) -> str:
        """Build compact KG-extraction text for one multimodal item."""
        content_type = data.get("content_type", "unknown")
        description = (data.get("description") or "").strip()
        entity_info = data.get("entity_info") or {}
        original_item = data.get("original_item") or {}
        entity_name = (entity_info.get("entity_name") or "").strip()

        header_bits = [f"[{content_type}]"]
        if entity_name:
            header_bits.append(entity_name)

        extra_bits: list[str] = []
        if content_type == "image":
            captions = normalize_caption_list(
                original_item.get("image_caption", original_item.get("img_caption", []))
            )
            footnotes = normalize_caption_list(
                original_item.get(
                    "image_footnote", original_item.get("img_footnote", [])
                )
            )
            if captions:
                extra_bits.append("Captions: " + ", ".join(captions))
            if footnotes:
                extra_bits.append("Footnotes: " + ", ".join(footnotes))
        elif content_type == "table":
            captions = normalize_caption_list(original_item.get("table_caption", []))
            footnotes = normalize_caption_list(original_item.get("table_footnote", []))
            table_body = format_table_body(get_table_body(original_item))
            if captions:
                extra_bits.append("Caption: " + ", ".join(captions))
            if table_body and table_body.strip() and table_body.strip() != "None":
                body = table_body.strip()
                if len(body) > 4000:
                    body = body[:4000] + "…"
                extra_bits.append("Structure:\n" + body)
            if footnotes:
                extra_bits.append("Footnotes: " + ", ".join(footnotes))
        elif content_type == "equation":
            equation_text, equation_format = get_equation_text_and_format(original_item)
            if equation_text:
                extra_bits.append(f"Equation ({equation_format}): {equation_text}")

        parts = [" ".join(header_bits)]
        parts.extend(extra_bits)
        if description:
            parts.append(description)
        return "\n".join(p for p in parts if p).strip()

    def _chunk_token_budget_for_extraction(self, default: int = 1200) -> int:
        """Token budget used when packing multimodal descriptions for extraction."""
        value = default
        try:
            value = int(getattr(self.lightrag, "chunk_token_size", default) or default)
        except (TypeError, ValueError):
            value = default
        return value if value > 0 else default

    def _count_tokens_for_extraction(self, text: str) -> int:
        tokenizer = getattr(self.lightrag, "tokenizer", None)
        if tokenizer is not None:
            try:
                return len(tokenizer.encode(text))
            except Exception:
                pass
        return max(1, len(text) // 4)

    def _build_multimodal_extraction_chunks(
        self,
        multimodal_data_list: list[dict[str, Any]],
        lightrag_chunks: dict[str, Any],
        mode: str = "legacy",
    ) -> dict[str, Any]:
        """Build chunks passed to ``extract_entities``."""
        if mode == "legacy":
            return lightrag_chunks

        chunk_id_to_data: dict[str, dict[str, Any]] = {}
        for data in multimodal_data_list:
            formatted = self._apply_chunk_template(
                data["content_type"], data["original_item"], data["description"]
            )
            chunk_id = compute_mdhash_id(formatted, prefix="chunk-")
            chunk_id_to_data[chunk_id] = data

        if mode == "per_item":
            extraction_chunks: dict[str, Any] = {}
            for chunk_id, chunk in lightrag_chunks.items():
                data = chunk_id_to_data.get(chunk_id)
                content = (
                    self._modal_description_only_text(data)
                    if data is not None
                    else chunk.get("content", "")
                )
                extraction_chunks[chunk_id] = {
                    **chunk,
                    "content": content,
                    "tokens": self._count_tokens_for_extraction(content),
                }
            return extraction_chunks

        budget = self._chunk_token_budget_for_extraction()
        file_ref = next(
            (c.get("file_path") for c in lightrag_chunks.values()),
            "multimodal_content",
        )
        doc_id = next(
            (c.get("full_doc_id") for c in lightrag_chunks.values()),
            None,
        )

        packs: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0

        for data in multimodal_data_list:
            text = self._modal_description_only_text(data)
            if not text:
                continue
            tokens = self._count_tokens_for_extraction(text)
            if current and current_tokens + tokens > budget:
                packs.append(current)
                current = []
                current_tokens = 0
            current.append(text)
            current_tokens += tokens
            if current_tokens >= budget and len(current) == 1:
                packs.append(current)
                current = []
                current_tokens = 0

        if current:
            packs.append(current)

        extraction_chunks = {}
        try:
            base_order = min(
                (c.get("chunk_order_index", 0) for c in lightrag_chunks.values()),
                default=0,
            )
        except ValueError:
            base_order = 0

        for pack_index, parts in enumerate(packs):
            packed_content = "\n\n".join(parts)
            chunk_id = compute_mdhash_id(
                f"modal-pack:{doc_id}:{pack_index}:{packed_content}",
                prefix="chunk-",
            )
            extraction_chunks[chunk_id] = {
                "content": packed_content,
                "tokens": self._count_tokens_for_extraction(packed_content),
                "full_doc_id": doc_id,
                "chunk_order_index": base_order + pack_index,
                "file_path": file_ref,
                "llm_cache_list": [],
                "is_multimodal": True,
                "is_multimodal_extraction_pack": True,
                "original_type": "packed_modal",
            }

        return extraction_chunks

    def _convert_to_lightrag_chunks_type_aware(
        self, multimodal_data_list: list[dict[str, Any]], file_path: str, doc_id: str
    ) -> dict[str, Any]:
        """Convert multimodal data to LightRAG standard chunks format."""
        chunks = {}

        for data in multimodal_data_list:
            description = data["description"]
            entity_info = data["entity_info"]
            chunk_order_index = data["chunk_order_index"]
            content_type = data["content_type"]
            original_item = data["original_item"]

            formatted_chunk_content = self._apply_chunk_template(
                content_type, original_item, description
            )

            chunk_id = compute_mdhash_id(formatted_chunk_content, prefix="chunk-")
            tokens = len(self.lightrag.tokenizer.encode(formatted_chunk_content))
            file_ref = self._get_file_reference(file_path)

            chunks[chunk_id] = {
                "content": formatted_chunk_content,
                "tokens": tokens,
                "full_doc_id": doc_id,
                "chunk_order_index": chunk_order_index,
                "file_path": file_ref,
                "llm_cache_list": [],
                "is_multimodal": True,
                "modal_entity_name": entity_info["entity_name"],
                "original_type": data["content_type"],
                "page_idx": data["item_info"].get("page_idx", 0),
            }
            if data["item_info"].get("page_idx_end") is not None:
                chunks[chunk_id]["page_idx_end"] = data["item_info"]["page_idx_end"]

        self.logger.debug(
            f"Converted {len(chunks)} multimodal items to multimodal chunks format"
        )
        return chunks

    @staticmethod
    def _format_window_part(window_meta: dict[str, Any] | None) -> str:
        """Render the ' — part k/N' suffix for a windowed media chunk, if any."""
        if not window_meta:
            return ""
        return f" — part {window_meta['part']}/{window_meta['total']}"

    def _apply_chunk_template(
        self, content_type: str, original_item: dict[str, Any], description: str
    ) -> str:
        """Apply the appropriate chunk template based on content type with 1-based page citations."""
        templates = getattr(self, "_instance_prompts", PROMPTS)

        page_idx = original_item.get("page_idx")
        page_idx_end = original_item.get("page_idx_end")
        page_prefix = ""
        if isinstance(page_idx, int) and page_idx >= 0:
            if isinstance(page_idx_end, int) and page_idx_end > page_idx:
                page_prefix = f"[Page {page_idx + 1}-{page_idx_end + 1}]\n"
            else:
                page_prefix = f"[Page {page_idx + 1}]\n"

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

                formatted = templates["image_chunk"].format(
                    section_path=section_path if section_path else "None",
                    neighbor_text=neighbor_text if neighbor_text else "None",
                    image_path=image_path,
                    captions=", ".join(captions) if captions else "None",
                    footnotes=", ".join(footnotes) if footnotes else "None",
                    enhanced_caption=description,
                )

            elif content_type == "table":
                table_img_path = "\nTable Image Path: ".join(
                    table_image_paths(original_item)
                )
                table_caption = normalize_caption_list(
                    original_item.get("table_caption", [])
                )
                table_body = format_table_body(get_table_body(original_item))
                table_footnote = normalize_caption_list(
                    original_item.get("table_footnote", [])
                )

                formatted = templates["table_chunk"].format(
                    table_img_path=table_img_path,
                    table_caption=", ".join(table_caption) if table_caption else "None",
                    table_body=table_body,
                    table_footnote=(
                        ", ".join(table_footnote) if table_footnote else "None"
                    ),
                    enhanced_caption=description,
                )

            elif content_type == "equation":
                equation_text, equation_format = get_equation_text_and_format(
                    original_item
                )

                formatted = templates["equation_chunk"].format(
                    equation_text=equation_text,
                    equation_format=equation_format,
                    enhanced_caption=description,
                )

            elif content_type == "audio":
                audio_path = original_item.get(
                    "audio_path", original_item.get("img_path", "")
                )
                part = self._format_window_part(original_item.get("_window_meta"))

                formatted = (
                    f"[Audio Content]{part}\n"
                    f"Source: {audio_path}\n"
                    f"Transcription:\n{description}"
                )

            elif content_type == "video":
                video_path = original_item.get(
                    "video_path", original_item.get("img_path", "")
                )
                part = self._format_window_part(original_item.get("_window_meta"))

                formatted = (
                    f"[Video Content]{part}\n"
                    f"Source: {video_path}\n"
                    f"Analysis:\n{description}"
                )

            else:
                content = str(original_item.get("content", original_item))

                formatted = templates["generic_chunk"].format(
                    content_type=content_type.title(),
                    content=content,
                    enhanced_caption=description,
                )

            if page_prefix and not formatted.lstrip().startswith("[Page "):
                return f"{page_prefix}{formatted}"
            return formatted

        except Exception as e:
            self.logger.warning(
                f"Error applying chunk template for {content_type}: {e}"
            )
            return description

    async def _store_chunks_to_lightrag_storage_type_aware(
        self, chunks: dict[str, Any]
    ):
        """Store chunks to storage."""
        try:
            await self.lightrag.text_chunks.upsert(chunks)
            await self.lightrag.chunks_vdb.upsert(chunks)
            self.logger.debug(f"Stored {len(chunks)} multimodal chunks to storage")
        except Exception as e:
            self.logger.error(f"Error storing chunks to storage: {e}")
            raise

    async def _store_multimodal_main_entities(
        self,
        multimodal_data_list: list[dict[str, Any]],
        lightrag_chunks: dict[str, Any],
        file_path: str,
        doc_id: str = None,
    ):
        """Store multimodal main entities to entities_vdb and full_entities."""
        if not multimodal_data_list:
            return

        entities_to_store = {}
        file_ref = self._get_file_reference(file_path)

        for data in multimodal_data_list:
            entity_info = data["entity_info"]
            entity_name = entity_info["entity_name"]
            description = data["description"]
            content_type = data["content_type"]
            original_item = data["original_item"]

            formatted_chunk_content = self._apply_chunk_template(
                content_type, original_item, description
            )

            chunk_id = compute_mdhash_id(formatted_chunk_content, prefix="chunk-")
            entity_id = compute_mdhash_id(entity_name, prefix="ent-")

            entity_data = {
                "entity_name": entity_name,
                "entity_type": entity_info.get("entity_type", content_type),
                "content": entity_info.get("summary", description),
                "source_id": chunk_id,
                "file_path": file_ref,
            }

            entities_to_store[entity_id] = entity_data

        if entities_to_store:
            try:
                for entity_id, entity_data in entities_to_store.items():
                    entity_name = entity_data["entity_name"]
                    node_data = {
                        "entity_id": entity_name,
                        "entity_type": entity_data["entity_type"],
                        "description": entity_data["content"],
                        "source_id": entity_data["source_id"],
                        "file_path": entity_data["file_path"],
                        "created_at": int(time.time()),
                    }
                    await self.lightrag.chunk_entity_relation_graph.upsert_node(
                        entity_name, node_data
                    )

                await self.lightrag.entities_vdb.upsert(entities_to_store)
                await self.lightrag.entities_vdb.index_done_callback()

                if doc_id and self.lightrag.full_entities:
                    await self._store_multimodal_entities_to_full_entities(
                        entities_to_store, doc_id
                    )

                self.logger.debug(
                    f"Stored {len(entities_to_store)} multimodal main entities to knowledge graph, entities_vdb, and full_entities"
                )

            except Exception as e:
                self.logger.error(f"Error storing multimodal main entities: {e}")
                raise

    async def _batch_extract_entities_lightrag_style_type_aware(
        self, lightrag_chunks: dict[str, Any]
    ) -> list[tuple]:
        """Use LightRAG's extract_entities for batch entity relation extraction."""
        from lightrag.kg.shared_storage import (
            get_namespace_data,
            get_pipeline_status_lock,
        )
        from lightrag.operate import extract_entities

        pipeline_status = await get_namespace_data("pipeline_status")
        pipeline_status_lock = get_pipeline_status_lock()

        chunk_results = await extract_entities(
            chunks=lightrag_chunks,
            global_config=self.lightrag.__dict__,
            pipeline_status=pipeline_status,
            pipeline_status_lock=pipeline_status_lock,
            llm_response_cache=self.lightrag.llm_response_cache,
            text_chunks_storage=self.lightrag.text_chunks,
        )

        self.logger.info(
            f"Extracted entities from {len(lightrag_chunks)} multimodal chunks"
        )
        return chunk_results

    async def _batch_add_belongs_to_relations_type_aware(
        self, chunk_results: list[tuple], multimodal_data_list: list[dict[str, Any]]
    ) -> list[tuple]:
        """Add belongs_to relations for multimodal entities."""
        chunk_to_modal_entity = {}
        chunk_to_file_path = {}

        for data in multimodal_data_list:
            description = data["description"]
            content_type = data["content_type"]
            original_item = data["original_item"]

            formatted_chunk_content = self._apply_chunk_template(
                content_type, original_item, description
            )
            chunk_id = compute_mdhash_id(formatted_chunk_content, prefix="chunk-")

            chunk_to_modal_entity[chunk_id] = data["entity_info"]["entity_name"]
            chunk_to_file_path[chunk_id] = data.get("file_path", "multimodal_content")

        enhanced_chunk_results = []
        belongs_to_count = 0

        for maybe_nodes, maybe_edges in chunk_results:
            chunk_id = None
            for nodes_dict in maybe_nodes.values():
                if nodes_dict:
                    chunk_id = nodes_dict[0].get("source_id")
                    break

            if chunk_id and chunk_id in chunk_to_modal_entity:
                modal_entity_name = chunk_to_modal_entity[chunk_id]
                file_path = chunk_to_file_path.get(chunk_id, "multimodal_content")

                for entity_name in maybe_nodes.keys():
                    if entity_name != modal_entity_name:
                        belongs_to_relation = {
                            "src_id": entity_name,
                            "tgt_id": modal_entity_name,
                            "description": f"Entity {entity_name} belongs to {modal_entity_name}",
                            "keywords": "belongs_to,part_of,contained_in",
                            "source_id": chunk_id,
                            "weight": 10.0,
                            "file_path": file_path,
                        }

                        edge_key = (entity_name, modal_entity_name)
                        if edge_key not in maybe_edges:
                            maybe_edges[edge_key] = []
                        maybe_edges[edge_key].append(belongs_to_relation)
                        belongs_to_count += 1

            enhanced_chunk_results.append((maybe_nodes, maybe_edges))

        self.logger.info(
            f"Added {belongs_to_count} belongs_to relations for multimodal entities"
        )
        return enhanced_chunk_results

    async def _batch_merge_lightrag_style_type_aware(
        self, enhanced_chunk_results: list[tuple], file_path: str, doc_id: str = None
    ):
        """Use LightRAG's merge_nodes_and_edges for batch merge."""
        from lightrag.kg.shared_storage import (
            get_namespace_data,
            get_pipeline_status_lock,
        )
        from lightrag.operate import merge_nodes_and_edges

        pipeline_status = await get_namespace_data("pipeline_status")
        pipeline_status_lock = get_pipeline_status_lock()
        file_ref = self._get_file_reference(file_path)

        await merge_nodes_and_edges(
            chunk_results=enhanced_chunk_results,
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
            file_path=file_ref,
        )

        await self.lightrag._insert_done()

    async def _update_doc_status_with_chunks_type_aware(
        self, doc_id: str, chunk_ids: list[str]
    ):
        """Merge multimodal chunk ids into the document's chunks_list."""
        try:
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)

            if not current_doc_status:
                self.logger.warning(
                    f"doc_status record {doc_id} not found; "
                    f"{len(chunk_ids)} multimodal chunk(s) will be missing "
                    "from its chunks_list"
                )
                return

            existing_chunks_list = current_doc_status.get("chunks_list", [])
            existing_chunks_count = current_doc_status.get("chunks_count", 0)

            already_listed = set(existing_chunks_list)
            new_chunk_ids = [cid for cid in chunk_ids if cid not in already_listed]
            if not new_chunk_ids:
                self.logger.debug(
                    f"All {len(chunk_ids)} multimodal chunks already listed "
                    f"in doc_status for {doc_id}"
                )
                return

            updated_chunks_list = existing_chunks_list + new_chunk_ids
            updated_chunks_count = existing_chunks_count + len(new_chunk_ids)

            sanitized_status = self._sanitize_doc_status_record(
                {
                    **current_doc_status,
                    "chunks_list": updated_chunks_list,
                    "chunks_count": updated_chunks_count,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                }
            )
            await self.lightrag.doc_status.upsert({doc_id: sanitized_status})
            await self.lightrag.doc_status.index_done_callback()

            self.logger.info(
                f"Updated doc_status: added {len(new_chunk_ids)} multimodal chunks to standard chunks_list "
                f"(total chunks: {updated_chunks_count})"
            )

        except Exception as e:
            self.logger.warning(
                f"Error updating doc_status with multimodal chunks: {e}"
            )
