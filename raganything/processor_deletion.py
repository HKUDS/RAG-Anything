"""
Document deletion and cascading cleanup mixin for RAGAnything.

Handles cascading deletion of documents across LightRAG, multimodal status cache,
pre-registration placeholders, and on-disk parsed media directories.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from raganything.modal_ownership import (
    document_caption_entities,
    refresh_surviving_captions,
)
from typing import Any


class DocumentDeletionMixin:
    """Mixin responsible for cascading document deletion across storage and disk."""

    async def _resolve_parsed_output_dirs_for_deletion(
        self,
        doc_id: str,
        current_status: dict[str, Any] | None,
    ) -> list[tuple[Path, Path]]:
        """
        Resolve (output_base, parsed_output_dir) pairs for a document deletion.

        Checks in order of specificity:
        1. In-memory locations recorded during ``parse_document`` / ``process_document_*``
        2. ``metadata`` persisted inside ``doc_status``
        3. Entries in ``self.parse_cache`` matching ``doc_id``
        4. Legacy absolute source path with the configured output directory
        """
        pairs: list[tuple[Path, Path]] = []
        seen: set[tuple[Path, Path]] = set()

        def _add_pair(base_val: Any, dir_val: Any) -> None:
            if not base_val or not dir_val:
                return
            try:
                base_p = Path(str(base_val)).resolve()
                dir_p = Path(str(dir_val)).resolve()
                key = (base_p, dir_p)
                if key not in seen:
                    seen.add(key)
                    pairs.append(key)
            except Exception:
                pass

        loc_map = getattr(self, "_parsed_output_locations", {})
        if doc_id in loc_map:
            rec = loc_map[doc_id]
            for base_s, dir_s in rec.get("pairs", []):
                _add_pair(base_s, dir_s)
            if not rec.get("pairs"):
                base_s = rec.get("output_base")
                for dir_s in rec.get("parsed_output_dirs", []):
                    _add_pair(base_s, dir_s)

        if isinstance(current_status, dict):
            meta = current_status.get("metadata")
            if isinstance(meta, dict):
                base_s = meta.get("raganything_output_base")
                for dir_s in meta.get("raganything_parsed_output_dirs") or []:
                    _add_pair(base_s, dir_s)
                src_s = meta.get("raganything_source_file_path")
                if src_s and base_s and not pairs:
                    comp_base, comp_dirs = self._compute_parsed_output_dirs(
                        src_s, base_s
                    )
                    if comp_base is not None:
                        for d in comp_dirs:
                            _add_pair(comp_base, d)

        parse_cache = getattr(self, "parse_cache", None)
        if parse_cache is not None:
            cache_dicts: list[dict[str, Any]] = []
            for attr_name in ("_data", "entries", "records", "data"):
                raw_store = getattr(parse_cache, attr_name, None)
                if isinstance(raw_store, dict):
                    cache_dicts.extend(
                        v for v in raw_store.values() if isinstance(v, dict)
                    )
            for entry in cache_dicts:
                if entry.get("doc_id") == doc_id:
                    base_s = entry.get("output_dir") or getattr(
                        getattr(self, "config", None), "parser_output_dir", None
                    )
                    for dir_s in entry.get("parsed_output_dirs") or []:
                        _add_pair(base_s, dir_s)
                    entry_fp = entry.get("file_path")
                    if entry_fp and base_s and not entry.get("parsed_output_dirs"):
                        comp_base, comp_dirs = self._compute_parsed_output_dirs(
                            entry_fp, base_s
                        )
                        if comp_base is not None:
                            for d in comp_dirs:
                                _add_pair(comp_base, d)

        if not pairs and isinstance(current_status, dict):
            file_path = current_status.get("file_path")
            default_base = getattr(
                getattr(self, "config", None), "parser_output_dir", None
            )
            if file_path and Path(file_path).is_absolute() and default_base:
                comp_base, comp_dirs = self._compute_parsed_output_dirs(
                    file_path, default_base
                )
                if comp_base is not None:
                    for d in comp_dirs:
                        _add_pair(comp_base, d)

        return pairs

    async def adelete_by_doc_id(
        self,
        doc_id: str,
        delete_media_files: bool = False,
        delete_llm_cache: bool = False,
    ) -> dict[str, Any]:
        """
        Cascading deletion of a document from RAG-Anything and LightRAG.

        Delegates core graph/vector/KV deletion to LightRAG first, and only
        cleans up RAG-Anything state once core deletion confirms success.

        Args:
            doc_id: The document ID to delete.
            delete_media_files: If True, deletes the parsed output directory on disk.
            delete_llm_cache: If True, deletes cached LLM responses in LightRAG.

        Returns:
            Dict[str, Any] containing deletion status, counts, and metadata.
        """
        init_result = await self._ensure_lightrag_initialized()
        if isinstance(init_result, dict) and not init_result.get("success", True):
            error_msg = init_result.get(
                "error", "LightRAG initialization failed before deletion"
            )
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": str(error_msg),
                "multimodal_status_deleted": False,
                "media_files_deleted": False,
                "lightrag_result": None,
            }

        current_status = None
        if hasattr(self.lightrag, "doc_status") and self.lightrag.doc_status:
            current_status = await self.lightrag.doc_status.get_by_id(doc_id)

        doc_exists = bool(current_status)
        if (
            not doc_exists
            and hasattr(self.lightrag, "full_docs")
            and self.lightrag.full_docs
        ):
            doc_exists = bool(await self.lightrag.full_docs.get_by_id(doc_id))

        cache = getattr(self, "multimodal_status_cache", None)
        cached = (await cache.get_by_id(doc_id) if cache else None) or {}
        multimodal_cache_exists = bool(cached)

        if not doc_exists and not multimodal_cache_exists:
            return {
                "status": "not_found",
                "doc_id": doc_id,
                "message": f"Document {doc_id} not found",
                "multimodal_status_deleted": False,
                "media_files_deleted": False,
                "lightrag_result": None,
            }

        candidate_output_dirs: list[tuple[Path, Path]] = []
        shared_output_dirs: set[Path] = set()
        if delete_media_files:
            candidate_output_dirs = await self._resolve_parsed_output_dirs_for_deletion(
                doc_id, current_status
            )
            if candidate_output_dirs:
                page = 1
                while True:
                    records, total = await self.lightrag.doc_status.get_docs_paginated(
                        page=page, page_size=200
                    )
                    for other_id, record in records:
                        if other_id != doc_id:
                            shared_output_dirs.update(
                                Path(path).resolve()
                                for path in (record.metadata or {}).get(
                                    "raganything_parsed_output_dirs", []
                                )
                            )
                    if page * 200 >= total:
                        break
                    page += 1

        doc_pre_id: str | None = None
        if isinstance(current_status, dict):
            file_name = current_status.get("file_path")
            if file_name:
                candidate_pre_id = f"doc-pre-{self._get_file_reference(file_name)}"
                if candidate_pre_id != doc_id:
                    doc_pre_id = candidate_pre_id

        adelete_fn = getattr(self.lightrag, "adelete_by_doc_id", None)
        if not callable(adelete_fn):
            error_msg = (
                "Underlying LightRAG instance does not support adelete_by_doc_id; "
                "refusing partial doc_status/full_docs deletion to avoid leaving "
                "orphaned graph/vector data."
            )
            self.logger.error(error_msg)
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": error_msg,
                "multimodal_status_deleted": False,
                "media_files_deleted": False,
                "lightrag_result": {
                    "status": "failed",
                    "doc_id": doc_id,
                    "message": error_msg,
                    "status_code": 501,
                },
            }

        try:
            names = set(cached.get("pending_caption_refresh", []))
            names.update(
                await document_caption_entities(self.lightrag, doc_id, current_status)
            )
            if names and cache:
                await cache.upsert(
                    {doc_id: {**cached, "pending_caption_refresh": sorted(names)}}
                )
                await cache.index_done_callback()
            lr_res = await adelete_fn(doc_id, delete_llm_cache=delete_llm_cache)
            if hasattr(lr_res, "status"):
                lightrag_result = {
                    "status": lr_res.status,
                    "doc_id": getattr(lr_res, "doc_id", doc_id),
                    "message": getattr(lr_res, "message", ""),
                    "status_code": getattr(lr_res, "status_code", 200),
                    "file_path": getattr(lr_res, "file_path", None),
                }
            elif isinstance(lr_res, dict):
                lightrag_result = dict(lr_res)
                lightrag_result.setdefault("status", "failed")
                lightrag_result.setdefault("doc_id", doc_id)
            else:
                lightrag_result = {
                    "status": "failed",
                    "doc_id": doc_id,
                    "message": "LightRAG returned no confirmed deletion status",
                }
        except Exception as e:
            self.logger.error(
                f"Error calling LightRAG adelete_by_doc_id for {doc_id}: {e}"
            )
            error_msg = f"Failed to delete document {doc_id} from LightRAG: {e}"
            lightrag_result = {
                "status": "failed",
                "doc_id": doc_id,
                "message": str(e),
                "status_code": 500,
            }
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": error_msg,
                "multimodal_status_deleted": False,
                "media_files_deleted": False,
                "lightrag_result": lightrag_result,
            }

        res_status = str(lightrag_result.get("status") or "failed")
        lr_message = lightrag_result.get("message") or ""

        core_deletion_confirmed = res_status == "success" or (
            res_status == "not_found" and not doc_exists and multimodal_cache_exists
        )

        if not core_deletion_confirmed:
            failure_message = (
                lr_message
                if lr_message
                else f"Core deletion for document {doc_id} did not succeed (status={res_status})"
            )
            return {
                "status": res_status,
                "doc_id": doc_id,
                "message": failure_message,
                "multimodal_status_deleted": False,
                "media_files_deleted": False,
                "lightrag_result": lightrag_result,
            }

        try:
            await refresh_surviving_captions(self.lightrag, names)
        except Exception as exc:
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": f"Failed to refresh shared caption entities: {exc}",
                "multimodal_status_deleted": False,
                "media_files_deleted": False,
                "lightrag_result": lightrag_result,
            }

        multimodal_status_deleted = False
        if hasattr(self, "multimodal_status_cache") and self.multimodal_status_cache:
            try:
                if await self.multimodal_status_cache.get_by_id(doc_id):
                    await self.multimodal_status_cache.delete([doc_id])
                    await self.multimodal_status_cache.index_done_callback()
                    multimodal_status_deleted = True
            except Exception as e:
                self.logger.warning(
                    f"Error deleting multimodal status cache for {doc_id}: {e}"
                )

        media_files_deleted = False
        media_cleanup_failed = False
        if delete_media_files and candidate_output_dirs:
            for output_base, unique_dir in candidate_output_dirs:
                if any(
                    unique_dir == shared
                    or unique_dir in shared.parents
                    or shared in unique_dir.parents
                    for shared in shared_output_dirs
                ):
                    continue
                try:
                    if (
                        output_base in unique_dir.parents
                        and unique_dir.exists()
                        and unique_dir.is_dir()
                    ):
                        shutil.rmtree(unique_dir)
                        media_files_deleted = True
                except Exception as e:
                    media_cleanup_failed = True
                    self.logger.warning(
                        f"Error removing media files for {doc_id} at {unique_dir}: {e}"
                    )

            media_files_deleted = media_files_deleted and not media_cleanup_failed

            if media_files_deleted and hasattr(self, "_parsed_output_locations"):
                self._parsed_output_locations.pop(doc_id, None)

            parse_cache = getattr(self, "parse_cache", None)
            if media_files_deleted and parse_cache is not None:
                try:
                    removed_dirs = {
                        str(unique_dir) for _, unique_dir in candidate_output_dirs
                    }
                    stale_keys: list[str] = []
                    for attr_name in ("_data", "entries", "records", "data"):
                        raw_store = getattr(parse_cache, attr_name, None)
                        if isinstance(raw_store, dict):
                            for k, v in list(raw_store.items()):
                                if not isinstance(v, dict):
                                    continue
                                entry_dirs = set(v.get("parsed_output_dirs") or [])
                                if v.get("doc_id") == doc_id or bool(
                                    entry_dirs & removed_dirs
                                ):
                                    if k not in stale_keys:
                                        stale_keys.append(k)
                    if stale_keys:
                        if callable(getattr(parse_cache, "delete", None)):
                            await parse_cache.delete(stale_keys)
                            if callable(
                                getattr(parse_cache, "index_done_callback", None)
                            ):
                                await parse_cache.index_done_callback()
                        else:
                            for attr_name in ("_data", "entries", "records", "data"):
                                raw_store = getattr(parse_cache, attr_name, None)
                                if isinstance(raw_store, dict):
                                    for k in stale_keys:
                                        raw_store.pop(k, None)
                except Exception as e:
                    self.logger.debug(
                        f"Parse cache invalidation for {doc_id} after media deletion: {e}"
                    )

        if (
            doc_pre_id
            and hasattr(self.lightrag, "doc_status")
            and self.lightrag.doc_status
        ):
            try:
                if await self.lightrag.doc_status.get_by_id(doc_pre_id):
                    await self.lightrag.doc_status.delete([doc_pre_id])
                    await self.lightrag.doc_status.index_done_callback()
            except Exception as e:
                self.logger.debug(f"Pre-registration record {doc_pre_id} cleanup: {e}")

        final_status = (
            "success"
            if (res_status == "success" or multimodal_status_deleted)
            else res_status
        )
        return {
            "status": final_status,
            "doc_id": doc_id,
            "message": (
                lr_message
                if (lr_message and res_status == "success")
                else f"Successfully processed deletion for document {doc_id}"
            ),
            "multimodal_status_deleted": multimodal_status_deleted,
            "media_files_deleted": media_files_deleted,
            "lightrag_result": lightrag_result,
        }
