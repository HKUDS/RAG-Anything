"""
Document status synchronization and pipeline polling mixin for RAGAnything.

Manages document processing status, multimodal completion flags, text chunk page labels,
and LightRAG pipeline execution synchronization.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from lightrag.utils import compute_mdhash_id

from raganything.base import DocStatus
from raganything.utils import (
    annotate_chunks_with_page_idx,
    build_sanitized_page_map,
    replay_chunk_spans,
)


def _is_lightrag_token_chunker(func) -> bool:
    try:
        from lightrag.operate import chunking_by_token_size
    except ImportError:  # pragma: no cover - lightrag always provides it
        return False
    return func is chunking_by_token_size


class DocumentStatusSyncMixin:
    """Mixin responsible for doc_status records, multimodal flags, and pipeline synchronization."""

    _LEGACY_DOC_STATUS_FIELDS = frozenset(
        {"content", "multimodal_content", "scheme_name"}
    )

    @staticmethod
    def _current_doc_status_timestamp() -> str:
        """Return a stable UTC timestamp for doc_status bookkeeping."""
        return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    async def _ensure_doc_status_record(
        self,
        doc_id: str,
        file_path: str,
        *,
        scheme_name: str | None = None,
        status: DocStatus = DocStatus.READY,
    ) -> dict[str, Any]:
        """Create a minimal doc_status entry when LightRAG has not created one yet."""
        current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
        if current_doc_status:
            return current_doc_status

        timestamp = self._current_doc_status_timestamp()
        doc_status_payload: dict[str, Any] = {
            "status": status,
            "content_summary": "",
            "content_length": 0,
            "error_msg": "",
            "chunks_count": 0,
            "chunks_list": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "file_path": self._get_file_reference(file_path),
            "metadata": {"scheme_name": scheme_name} if scheme_name is not None else {},
        }

        await self.lightrag.doc_status.upsert({doc_id: doc_status_payload})
        await self.lightrag.doc_status.index_done_callback()
        return await self.lightrag.doc_status.get_by_id(doc_id) or doc_status_payload

    async def _drop_placeholder_doc_status(self, doc_id: str) -> None:
        """Remove a doc_status record for ``doc_id`` whose text LightRAG never stored."""
        if not await self.lightrag.doc_status.get_by_id(doc_id):
            return
        if not await self.lightrag.full_docs.get_by_id(doc_id):
            await self.lightrag.doc_status.delete([doc_id])

    async def _lightrag_pipeline_status_and_lock(self) -> tuple[dict[str, Any], Any]:
        """Pipeline status and its lock for this LightRAG instance's workspace.

        Calling ``get_namespace_data`` / ``get_pipeline_status_lock`` without a
        workspace resolves to LightRAG's *default* workspace (the first instance
        initialized in the process), so progress, cancellation and locking
        would hit another workspace's pipeline when several are in use.
        """
        from lightrag.kg.shared_storage import get_namespace_data, get_namespace_lock

        workspace = getattr(self.lightrag, "workspace", None)
        return (
            await get_namespace_data("pipeline_status", workspace=workspace),
            get_namespace_lock("pipeline_status", workspace=workspace),
        )

    async def _lightrag_pipeline_status(self) -> dict[str, Any]:
        """LightRAG's shared pipeline status for this workspace, or ``{}``."""
        try:
            from lightrag.kg.shared_storage import get_namespace_data

            return await get_namespace_data(
                "pipeline_status", workspace=getattr(self.lightrag, "workspace", None)
            )
        except Exception:
            return {}

    async def _wait_for_text_processing(
        self,
        doc_id: str,
        split_by_character: str | None,
        split_by_character_only: bool,
    ) -> None:
        """Return once LightRAG has finished processing the text of ``doc_id``."""
        waiting = (DocStatus.PENDING, DocStatus.PROCESSING)
        pipeline = await self._lightrag_pipeline_status()
        record = await self.lightrag.doc_status.get_by_id(doc_id)
        if record and record.get("status") in waiting:
            self.logger.info(
                f"Text of {doc_id} is queued behind another insert; waiting "
                "for LightRAG to process it"
            )
        delay = 0.2
        next_report = time.monotonic() + 300
        while record:
            status = record.get("status")
            busy = bool(pipeline.get("busy"))
            if status not in waiting and not (status == DocStatus.FAILED and busy):
                break
            if busy:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 2.0)
            elif any(
                "Pipeline cancelled by user" in str(message)
                for message in pipeline.get("history_messages") or []
            ):
                raise RuntimeError(
                    f"LightRAG's pipeline was cancelled before the text of "
                    f"{doc_id} was processed"
                )
            else:
                await self.lightrag.apipeline_process_enqueue_documents(
                    split_by_character, split_by_character_only
                )
            record = await self.lightrag.doc_status.get_by_id(doc_id)
            if time.monotonic() >= next_report:
                next_report += 300
                self.logger.warning(
                    f"Still waiting for LightRAG to process the text of {doc_id} "
                    f"(status: {record.get('status') if record else None})"
                )
        if record and record.get("status") == DocStatus.FAILED:
            prefix = f"LightRAG failed to process the text of {doc_id}: "
            error = record.get("error_msg") or "unknown error"
            raise RuntimeError(error if error.startswith(prefix) else prefix + error)

    async def _annotate_text_chunk_pages(
        self,
        doc_id: str,
        track_id: str | None,
        text_content: str,
        page_intervals: list[tuple[int, int, int | None]],
        split_by_character: str | None,
        split_by_character_only: bool,
    ) -> None:
        """Give the text chunks LightRAG stored for ``doc_id`` their pages (#330)."""
        try:
            lightrag = self.lightrag
            record = await lightrag.doc_status.get_by_id(doc_id)
            if (
                not track_id
                or not record
                or record.get("track_id") != track_id
                or record.get("status") != DocStatus.PROCESSED
            ):
                return
            chunk_ids = list(dict.fromkeys(record.get("chunks_list") or []))
            if not chunk_ids:
                return
            labels = await self._text_chunk_page_labels(
                doc_id,
                text_content,
                page_intervals,
                split_by_character,
                split_by_character_only,
                set(chunk_ids),
            )
            rows = await lightrag.text_chunks.get_by_ids(chunk_ids)
            updates = {}
            for chunk_id, row in zip(chunk_ids, rows):
                if not row or row.get("full_doc_id") != doc_id:
                    continue
                pages = labels.get(chunk_id, (None, None))
                fields = {
                    key: value
                    for key, value in zip(("page_idx", "page_idx_end"), pages)
                    if row.get(key) != value
                }
                if fields:
                    updates[chunk_id] = {**row, **fields}
            if updates:
                await lightrag.text_chunks.upsert(updates)
                await lightrag.text_chunks.index_done_callback()
        except Exception as exc:
            self.logger.warning(
                f"page_idx annotation failed; chunks stored without page "
                f"provenance: {exc}"
            )

    async def _text_chunk_page_labels(
        self,
        doc_id: str,
        text_content: str,
        page_intervals: list[tuple[int, int, int | None]],
        split_by_character: str | None,
        split_by_character_only: bool,
        recorded_ids: set,
    ) -> dict[str, tuple[int | None, int | None]]:
        """``(page_idx, page_idx_end)`` per chunk id of the stored document."""
        lightrag = self.lightrag
        if all(page is None for _, _, page in page_intervals):
            return {}
        if not _is_lightrag_token_chunker(getattr(lightrag, "chunking_func", None)):
            return {}
        sanitized, intervals = build_sanitized_page_map(text_content, page_intervals)
        stored = await lightrag.full_docs.get_by_id(doc_id)
        if not intervals or not stored or stored.get("content") != sanitized:
            return {}

        from lightrag.operate import chunking_by_token_size

        settings = (
            split_by_character,
            split_by_character_only,
            lightrag.chunk_overlap_token_size,
            lightrag.chunk_token_size,
        )
        chunks = chunking_by_token_size(lightrag.tokenizer, sanitized, *settings)
        chunk_ids = [
            compute_mdhash_id(chunk["content"], prefix="chunk-") for chunk in chunks
        ]
        if set(chunk_ids) != recorded_ids:
            return {}
        spans = replay_chunk_spans(lightrag.tokenizer, sanitized, chunks, *settings)
        if spans is None:
            self.logger.warning(
                "page_idx annotation skipped: could not reproduce how the "
                "document was chunked"
            )
            return {}
        annotate_chunks_with_page_idx(chunks, spans, intervals)

        found: dict[str, set] = {}
        for chunk_id, chunk in zip(chunk_ids, chunks):
            found.setdefault(chunk_id, set()).add(
                (chunk.get("page_idx"), chunk.get("page_idx_end"))
            )
        return {
            chunk_id: next(iter(pages))
            for chunk_id, pages in found.items()
            if len(pages) == 1
        }

    @staticmethod
    def _doc_status_supports_multimodal_processed() -> bool:
        """Return False if LightRAG's DocProcessingStatus dataclass rejects multimodal_processed."""
        from lightrag.base import DocProcessingStatus

        return "multimodal_processed" in DocProcessingStatus.__dataclass_fields__

    def _sanitize_doc_status_record(
        self,
        record: dict[str, Any],
        *,
        allow_multimodal_processed: bool | None = None,
    ) -> dict[str, Any]:
        """Strip undeclared legacy keys before persisting a doc_status record."""
        if allow_multimodal_processed is None:
            allow_multimodal_processed = (
                self._doc_status_supports_multimodal_processed()
            )
        forbidden = set(self._LEGACY_DOC_STATUS_FIELDS)
        if not allow_multimodal_processed:
            forbidden.add("multimodal_processed")
        cleaned = {k: v for k, v in record.items() if k not in forbidden}
        if "scheme_name" in record and record["scheme_name"] is not None:
            existing_meta = cleaned.get("metadata")
            meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
            meta.setdefault("scheme_name", record["scheme_name"])
            cleaned["metadata"] = meta
        return cleaned

    async def _upsert_doc_status(
        self,
        doc_id: str,
        file_path: str,
        *,
        scheme_name: str | None = None,
        **updates,
    ) -> dict[str, Any]:
        """Merge doc_status updates while preserving any existing LightRAG fields."""
        current_doc_status = await self._ensure_doc_status_record(
            doc_id,
            file_path,
            scheme_name=scheme_name,
        )
        raw_updated = {
            **current_doc_status,
            **updates,
            "updated_at": self._current_doc_status_timestamp(),
        }
        updated_doc_status = self._sanitize_doc_status_record(raw_updated)
        await self.lightrag.doc_status.upsert({doc_id: updated_doc_status})
        await self.lightrag.doc_status.index_done_callback()
        return updated_doc_status

    async def _get_multimodal_status_record(self, doc_id: str) -> dict[str, Any] | None:
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
        self, doc_id: str, doc_status: dict[str, Any] | None = None
    ) -> bool:
        """Read multimodal completion state from doc_status or compatibility cache."""
        if doc_status is not None and "multimodal_processed" in doc_status:
            return bool(doc_status.get("multimodal_processed", False))

        compatibility_status = await self._get_multimodal_status_record(doc_id)
        if compatibility_status is not None:
            return bool(compatibility_status.get("multimodal_processed", False))

        return False

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
                loc_record = getattr(self, "_parsed_output_locations", {}).get(doc_id)
                if loc_record:
                    existing_meta = update_payload.get("metadata")
                    meta = (
                        dict(existing_meta) if isinstance(existing_meta, dict) else {}
                    )
                    meta.update(
                        {
                            "raganything_output_base": loc_record["output_base"],
                            "raganything_parsed_output_dirs": list(
                                loc_record["parsed_output_dirs"]
                            ),
                            "raganything_source_file_path": loc_record[
                                "source_file_path"
                            ],
                        }
                    )
                    update_payload["metadata"] = meta
                supports_mm_field = self._doc_status_supports_multimodal_processed()
                update_payload = self._sanitize_doc_status_record(update_payload)
                try:
                    await self.lightrag.doc_status.upsert({doc_id: update_payload})
                except (TypeError, ValueError) as exc:
                    self.logger.debug(
                        "Falling back to schema-compatible doc_status update for %s: %s",
                        doc_id,
                        exc,
                    )
                    fallback_payload = {
                        k: v
                        for k, v in update_payload.items()
                        if k != "multimodal_processed"
                    }
                    fallback_payload.update(
                        {
                            "status": final_status,
                            "updated_at": self._current_doc_status_timestamp(),
                        }
                    )
                    await self.lightrag.doc_status.upsert({doc_id: fallback_payload})
                    supports_mm_field = False
                if not supports_mm_field:
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

    async def get_document_processing_status(self, doc_id: str) -> dict[str, Any]:
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
