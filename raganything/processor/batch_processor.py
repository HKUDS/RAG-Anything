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




# Module-level registry of pending background tasks.
# Subprocess entry points (process_worker.py) await these before exiting
# so that async multimodal processing is not killed mid-flight.
_pending_background_tasks: "set[asyncio.Task]" = set()


def register_background_task(task: "asyncio.Task") -> None:
    """Register a background task so subprocesses can await it before exit."""
    _pending_background_tasks.add(task)
    task.add_done_callback(lambda t: _pending_background_tasks.discard(t))


def get_pending_background_tasks() -> "set[asyncio.Task]":
    """Return a snapshot of currently pending background tasks."""
    return set(_pending_background_tasks)


class BatchProcessorMixin:
    """Background task management and batch entity operations."""
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
    async def _batch_extract_entities_lightrag_style_type_aware(
        self, lightrag_chunks: Dict[str, Any]
    ) -> List[Tuple]:
        """Use LightRAG's extract_entities for batch entity relation extraction"""
        from lightrag.kg.shared_storage import (
            get_namespace_data,
            get_pipeline_status_lock,
        )
        from lightrag.operate import extract_entities

        # Get pipeline status (consistent with LightRAG)
        pipeline_status = await get_namespace_data("pipeline_status")
        pipeline_status_lock = get_pipeline_status_lock()

        # Directly use LightRAG's extract_entities
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
        self, chunk_results: List[Tuple], multimodal_data_list: List[Dict[str, Any]]
    ) -> List[Tuple]:
        """Add belongs_to relations for multimodal entities"""
        # Create mapping from chunk_id to modal_entity_name
        chunk_to_modal_entity = {}
        chunk_to_file_path = {}

        for data in multimodal_data_list:
            description = data["description"]
            content_type = data["content_type"]
            original_item = data["original_item"]

            # Use the unified chunk_id helper (includes 8000-char truncation).
            # Must match _convert_to_lightrag_chunks_type_aware and all other
            # chunk_id computation sites.  Never call compute_mdhash_id directly.
            formatted_chunk_content = self._apply_chunk_template(
                content_type, original_item, description
            )
            chunk_id = self._compute_chunk_id(formatted_chunk_content)

            chunk_to_modal_entity[chunk_id] = data["entity_info"]["entity_name"]
            chunk_to_file_path[chunk_id] = data.get("file_path", "multimodal_content")

        enhanced_chunk_results = []
        belongs_to_count = 0

        for maybe_nodes, maybe_edges in chunk_results:
            # Find corresponding modal_entity_name for this chunk
            chunk_id = None
            for nodes_dict in maybe_nodes.values():
                if nodes_dict:
                    chunk_id = nodes_dict[0].get("source_id")
                    break

            if chunk_id and chunk_id in chunk_to_modal_entity:
                modal_entity_name = chunk_to_modal_entity[chunk_id]
                file_path = chunk_to_file_path.get(chunk_id, "multimodal_content")

                # Add belongs_to relations for all extracted entities
                for entity_name in maybe_nodes.keys():
                    if entity_name != modal_entity_name:  # Avoid self-relation
                        belongs_to_relation = {
                            "src_id": entity_name,
                            "tgt_id": modal_entity_name,
                            "description": f"Entity {entity_name} belongs to {modal_entity_name}",
                            "keywords": "belongs_to,part_of,contained_in",
                            "source_id": chunk_id,
                            "weight": 10.0,
                            "file_path": file_path,
                        }

                        # Add to maybe_edges
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
        self, enhanced_chunk_results: List[Tuple], file_path: str, doc_id: str = None
    ):
        """Use LightRAG's merge_nodes_and_edges for batch merge

        NOTE: LightRAG's merge_nodes_and_edges Phase 3 **overwrites**
        full_entities[doc_id] / full_relations[doc_id] via upsert instead
        of merging.  For mixed text+multimodal documents the text pipeline
        has already written a complete entity list there; the multimodal
        merge would clobber it, making text entities invisible to
        ``adelete_by_doc_id`` and leaving them as undeletable orphans.

        We work around this by saving the pre-merge state and re-merging
        the union of old and new entity/relation names after the call.
        """
        from lightrag.kg.shared_storage import (
            get_namespace_data,
            get_pipeline_status_lock,
        )
        from lightrag.operate import merge_nodes_and_edges

        pipeline_status = await get_namespace_data("pipeline_status")
        pipeline_status_lock = get_pipeline_status_lock()

        # Use full path or basename based on config
        file_ref = self._get_file_reference(file_path)

        # Save pre-merge state so we can restore text entities that
        # merge_nodes_and_edges would otherwise drop.
        prev_full_entities = None
        prev_full_relations = None
        if doc_id:
            prev_full_entities = await self.lightrag.full_entities.get_by_id(doc_id)
            prev_full_relations = await self.lightrag.full_relations.get_by_id(doc_id)

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

        # ── Fix: restore text entities that merge_nodes_and_edges overwrote ──
        if doc_id and prev_full_entities:
            current_entities = (
                await self.lightrag.full_entities.get_by_id(doc_id) or {}
            )
            current_names = set(current_entities.get("entity_names", []))
            prev_names = set(prev_full_entities.get("entity_names", []))
            merged_names = current_names | prev_names
            if merged_names != current_names:
                await self.lightrag.full_entities.upsert({
                    doc_id: {
                        "entity_names": list(merged_names),
                        "count": len(merged_names),
                    }
                })
                self.logger.debug(
                    f"Restored {len(merged_names) - len(current_names)} "
                    f"text entities to full_entities[{doc_id}]"
                )

        if doc_id and prev_full_relations:
            current_relations = (
                await self.lightrag.full_relations.get_by_id(doc_id) or {}
            )
            current_pairs = {
                tuple(p) for p in current_relations.get("relation_pairs", [])
            }
            prev_pairs = {
                tuple(p) for p in prev_full_relations.get("relation_pairs", [])
            }
            merged_pairs = current_pairs | prev_pairs
            if merged_pairs != current_pairs:
                await self.lightrag.full_relations.upsert({
                    doc_id: {
                        "relation_pairs": [list(p) for p in merged_pairs],
                        "count": len(merged_pairs),
                    }
                })
                self.logger.debug(
                    f"Restored {len(merged_pairs) - len(current_pairs)} "
                    f"text relations to full_relations[{doc_id}]"
                )

        await self.lightrag._insert_done()
