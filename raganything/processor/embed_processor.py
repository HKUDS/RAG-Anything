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



class EmbedProcessorMixin:
    """Embedding, entity storage, and low-degree entity filtering."""
    async def _store_chunks_to_lightrag_storage_type_aware(
        self, chunks: Dict[str, Any]
    ):
        """Store chunks to storage with batched embedding for speed.

        Chunks are grouped into batches to reduce API round-trips (configured
        via EMBEDDING_BATCH_SIZE env var). Failed batches are retried
        individually to ensure no data loss.
        """
        try:
            # Store in text_chunks storage (no embedding, safe to batch)
            await self.lightrag.text_chunks.upsert(chunks)

            batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
            chunk_items = list(chunks.items())
            failed_ids: list[str] = []
            total_batches = (len(chunk_items) + batch_size - 1) // batch_size

            for batch_idx in range(0, len(chunk_items), batch_size):
                batch = dict(chunk_items[batch_idx:batch_idx + batch_size])
                batch_num = batch_idx // batch_size + 1
                try:
                    await self.lightrag.chunks_vdb.upsert(batch)
                    self.logger.debug(
                        f"Batch {batch_num}/{total_batches}: embedded {len(batch)} chunks"
                    )
                except Exception as batch_err:
                    self.logger.warning(
                        f"Batch {batch_num}/{total_batches} failed ({batch_err}), "
                        f"retrying individually..."
                    )
                    # Fallback: retry each chunk in the failed batch individually
                    for cid, cdata in batch.items():
                        try:
                            await self.lightrag.chunks_vdb.upsert({cid: cdata})
                        except Exception as chunk_err:
                            failed_ids.append(cid)
                            self.logger.warning(
                                f"Chunk {cid[:20]}... embedding failed "
                                f"(skipped): {chunk_err}"
                            )

            # ── 持久化：确保 text_chunks 和 chunks_vdb 从内存刷到磁盘 ──
            # JsonKVStorage.upsert() 和 NanoVectorDB.upsert() 仅写入内存，
            # index_done_callback() 才真正落盘。若不调用，服务器重启后
            # 所有多模态 chunk 数据（文本 + 向量）丢失。
            await self.lightrag.text_chunks.index_done_callback()
            await self.lightrag.chunks_vdb.index_done_callback()

            if failed_ids:
                self.logger.warning(
                    f"{len(failed_ids)}/{len(chunks)} chunks skipped due to "
                    f"embedding errors"
                )
            else:
                self.logger.info(
                    f"Stored {len(chunks)} multimodal chunks to storage "
                    f"({total_batches} batches, batch_size={batch_size})"
                )

        except Exception as e:
            self.logger.error(f"Error storing chunks to storage: {e}")
            raise

    async def _store_multimodal_main_entities(
        self,
        multimodal_data_list: List[Dict[str, Any]],
        lightrag_chunks: Dict[str, Any],
        file_path: str,
        doc_id: str = None,
    ):
        """
        Store multimodal main entities to entities_vdb and full_entities.
        This ensures that entities like "TableName (table)" are properly indexed.

        Args:
            multimodal_data_list: List of processed multimodal data with entity info
            lightrag_chunks: Chunks in LightRAG format (already formatted with templates)
            file_path: File path for the entities
            doc_id: Document ID for full_entities storage
        """
        if not multimodal_data_list:
            return

        # Create entities_vdb entries for all multimodal main entities
        entities_to_store = {}

        # Use full path or basename based on config
        file_ref = self._get_file_reference(file_path)

        for data in multimodal_data_list:
            entity_info = data["entity_info"]
            entity_name = entity_info["entity_name"]
            description = data["description"]
            content_type = data["content_type"]
            original_item = data["original_item"]

            # Apply the same chunk template to get the formatted content
            formatted_chunk_content = self._apply_chunk_template(
                content_type, original_item, description
            )

            # Truncate before computing chunk_id, MUST match
            # _convert_to_lightrag_chunks_type_aware (line ~1350).
            # Otherwise entity source_id points to a hash of untruncated content
            # while text_chunks_db stores the chunk under the hash of truncated
            # content, causing every chunk lookup to return None.
            _MAX_CHUNK_CHARS = 8000
            if len(formatted_chunk_content) > _MAX_CHUNK_CHARS:
                formatted_chunk_content = (
                    formatted_chunk_content[:_MAX_CHUNK_CHARS]
                    + "\n\n[内容已截断，超出嵌入模型长度限制]"
                )

            # Generate chunk_id using the formatted content (same as in _convert_to_lightrag_chunks)
            chunk_id = compute_mdhash_id(formatted_chunk_content, prefix="chunk-")

            # Generate entity_id using LightRAG's standard format
            entity_id = compute_mdhash_id(entity_name, prefix="ent-")

            # Create entity data in LightRAG format
            entity_data = {
                "entity_name": entity_name,
                "entity_type": entity_info.get("entity_type", content_type),
                "content": f"{entity_name}\n{entity_info.get('summary', description)}",
                "source_id": chunk_id,
                "file_path": file_ref,
            }

            entities_to_store[entity_id] = entity_data

        if entities_to_store:
            try:
                # Store entities in knowledge graph
                for entity_id, entity_data in entities_to_store.items():
                    entity_name = entity_data["entity_name"]

                    # Create node data for knowledge graph
                    node_data = {
                        "entity_id": entity_name,
                        "entity_type": entity_data["entity_type"],
                        "description": entity_data["content"],
                        "source_id": entity_data["source_id"],
                        "file_path": entity_data["file_path"],
                        "created_at": int(time.time()),
                    }

                    # Store in knowledge graph
                    await self.lightrag.chunk_entity_relation_graph.upsert_node(
                        entity_name, node_data
                    )

                # Store in entities_vdb
                await self.lightrag.entities_vdb.upsert(entities_to_store)
                await self.lightrag.entities_vdb.index_done_callback()

                # NEW: Store multimodal main entities in full_entities storage
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

    async def _store_multimodal_entities_to_full_entities(
        self, entities_to_store: Dict[str, Any], doc_id: str
    ):
        """
        Store multimodal main entities to full_entities storage.

        Args:
            entities_to_store: Dictionary of entities to store
            doc_id: Document ID for grouping entities
        """
        try:
            # Get current full_entities data for this document
            current_doc_entities = await self.lightrag.full_entities.get_by_id(doc_id)

            if current_doc_entities is None:
                # Create new document entry
                entity_names = [
                    entity_data["entity_name"]
                    for entity_data in entities_to_store.values()
                ]
                doc_entities_data = {
                    "entity_names": entity_names,
                    "count": len(entity_names),
                    "update_time": int(time.time()),
                }
            else:
                # Update existing document entry while preserving any existing
                # metadata fields stored by the text pipeline.
                existing_entity_names = list(
                    current_doc_entities.get("entity_names", [])
                )
                seen_entity_names = set(existing_entity_names)

                for entity_data in entities_to_store.values():
                    entity_name = entity_data["entity_name"]
                    if entity_name not in seen_entity_names:
                        existing_entity_names.append(entity_name)
                        seen_entity_names.add(entity_name)

                doc_entities_data = {
                    **current_doc_entities,
                    "entity_names": existing_entity_names,
                    "count": len(existing_entity_names),
                    "update_time": int(time.time()),
                }

            # Store updated data
            await self.lightrag.full_entities.upsert({doc_id: doc_entities_data})
            await self.lightrag.full_entities.index_done_callback()

            self.logger.debug(
                f"Added {len(entities_to_store)} multimodal main entities to full_entities for doc {doc_id}"
            )

        except Exception as e:
            self.logger.error(
                f"Error storing multimodal entities to full_entities: {e}"
            )
            raise
    async def _filter_low_degree_entities(self, doc_id: str | None = None) -> int:
        """Remove entity nodes whose graph degree is below the configured threshold.

        This is a post-extraction quality filter. After all entities and
        relations have been merged into ``chunk_entity_relation_graph``,
        isolated entities (degree < ``entity_extraction_min_degree``) are
        removed from the graph, ``entities_vdb``, and ``full_entities``.
        Their associated text chunks are **not** deleted — only the entity
        nodes themselves.

        Args:
            doc_id: Optional document ID. When provided, only that document's
                    entities are scanned in ``full_entities`` cleanup.

        Returns:
            Number of entities removed.
        """
        min_degree = self.config.entity_extraction_min_degree
        if min_degree <= 0:
            return 0

        graph = self.lightrag.chunk_entity_relation_graph
        if graph is None:
            return 0

        try:
            all_nodes = await graph.get_all_nodes()
        except Exception as e:
            self.logger.warning(
                "Failed to enumerate graph nodes for connectivity filter: %s", e
            )
            return 0

        # Compute entity degrees from edges in one shot (avoids N node_degree calls)
        degree_map: dict[str, int] = {}
        try:
            all_edges = await graph.get_all_edges()
            if all_edges:
                for edge in all_edges:
                    src = edge.get("source", "")
                    tgt = edge.get("target", "")
                    if src:
                        degree_map[src] = degree_map.get(src, 0) + 1
                    if tgt:
                        degree_map[tgt] = degree_map.get(tgt, 0) + 1
        except Exception as e:
            self.logger.warning(
                "Failed to enumerate edges for degree computation: %s", e
            )

        to_remove = []
        for node_data in all_nodes:
            node_id = node_data.get("entity_id") or node_data.get("entity_name", "")
            if not node_id:
                continue
            degree = degree_map.get(node_id, 0)
            if degree < min_degree:
                to_remove.append(node_id)

        if not to_remove:
            return 0

        self.logger.info(
            "Connectivity filter: removing %d entities with degree < %d",
            len(to_remove),
            min_degree,
        )

        # Remove from chunk_entity_relation_graph
        for node_id in to_remove:
            try:
                await graph.delete_node(node_id)
            except Exception as e:
                self.logger.debug(
                    "Failed to remove entity node %s from graph: %s", node_id, e
                )

        # Remove from entities_vdb (vector index)
        if hasattr(self.lightrag, "entities_vdb") and self.lightrag.entities_vdb:
            try:
                # entities_vdb.delete_entity(entity_id) or delete([entity_ids])
                for node_id in to_remove:
                    try:
                        await self.lightrag.entities_vdb.delete_entity(node_id)
                    except Exception:
                        pass
            except Exception as e:
                self.logger.warning(
                    "Failed to clean entities_vdb for filtered entities: %s", e
                )

        # Remove from full_entities (persistent entity store by doc)
        if (
            doc_id
            and hasattr(self.lightrag, "full_entities")
            and self.lightrag.full_entities
        ):
            try:
                doc_data = await self.lightrag.full_entities.get_by_id(doc_id)
                if doc_data:
                    doc_entities = doc_data.get("entity_names", [])
                    if doc_entities:
                        remove_set = set(to_remove)
                        filtered = [
                            e
                            for e in doc_entities
                            if e not in remove_set
                        ]
                        if len(filtered) != len(doc_entities):
                            doc_data["entity_names"] = filtered
                            await self.lightrag.full_entities.upsert(
                                {doc_id: doc_data}
                            )
                            self.logger.debug(
                                "Cleaned %d filtered entities from full_entities doc %s",
                                len(doc_entities) - len(filtered),
                                doc_id,
                            )
            except Exception as e:
                self.logger.warning(
                    "Failed to clean full_entities for filtered entities: %s", e
                )

        return len(to_remove)
