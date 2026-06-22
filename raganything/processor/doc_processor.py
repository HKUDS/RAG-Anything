# -*- coding: utf-8 -*-
"""
Document Processor Mixin — Document Ingestion Pipeline.

Layer: Core
Primary Responsibility: DocProcessorMixin — document parsing, caching,
    doc_status lifecycle, content insertion, and complete document processing
    orchestration.
Key Dependencies: lightrag (LightRAG, compute_mdhash_id), raganything.parser,
    raganything.utils (separate_content, insert_text_content)

Call chain:
    process_document_complete()
      → parse_document()          — parser invocation + caching
      → _ensure_doc_status_record() — doc_status lifecycle
      → insert_content_list()     — text + multimodal insertion
        → insert_text_content_with_multimodal_content()
        → get_processor_for_type()
      → _schedule_bm25_index_update()

    parse_document()
      → _get_cached_result() → _store_cached_result()
"""

from __future__ import annotations

from .batch_processor import register_background_task

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



class DocProcessorMixin:
    """Document parsing, caching, and processing entry points."""
    def _generate_cache_key(
        self, file_path: Path, parse_method: str = None, **kwargs
    ) -> str:
        """
        Generate cache key based on file path and parsing configuration

        Args:
            file_path: Path to the file
            parse_method: Parse method used
            **kwargs: Additional parser parameters

        Returns:
            str: Cache key for the file and configuration
        """

        # Get file modification time
        mtime = file_path.stat().st_mtime

        # Create configuration dict for cache key
        config_dict = {
            "file_path": str(file_path.absolute()),
            "mtime": mtime,
            "parser": self.config.parser,
            "parse_method": parse_method or self.config.parse_method,
        }

        # Add relevant kwargs to config
        relevant_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            in [
                "lang",
                "device",
                "start_page",
                "end_page",
                "formula",
                "table",
                "backend",
                "source",
            ]
        }
        config_dict.update(relevant_kwargs)

        # Generate hash from config
        config_str = json.dumps(config_dict, sort_keys=True)
        cache_key = hashlib.md5(config_str.encode()).hexdigest()

        return cache_key

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
    ) -> Dict[str, Any]:
        """Create a minimal doc_status entry when LightRAG has not created one yet."""
        current_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
        if current_doc_status:
            return current_doc_status

        timestamp = self._current_doc_status_timestamp()
        doc_status_payload: Dict[str, Any] = {
            "status": status,
            "content": "",
            "content_summary": "",
            "content_length": 0,
            "error_msg": "",
            "chunks_count": 0,
            "chunks_list": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "file_path": self._get_file_reference(file_path),
        }
        if scheme_name is not None:
            doc_status_payload["scheme_name"] = scheme_name

        await self.lightrag.doc_status.upsert({doc_id: doc_status_payload})
        await self.lightrag.doc_status.index_done_callback()
        return await self.lightrag.doc_status.get_by_id(doc_id) or doc_status_payload

    async def _upsert_doc_status(
        self,
        doc_id: str,
        file_path: str,
        *,
        scheme_name: str | None = None,
        **updates,
    ) -> Dict[str, Any]:
        """Merge doc_status updates while preserving any existing LightRAG fields."""
        current_doc_status = await self._ensure_doc_status_record(
            doc_id,
            file_path,
            scheme_name=scheme_name,
        )
        updated_doc_status = {
            **current_doc_status,
            **updates,
            "updated_at": self._current_doc_status_timestamp(),
        }
        await self.lightrag.doc_status.upsert({doc_id: updated_doc_status})
        await self.lightrag.doc_status.index_done_callback()
        return updated_doc_status
    def _generate_content_based_doc_id(self, content_list: List[Dict[str, Any]]) -> str:
        """
        Generate doc_id based on document content

        Args:
            content_list: Parsed content list

        Returns:
            str: Content-based document ID with doc- prefix
        """
        from lightrag.utils import compute_mdhash_id

        # Extract key content for ID generation
        content_hash_data = []

        for item in content_list:
            if isinstance(item, dict):
                # For text content, use the text
                if item.get("type") == "text" and item.get("text"):
                    content_hash_data.append(item["text"].strip())
                # For other content types, use key identifiers
                elif item.get("type") == "image" and item.get("img_path"):
                    content_hash_data.append(f"image:{item['img_path']}")
                elif item.get("type") == "table" and item.get("table_body"):
                    content_hash_data.append(f"table:{item['table_body']}")
                elif item.get("type") == "equation" and item.get("text"):
                    content_hash_data.append(f"equation:{item['text']}")
                else:
                    # For other types, use string representation
                    content_hash_data.append(str(item))

        # Create a content signature
        content_signature = "\n".join(content_hash_data)

        # Generate doc_id from content
        doc_id = compute_mdhash_id(content_signature, prefix="doc-")

        return doc_id

    async def _get_cached_result(
        self, cache_key: str, file_path: Path, parse_method: str = None, **kwargs
    ) -> tuple[List[Dict[str, Any]], str] | None:
        """
        Get cached parsing result if available and valid

        Args:
            cache_key: Cache key to look up
            file_path: Path to the file for mtime check
            parse_method: Parse method used
            **kwargs: Additional parser parameters

        Returns:
            tuple[List[Dict[str, Any]], str] | None: (content_list, doc_id) or None if not found/invalid
        """
        if not hasattr(self, "parse_cache") or self.parse_cache is None:
            return None

        try:
            cached_data = await self.parse_cache.get_by_id(cache_key)
            if not cached_data:
                return None

            # Check file modification time
            current_mtime = file_path.stat().st_mtime
            cached_mtime = cached_data.get("mtime", 0)

            if current_mtime != cached_mtime:
                self.logger.debug(f"Cache invalid - file modified: {cache_key}")
                return None

            # Check parsing configuration
            cached_config = cached_data.get("parse_config", {})
            current_config = {
                "parser": self.config.parser,
                "parse_method": parse_method or self.config.parse_method,
            }

            # Add relevant kwargs to current config
            relevant_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k
                in [
                    "lang",
                    "device",
                    "start_page",
                    "end_page",
                    "formula",
                    "table",
                    "backend",
                    "source",
                ]
            }
            current_config.update(relevant_kwargs)

            if cached_config != current_config:
                self.logger.debug(f"Cache invalid - config changed: {cache_key}")
                return None

            content_list = cached_data.get("content_list", [])
            doc_id = cached_data.get("doc_id")

            if content_list and doc_id:
                self.logger.debug(
                    f"Found valid cached parsing result for key: {cache_key}"
                )
                return content_list, doc_id
            else:
                self.logger.debug(
                    f"Cache incomplete - missing content or doc_id: {cache_key}"
                )
                return None

        except Exception as e:
            self.logger.warning(f"Error accessing parse cache: {e}")

        return None

    async def _store_cached_result(
        self,
        cache_key: str,
        content_list: List[Dict[str, Any]],
        doc_id: str,
        file_path: Path,
        parse_method: str = None,
        **kwargs,
    ) -> None:
        """
        Store parsing result in cache

        Args:
            cache_key: Cache key to store under
            content_list: Content list to cache
            doc_id: Content-based document ID
            file_path: Path to the file for mtime storage
            parse_method: Parse method used
            **kwargs: Additional parser parameters
        """
        if not hasattr(self, "parse_cache") or self.parse_cache is None:
            return

        try:
            # Get file modification time
            file_mtime = file_path.stat().st_mtime

            # Create parsing configuration
            parse_config = {
                "parser": self.config.parser,
                "parse_method": parse_method or self.config.parse_method,
            }

            # Add relevant kwargs to config
            relevant_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k
                in [
                    "lang",
                    "device",
                    "start_page",
                    "end_page",
                    "formula",
                    "table",
                    "backend",
                    "source",
                ]
            }
            parse_config.update(relevant_kwargs)

            cache_data = {
                cache_key: {
                    "content_list": content_list,
                    "doc_id": doc_id,
                    "mtime": file_mtime,
                    "parse_config": parse_config,
                    "cached_at": time.time(),
                    "cache_version": "1.0",
                }
            }
            await self.parse_cache.upsert(cache_data)
            # Ensure data is persisted to disk
            await self.parse_cache.index_done_callback()
            self.logger.info(f"Stored parsing result in cache: {cache_key}")
        except Exception as e:
            self.logger.warning(f"Error storing to parse cache: {e}")
    async def parse_document(
        self,
        file_path: str,
        output_dir: str = None,
        parse_method: str = None,
        display_stats: bool = None,
        **kwargs,
    ) -> tuple[List[Dict[str, Any]], str]:
        """
        Parse document with caching support

        Args:
            file_path: Path to the file to parse
            output_dir: Output directory (defaults to config.parser_output_dir)
            parse_method: Parse method (defaults to config.parse_method)
            display_stats: Whether to display content statistics (defaults to config.display_content_stats)
            **kwargs: Additional parameters for parser (e.g., lang, device, start_page, end_page, formula, table, backend, source)

        Returns:
            tuple[List[Dict[str, Any]], str]: (content_list, doc_id)
        """
        # Use config defaults if not provided
        if output_dir is None:
            output_dir = self.config.parser_output_dir
        if parse_method is None:
            parse_method = self.config.parse_method
        if display_stats is None:
            display_stats = self.config.display_content_stats

        self.logger.info(f"Starting document parsing: {file_path}")

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        callback_file = str(file_path)
        callback_manager = getattr(self, "callback_manager", None)
        parse_start_time = time.time()
        if callback_manager is not None:
            callback_manager.dispatch(
                "on_parse_start",
                file_path=callback_file,
                parser=self.config.parser,
            )

        # Generate cache key based on file and configuration
        cache_key = self._generate_cache_key(file_path, parse_method, **kwargs)

        # Check cache first
        cached_result = await self._get_cached_result(
            cache_key, file_path, parse_method, **kwargs
        )
        if cached_result is not None:
            content_list, doc_id = cached_result
            self.logger.info(f"Using cached parsing result for: {file_path}")
            if display_stats:
                self.logger.info(
                    f"* Total blocks in cached content_list: {len(content_list)}"
                )
            if callback_manager is not None:
                duration = time.time() - parse_start_time
                callback_manager.dispatch(
                    "on_parse_complete",
                    file_path=callback_file,
                    content_blocks=len(content_list),
                    doc_id=doc_id,
                    duration_seconds=duration,
                )
            return content_list, doc_id

        # Choose appropriate parsing method based on file extension
        ext = file_path.suffix.lower()

        try:
            doc_parser = getattr(self, "doc_parser", None)
            if doc_parser is None:
                doc_parser = get_parser(self.config.parser)
                self.doc_parser = doc_parser

            # Log parser and method information
            self.logger.info(
                f"Using {self.config.parser} parser with method: {parse_method}"
            )

            if ext in [".pdf"]:
                self.logger.info("Detected PDF file, using parser for PDF...")
                content_list = await asyncio.to_thread(
                    doc_parser.parse_pdf,
                    pdf_path=file_path,
                    output_dir=output_dir,
                    method=parse_method,
                    **kwargs,
                )
            elif ext in [
                ".jpg",
                ".jpeg",
                ".png",
                ".bmp",
                ".tiff",
                ".tif",
                ".gif",
                ".webp",
            ]:
                self.logger.info("Detected image file, using parser for images...")
                try:
                    content_list = await asyncio.to_thread(
                        doc_parser.parse_image,
                        image_path=file_path,
                        output_dir=output_dir,
                        **kwargs,
                    )
                except NotImplementedError:
                    # Fallback to MinerU for image parsing if current parser doesn't support it
                    self.logger.warning(
                        f"{self.config.parser} parser doesn't support image parsing, falling back to MinerU"
                    )
                    content_list = await asyncio.to_thread(
                        MineruParser().parse_image,
                        image_path=file_path,
                        output_dir=output_dir,
                        **kwargs,
                    )
            elif ext in [
                ".doc",
                ".docx",
                ".ppt",
                ".pptx",
                ".xls",
                ".xlsx",
                ".html",
                ".htm",
                ".xhtml",
            ]:
                self.logger.info(
                    "Detected Office or HTML document, using parser for Office/HTML..."
                )
                content_list = await asyncio.to_thread(
                    doc_parser.parse_office_doc,
                    doc_path=file_path,
                    output_dir=output_dir,
                    **kwargs,
                )
            elif ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]:
                # Video files: create a simple content list for multimodal processing
                self.logger.info(
                    f"Detected video file: {file_path}, routing to video processor..."
                )
                content_list = [{
                    "type": "video",
                    "video_path": str(file_path),
                }]
            else:
                # For other or unknown formats, use generic parser
                self.logger.info(
                    f"Using generic parser for {ext} file (method={parse_method})..."
                )
                content_list = await asyncio.to_thread(
                    doc_parser.parse_document,
                    file_path=file_path,
                    method=parse_method,
                    output_dir=output_dir,
                    **kwargs,
                )

        except MineruExecutionError as e:
            self.logger.error(f"Mineru command failed: {e}")
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_parse_error",
                    file_path=callback_file,
                    error=e,
                    parser=self.config.parser,
                )
            raise
        except Exception as e:
            self.logger.error(
                f"Error during parsing with {self.config.parser} parser: {str(e)}"
            )
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_parse_error",
                    file_path=callback_file,
                    error=e,
                    parser=self.config.parser,
                )
            raise

        msg = f"Parsing {file_path} complete! Extracted {len(content_list)} content blocks"
        self.logger.info(msg)

        if len(content_list) == 0:
            raise ValueError("Parsing failed: No content was extracted")

        # Generate doc_id based on content
        doc_id = self._generate_content_based_doc_id(content_list)

        # Store result in cache
        await self._store_cached_result(
            cache_key, content_list, doc_id, file_path, parse_method, **kwargs
        )

        # Display content statistics if requested
        if display_stats:
            self.logger.info("\nContent Information:")
            self.logger.info(f"* Total blocks in content_list: {len(content_list)}")

            # Count elements by type
            block_types: Dict[str, int] = {}
            for block in content_list:
                if isinstance(block, dict):
                    block_type = block.get("type", "unknown")
                    if isinstance(block_type, str):
                        block_types[block_type] = block_types.get(block_type, 0) + 1

            self.logger.info("* Content block types:")
            for block_type, count in block_types.items():
                self.logger.info(f"  - {block_type}: {count}")

        if callback_manager is not None:
            duration = time.time() - parse_start_time
            callback_manager.dispatch(
                "on_parse_complete",
                file_path=callback_file,
                content_blocks=len(content_list),
                doc_id=doc_id,
                duration_seconds=duration,
            )

        return content_list, doc_id
    async def process_document_complete(
        self,
        file_path: str,
        output_dir: str = None,
        parse_method: str = None,
        display_stats: bool = None,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        doc_id: str | None = None,
        file_name: str | None = None,
        **kwargs,
    ):
        """
        Complete document processing workflow

        Args:
            file_path: Path to the file to process
            output_dir: output directory (defaults to config.parser_output_dir)
            parse_method: Parse method (defaults to config.parse_method)
            display_stats: Whether to display content statistics (defaults to config.display_content_stats)
            split_by_character: Optional character to split the text by
            split_by_character_only: If True, split only by the specified character
            doc_id: Optional document ID, if not provided will be generated from content
            **kwargs: Additional parameters for parser (e.g., lang, device, start_page, end_page, formula, table, backend, source)
        """
        callback_manager = getattr(self, "callback_manager", None)
        doc_start_time = time.time()
        stage = "parse"
        file_name = file_name or self._get_file_reference(file_path)

        try:
            # Ensure LightRAG is initialized
            init_result = await self._ensure_lightrag_initialized()
            if not init_result or not init_result.get("success"):
                raise RuntimeError(
                    f"LightRAG initialization failed: {(init_result or {}).get('error', 'unknown error')}"
                )

            # Use config defaults if not provided
            if output_dir is None:
                output_dir = self.config.parser_output_dir
            if parse_method is None:
                parse_method = self.config.parse_method
            if display_stats is None:
                display_stats = self.config.display_content_stats

            self.logger.info(f"Starting complete document processing: {file_path}")

            # Step 1: Parse document
            content_list, content_based_doc_id = await self.parse_document(
                file_path, output_dir, parse_method, display_stats, **kwargs
            )

            # Use provided doc_id or fall back to content-based doc_id
            if doc_id is None:
                doc_id = content_based_doc_id

            # Step 2: Separate text and multimodal content
            text_content, multimodal_items = separate_content(content_list)

            # LightRAG creates the initial doc_status entry during text insertion.
            # Pre-registering the same doc_id here makes LightRAG treat a fresh
            # document insert as a duplicate, so only create the record up front
            # for multimodal-only content that will not call ainsert().
            if not text_content.strip():
                await self._upsert_doc_status(
                    doc_id,
                    file_name,
                    status=DocStatus.HANDLING,
                    error_msg="",
                )

            # Step 2.5: Set content source for context extraction in multimodal processing
            if hasattr(self, "set_content_source_for_context") and multimodal_items:
                self.logger.info(
                    "Setting content source for context-aware multimodal processing..."
                )
                self.set_content_source_for_context(
                    content_list, self.config.content_format
                )

            # Step 3: Insert pure text content with all parameters
            stage = "text_insert"
            if text_content.strip():
                if callback_manager is not None:
                    callback_manager.dispatch(
                        "on_text_insert_start",
                        file_path=file_name,
                        text_length=len(text_content),
                        doc_id=doc_id,
                    )
                insert_start = time.time()
                await insert_text_content(
                    self.lightrag,
                    input=text_content,
                    file_paths=file_name,
                    split_by_character=split_by_character,
                    split_by_character_only=split_by_character_only,
                    ids=doc_id,
                )
                # Ensure LightRAG internal pipelines flush in-memory data to disk
                try:
                    await self.lightrag._insert_done()
                except Exception:
                    pass
                # Check whether LightRAG's pipeline marked the document as failed
                # before overwriting the status with HANDLING.
                ds = await self.lightrag.doc_status.get_by_id(doc_id)
                if ds and ds.get("status") == "failed":
                    self.logger.error(
                        "LightRAG pipeline failed for doc %s: %s",
                        doc_id[:16], ds.get("error_msg", "unknown error"),
                    )
                    raise RuntimeError(
                        f"文档处理失败（LightRAG entity extraction）: "
                        f"{ds.get('error_msg', 'unknown error')}"
                    )
                await self._upsert_doc_status(
                    doc_id,
                    file_name,
                    status=DocStatus.HANDLING,
                    error_msg="",
                )
                # Register chunk → doc source mappings for citation tracing
                # After text insertion, LightRAG populates chunks_list in doc_status
                try:
                    ds = await self.lightrag.doc_status.get_by_id(doc_id)
                    if ds and ds.get("chunks_list"):
                        self._register_chunk_sources(
                            doc_id,
                            file_path,  # use full path for file_path field
                            ds["chunks_list"],
                        )
                except Exception:
                    pass  # Non-critical

                if callback_manager is not None:
                    insert_duration = time.time() - insert_start
                    callback_manager.dispatch(
                        "on_text_insert_complete",
                        file_path=file_name,
                        duration_seconds=insert_duration,
                        doc_id=doc_id,
                    )
            else:
                # file_name was resolved before parsing so doc_status can be initialized early
                pass

            # Step 4: Process multimodal content (using specialized processors)
            stage = "multimodal"
            if multimodal_items:
                await self._process_multimodal_content(
                    multimodal_items, file_name, doc_id
                )
            else:
                # If no multimodal content, mark multimodal processing as complete
                # This ensures the document status properly reflects completion of all processing
                await self._mark_multimodal_processing_complete(doc_id)
                self.logger.debug(
                    f"No multimodal content found in document {doc_id}, "
                    "marked multimodal processing as complete",
                )

        except Exception as exc:
            if doc_id is not None:
                try:
                    await self._upsert_doc_status(
                        doc_id,
                        file_name,
                        status=DocStatus.FAILED,
                        error_msg=str(exc),
                    )
                except Exception as status_exc:
                    self.logger.debug(
                        f"Failed to persist doc_status error state for {doc_id}: {status_exc}"
                    )
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_document_error",
                    file_path=str(file_path),
                    doc_id=doc_id,
                    stage=stage,
                    error=exc,
                )
            raise

        self.logger.info(f"Document {file_path} processing complete!")
        if callback_manager is not None:
            duration = time.time() - doc_start_time
            callback_manager.dispatch(
                "on_document_complete",
                file_path=str(file_path),
                doc_id=doc_id,
                duration_seconds=duration,
            )

    async def process_document_complete_lightrag_api(
        self,
        file_path: str,
        output_dir: str = None,
        parse_method: str = None,
        display_stats: bool = None,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        doc_id: str | None = None,
        scheme_name: str | None = None,
        parser: str | None = None,
        **kwargs,
    ):
        """
        API exclusively for LightRAG calls: Complete document processing workflow

        Args:
            file_path: Path to the file to process
            output_dir: output directory (defaults to config.parser_output_dir)
            parse_method: Parse method (defaults to config.parse_method)
            display_stats: Whether to display content statistics (defaults to config.display_content_stats)
            split_by_character: Optional character to split the text by
            split_by_character_only: If True, split only by the specified character
            doc_id: Optional document ID, if not provided will be generated from content
            **kwargs: Additional parameters for parser (e.g., lang, device, start_page, end_page, formula, table, backend, source)
        """
        # Use full path or basename based on config
        file_name = self._get_file_reference(file_path)
        doc_pre_id = f"doc-pre-{file_name}"
        pipeline_status = None
        pipeline_status_lock = None
        current_doc_status = {}  # initialised here so the except block can always unpack it

        async def mark_initialization_failed(error_msg: str) -> None:
            """Persist init failures when LightRAG doc_status is already available."""
            lightrag = getattr(self, "lightrag", None)
            doc_status = getattr(lightrag, "doc_status", None)
            if doc_status is None:
                self.logger.error(
                    "LightRAG initialization failed before doc_status was available; "
                    f"unable to persist failed status for {file_path}"
                )
                return

            try:
                existing_status = await doc_status.get_by_id(doc_pre_id)
                failed_status = {
                    "status": DocStatus.FAILED,
                    "content": "",
                    "error_msg": error_msg,
                    "content_summary": "",
                    "multimodal_content": [],
                    "scheme_name": scheme_name,
                    "content_length": 0,
                    "created_at": "",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    "file_path": file_name,
                }
                if existing_status:
                    failed_status = {
                        **existing_status,
                        "status": DocStatus.FAILED,
                        "error_msg": error_msg,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    }
                await doc_status.upsert({doc_pre_id: failed_status})
                await doc_status.index_done_callback()
            except Exception as status_error:
                self.logger.error(
                    f"Failed to persist initialization failure status for {file_path}: "
                    f"{status_error}"
                )

        if parser:
            self.config.parser = parser

        try:
            # Ensure LightRAG is initialized before accessing its storages
            result = await self._ensure_lightrag_initialized()
            if not result or not result.get("success"):
                error_msg = (result or {}).get("error", "unknown error")
                self.logger.error(
                    f"LightRAG initialization failed: {error_msg}; "
                    f"skipping document processing for {file_path}"
                )
                await mark_initialization_failed(str(error_msg))
                return False

            # Use config defaults if not provided
            if output_dir is None:
                output_dir = self.config.parser_output_dir
            if parse_method is None:
                parse_method = self.config.parse_method
            if display_stats is None:
                display_stats = self.config.display_content_stats

            self.logger.info(f"Starting complete document processing: {file_path}")

            # Initialize doc status
            current_doc_status = await self.lightrag.doc_status.get_by_id(doc_pre_id)
            if not current_doc_status:
                await self.lightrag.doc_status.upsert(
                    {
                        doc_pre_id: {
                            "status": DocStatus.READY,
                            "content": "",
                            "error_msg": "",
                            "content_summary": "",
                            "multimodal_content": [],
                            "scheme_name": scheme_name,
                            "content_length": 0,
                            "created_at": "",
                            "updated_at": "",
                            "file_path": file_name,
                        }
                    }
                )
                current_doc_status = await self.lightrag.doc_status.get_by_id(
                    doc_pre_id
                )

            from lightrag.kg.shared_storage import (
                get_namespace_data,
                get_pipeline_status_lock,
            )

            pipeline_status = await get_namespace_data("pipeline_status")
            pipeline_status_lock = get_pipeline_status_lock()

            # Set processing status
            async with pipeline_status_lock:
                pipeline_status.update({"scan_disabled": True})
                pipeline_status["history_messages"].append("Now is not allowed to scan")

            await self.lightrag.doc_status.upsert(
                {
                    doc_pre_id: {
                        **current_doc_status,
                        "status": DocStatus.HANDLING,
                        "error_msg": "",
                    }
                }
            )

            content_list = []
            content_based_doc_id = ""

            try:
                # Step 1: Parse document
                content_list, content_based_doc_id = await self.parse_document(
                    file_path, output_dir, parse_method, display_stats, **kwargs
                )
            except MineruExecutionError as e:
                if isinstance(e.error_msg, list):
                    error_message = "\n".join(str(m) for m in e.error_msg)
                else:
                    error_message = str(e.error_msg)
                await self.lightrag.doc_status.upsert(
                    {
                        doc_pre_id: {
                            **current_doc_status,
                            "status": DocStatus.FAILED,
                            "error_msg": error_message,
                        }
                    }
                )
                self.logger.info(
                    f"Error processing document {file_path}: MineruExecutionError"
                )
                return False
            except Exception as e:
                await self.lightrag.doc_status.upsert(
                    {
                        doc_pre_id: {
                            **current_doc_status,
                            "status": DocStatus.FAILED,
                            "error_msg": str(e),
                        }
                    }
                )
                self.logger.info(f"Error processing document {file_path}: {str(e)}")
                return False

            # Use provided doc_id or fall back to content-based doc_id
            if doc_id is None:
                doc_id = content_based_doc_id

            await self._upsert_doc_status(
                doc_id,
                file_name,
                scheme_name=scheme_name,
                status=DocStatus.HANDLING,
                error_msg="",
            )

            # Step 2: Separate text and multimodal content
            text_content, multimodal_items = separate_content(content_list)

            # Step 2.5: Set content source for context extraction in multimodal processing
            if hasattr(self, "set_content_source_for_context") and multimodal_items:
                self.logger.info(
                    "Setting content source for context-aware multimodal processing..."
                )
                self.set_content_source_for_context(
                    content_list, self.config.content_format
                )

            # Step 3: Insert pure text content and multimodal content with all parameters
            if text_content.strip():
                await insert_text_content_with_multimodal_content(
                    self.lightrag,
                    input=text_content,
                    multimodal_content=multimodal_items,
                    file_paths=file_name,
                    split_by_character=split_by_character,
                    split_by_character_only=split_by_character_only,
                    ids=doc_id,
                    scheme_name=scheme_name,
                )

            self.logger.info(f"Document {file_path} processing completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error processing document {file_path}: {str(e)}")
            self.logger.debug("Exception details:", exc_info=True)

            # Update doc status to Failed
            await self.lightrag.doc_status.upsert(
                {
                    doc_pre_id: {
                        **current_doc_status,
                        "status": DocStatus.FAILED,
                        "error_msg": str(e),
                    }
                }
            )
            await self.lightrag.doc_status.index_done_callback()

            # Update pipeline status
            if pipeline_status_lock and pipeline_status:
                try:
                    async with pipeline_status_lock:
                        pipeline_status.update({"scan_disabled": False})
                        error_msg = (
                            f"RAGAnything processing failed for {file_name}: {str(e)}"
                        )
                        pipeline_status["latest_message"] = error_msg
                        pipeline_status["history_messages"].append(error_msg)
                        pipeline_status["history_messages"].append(
                            "Now is allowed to scan"
                        )
                except Exception as pipeline_update_error:
                    self.logger.error(
                        f"Failed to update pipeline status: {pipeline_update_error}"
                    )

            return False

        finally:
            if pipeline_status_lock is not None and pipeline_status is not None:
                try:
                    async with pipeline_status_lock:
                        pipeline_status.update({"scan_disabled": False})
                        pipeline_status["latest_message"] = (
                            f"RAGAnything processing completed for {file_name}"
                        )
                        pipeline_status["history_messages"].append(
                            f"RAGAnything processing completed for {file_name}"
                        )
                        pipeline_status["history_messages"].append(
                            "Now is allowed to scan"
                        )
                except Exception as _finally_err:
                    self.logger.error(
                        f"Failed to update pipeline status in finally block: {_finally_err}"
                    )
    async def insert_content_list(
        self,
        content_list: List[Dict[str, Any]],
        file_path: str = "unknown_document",
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        doc_id: str | None = None,
        display_stats: bool = None,
    ):
        """
        Insert content list directly without document parsing

        Args:
            content_list: Pre-parsed content list containing text and multimodal items.
                         Each item should be a dictionary with the following structure:
                         - Text: {"type": "text", "text": "content", "page_idx": 0}
                         - Image: {"type": "image", "img_path": "/absolute/path/to/image.jpg",
                                  "image_caption": ["caption"], "image_footnote": ["note"], "page_idx": 1}
                         - Table: {"type": "table", "table_body": "markdown table",
                                  "table_caption": ["caption"], "table_footnote": ["note"], "page_idx": 2}
                         - Equation: {"type": "equation", "latex": "LaTeX formula",
                                     "text": "description", "page_idx": 3}
                         - Generic: {"type": "custom_type", "content": "any content", "page_idx": 4}
            file_path: Reference file path/name for citation (defaults to "unknown_document")
            split_by_character: Optional character to split the text by
            split_by_character_only: If True, split only by the specified character
            doc_id: Optional document ID, if not provided will be generated from content
            display_stats: Whether to display content statistics (defaults to config.display_content_stats)

        Note:
            - img_path must be an absolute path to the image file
            - page_idx represents the page number where the content appears (0-based indexing)
            - Items are processed in the order they appear in the list
        """
        callback_manager = getattr(self, "callback_manager", None)
        doc_start_time = time.time()

        # Ensure LightRAG is initialized
        init_result = await self._ensure_lightrag_initialized()
        if not init_result or not init_result.get("success"):
            raise RuntimeError(
                f"LightRAG initialization failed: {(init_result or {}).get('error', 'unknown error')}"
            )

        # Use config defaults if not provided
        if display_stats is None:
            display_stats = self.config.display_content_stats

        self.logger.info(
            f"Starting direct content list insertion for: {file_path} ({len(content_list)} items)"
        )

        # Generate doc_id based on content if not provided
        if doc_id is None:
            doc_id = self._generate_content_based_doc_id(content_list)

        file_ref = self._get_file_reference(file_path)

        # Display content statistics if requested
        if display_stats:
            self.logger.info("\nContent Information:")
            self.logger.info(f"* Total blocks in content_list: {len(content_list)}")

            # Count elements by type
            block_types: Dict[str, int] = {}
            for block in content_list:
                if isinstance(block, dict):
                    block_type = block.get("type", "unknown")
                    if isinstance(block_type, str):
                        block_types[block_type] = block_types.get(block_type, 0) + 1

            self.logger.info("* Content block types:")
            for block_type, count in block_types.items():
                self.logger.info(f"  - {block_type}: {count}")

        # Step 1: Separate text and multimodal content
        text_content, multimodal_items = separate_content(content_list)

        # LightRAG creates the initial doc_status entry during text insertion.
        # Pre-registering the same doc_id here makes LightRAG treat a fresh
        # content-list insert as a duplicate, so only create the record up front
        # for multimodal-only content that will not call ainsert().
        if not text_content.strip():
            await self._upsert_doc_status(
                doc_id,
                file_ref,
                status=DocStatus.HANDLING,
                error_msg="",
            )

        # Step 1.5: Set content source for context extraction in multimodal processing
        if hasattr(self, "set_content_source_for_context") and multimodal_items:
            self.logger.info(
                "Setting content source for context-aware multimodal processing..."
            )
            self.set_content_source_for_context(
                content_list, self.config.content_format
            )

        # Step 2: Insert pure text content with all parameters
        if text_content.strip():
            if callback_manager is not None:
                callback_manager.dispatch(
                    "on_text_insert_start",
                    file_path=file_ref,
                    text_length=len(text_content),
                    doc_id=doc_id,
                )
            insert_start = time.time()
            await insert_text_content(
                self.lightrag,
                input=text_content,
                file_paths=file_ref,
                split_by_character=split_by_character,
                split_by_character_only=split_by_character_only,
                ids=doc_id,
            )
            # Persist LightRAG storages to disk (text_chunks, entities, etc.)
            try:
                await self.lightrag._insert_done()
            except Exception:
                pass
            # Check whether LightRAG's pipeline marked the document as failed
            # before overwriting the status with HANDLING.
            ds = await self.lightrag.doc_status.get_by_id(doc_id)
            if ds and ds.get("status") == "failed":
                self.logger.error(
                    "LightRAG pipeline failed for doc %s: %s",
                    doc_id[:16], ds.get("error_msg", "unknown error"),
                )
                raise RuntimeError(
                    f"文档处理失败（LightRAG entity extraction）: "
                    f"{ds.get('error_msg', 'unknown error')}"
                )
            await self._upsert_doc_status(
                doc_id,
                file_ref,
                status=DocStatus.HANDLING,
                error_msg="",
            )
            if callback_manager is not None:
                insert_duration = time.time() - insert_start
                callback_manager.dispatch(
                    "on_text_insert_complete",
                    file_path=file_ref,
                    duration_seconds=insert_duration,
                    doc_id=doc_id,
                )
        else:
            # file_ref was resolved before insertion so doc_status can be initialized early
            pass

        # Step 3: Process multimodal content in background (non-blocking)
        # VLM/LLM calls for image captions & table analysis can take minutes;
        # run them as a background task so text chunks are searchable immediately.
        if multimodal_items:
            import asyncio as _asyncio
            try:
                loop = _asyncio.get_running_loop()
                bg_task = loop.create_task(
                    self._process_multimodal_content_background(
                        multimodal_items, file_ref, doc_id
                    )
                )
                register_background_task(bg_task)
                self.logger.info(
                    f"Scheduled {len(multimodal_items)} multimodal items for background processing"
                )
                # Mark document as processed immediately — text is ready for search
                await self._upsert_doc_status(
                    doc_id, file_ref,
                    status=DocStatus.PROCESSED,
                    error_msg="",
                )
            except RuntimeError:
                # No event loop available — fall back to sync
                await self._process_multimodal_content(
                    multimodal_items, file_ref, doc_id
                )
                await self._mark_multimodal_processing_complete(doc_id)
        else:
            await self._mark_multimodal_processing_complete(doc_id)
            self.logger.debug(
                f"No multimodal content found in document {doc_id}, marked multimodal processing as complete"
            )

        self.logger.info(f"Content list insertion complete for: {file_path}")

        # Trigger BM25 index update for RRF hybrid search
        self._schedule_bm25_index_update()

        if callback_manager is not None:
            duration = time.time() - doc_start_time
            callback_manager.dispatch(
                "on_document_complete",
                file_path=file_path,
                doc_id=doc_id,
                duration_seconds=duration,
            )
