"""
Document processing functionality for RAGAnything

Contains methods for parsing documents and processing multimodal content
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from raganything.base import DocStatus
from raganything.document_context import document_context
from raganything.parse_options import (
    PARSER_CACHE_KWARGS as _PARSER_CACHE_KWARGS,  # noqa: F401
)
from raganything.parser import (
    HTML_FILE_EXTENSIONS,
    MineruExecutionError,
    MineruParser,
    get_parser,
    html_requires_docling_error,
)
from raganything.utils import (
    get_processor_for_type,
    insert_text_content,
    insert_text_content_with_multimodal_content,
    merge_continued_tables,
    separate_content_with_page_map,
)

AUDIO_FILE_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".opus"}
)
VIDEO_FILE_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".webm", ".avi", ".mkv", ".flv", ".wmv", ".m4v"}
)


def _is_lightrag_token_chunker(func) -> bool:
    try:
        from lightrag.operate import chunking_by_token_size
    except ImportError:  # pragma: no cover - lightrag always provides it
        return False
    return func is chunking_by_token_size


from raganything.processor_cache import ProcessorCacheMixin
from raganything.processor_deletion import DocumentDeletionMixin
from raganything.processor_multimodal import MultimodalIngestMixin
from raganything.processor_status import DocumentStatusSyncMixin


class ProcessorMixin(
    ProcessorCacheMixin,
    DocumentStatusSyncMixin,
    MultimodalIngestMixin,
    DocumentDeletionMixin,
):
    """ProcessorMixin class containing document processing functionality for RAGAnything"""

    async def parse_document(
        self,
        file_path: str,
        output_dir: str = None,
        parse_method: str = None,
        display_stats: bool = None,
        **kwargs,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Parse document with caching support

        Args:
            file_path: Path to the file to parse
            output_dir: Output directory (defaults to config.parser_output_dir)
            parse_method: Parse method (defaults to config.parse_method)
            display_stats: Whether to display content statistics (defaults to config.display_content_stats)
            **kwargs: Additional parameters for parser (e.g., lang, device,
                start_page, end_page, formula, table, backend, source,
                include_layout_blocks)

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

        # Populate parser/backend options from config if not explicitly overridden
        if self.config.parser == "mineru":
            if "backend" not in kwargs and getattr(self.config, "mineru_backend", None):
                kwargs["backend"] = self.config.mineru_backend
            if "vlm_url" not in kwargs and getattr(self.config, "mineru_vlm_url", None):
                kwargs["vlm_url"] = self.config.mineru_vlm_url
            if "source" not in kwargs and getattr(self.config, "mineru_source", None):
                kwargs["source"] = self.config.mineru_source

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
            self._record_parsed_output_location(doc_id, file_path, output_dir)
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
            elif ext in AUDIO_FILE_EXTENSIONS or ext in VIDEO_FILE_EXTENSIONS:
                # Media files need no document parser: they become a single
                # audio/video content item and are handled by the modal
                # processors (faster-whisper / SceneDetect+VLM) downstream.
                # media_sha256 ties the content-based doc_id to the file
                # bytes, so replacing the file re-ingests it as new content.
                kind = "audio" if ext in AUDIO_FILE_EXTENSIONS else "video"
                self.logger.info(
                    f"Detected {kind} file; building {kind} content item "
                    "(no document parser involved)..."
                )
                content_list = [
                    {
                        "type": kind,
                        f"{kind}_path": str(file_path.absolute()),
                        f"{kind}_caption": [],
                        "page_idx": 0,
                        "media_sha256": self._file_content_fingerprint(file_path),
                    }
                ]
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
            elif ext in HTML_FILE_EXTENSIONS:
                # Only parsers with a native HTML entry point (Docling) take
                # HTML; never fall back to parse_office_doc, whose LibreOffice
                # conversion fetches remote URLs referenced by the page.
                if not hasattr(doc_parser, "parse_html"):
                    raise html_requires_docling_error(file_path)
                self.logger.info("Detected HTML document, using parser for HTML...")
                content_list = await asyncio.to_thread(
                    doc_parser.parse_html,
                    html_path=file_path,
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
            ]:
                self.logger.info(
                    "Detected Office document, using parser for Office documents..."
                )
                content_list = await asyncio.to_thread(
                    doc_parser.parse_office_doc,
                    doc_path=file_path,
                    output_dir=output_dir,
                    **kwargs,
                )
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
                f"Error during parsing with {self.config.parser} parser: {e!s}"
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

        if getattr(self.config, "merge_continued_tables", False):
            content_list = merge_continued_tables(content_list)

        # Generate doc_id based on content
        doc_id = self._generate_content_based_doc_id(content_list)
        self._record_parsed_output_location(doc_id, file_path, output_dir)

        # Store result in cache
        await self._store_cached_result(
            cache_key,
            content_list,
            doc_id,
            file_path,
            parse_method,
            output_dir=output_dir,
            **kwargs,
        )

        # Display content statistics if requested
        if display_stats:
            self.logger.info("\nContent Information:")
            self.logger.info(f"* Total blocks in content_list: {len(content_list)}")

            # Count elements by type
            block_types: dict[str, int] = {}
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

    @document_context
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
        force_multimodal_reprocess: bool = False,
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
            force_multimodal_reprocess: If True, re-run multimodal (image/table/equation)
                processing even if this document was already marked as fully
                processed. Defaults to False (original behavior: already-processed
                documents are skipped). This is useful after switching to a new
                graph/vector storage backend, since a fresh backend will not yet
                contain the multimodal entities/relations that were written to the
                previous one (see https://github.com/HKUDS/RAG-Anything/issues/154).
                Text content is unaffected by this flag.
            **kwargs: Additional parameters for parser (e.g., lang, device,
                start_page, end_page, formula, table, backend, source,
                include_layout_blocks)
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
            self._record_parsed_output_location(
                doc_id,
                file_path,
                output_dir,
                fallback_doc_id=content_based_doc_id,
            )

            # Step 2: Separate text and multimodal content
            text_content, multimodal_items, page_intervals = (
                separate_content_with_page_map(content_list)
            )

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
                await self._drop_placeholder_doc_status(doc_id)
                track_id = await insert_text_content(
                    self.lightrag,
                    input=text_content,
                    file_paths=file_name,
                    split_by_character=split_by_character,
                    split_by_character_only=split_by_character_only,
                    ids=doc_id,
                )
                await self._wait_for_text_processing(
                    doc_id, split_by_character, split_by_character_only
                )
                await self._annotate_text_chunk_pages(
                    doc_id,
                    track_id,
                    text_content,
                    page_intervals,
                    split_by_character,
                    split_by_character_only,
                )
                await self._upsert_doc_status(
                    doc_id,
                    file_name,
                    status=DocStatus.HANDLING,
                    error_msg="",
                )
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
                    multimodal_items,
                    file_name,
                    doc_id,
                    force_reprocess=force_multimodal_reprocess,
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

    @document_context
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
            **kwargs: Additional parameters for parser (e.g., lang, device,
                start_page, end_page, formula, table, backend, source,
                include_layout_blocks)
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
                    "error_msg": error_msg,
                    "content_summary": "",
                    "content_length": 0,
                    # A real timestamp, never "": storage backends that map
                    # created_at as a date reject an empty string, and the
                    # rejected upsert is silently dropped (#328).
                    "created_at": self._current_doc_status_timestamp(),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    "file_path": file_name,
                    "metadata": (
                        {"scheme_name": scheme_name} if scheme_name is not None else {}
                    ),
                }
                if existing_status:
                    failed_status = {
                        **existing_status,
                        "status": DocStatus.FAILED,
                        "error_msg": error_msg,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    }
                    failed_status.pop("content", None)
                    failed_status.pop("multimodal_content", None)
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
                            "error_msg": "",
                            "content_summary": "",
                            "content_length": 0,
                            # A real timestamp, never "": storage backends
                            # that map created_at as a date reject an empty
                            # string, and the rejected upsert is silently
                            # dropped (#328).
                            "created_at": self._current_doc_status_timestamp(),
                            "updated_at": self._current_doc_status_timestamp(),
                            "file_path": file_name,
                            "metadata": (
                                {"scheme_name": scheme_name}
                                if scheme_name is not None
                                else {}
                            ),
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

            handling_status = {
                **current_doc_status,
                "status": DocStatus.HANDLING,
                "error_msg": "",
            }
            handling_status.pop("content", None)
            handling_status.pop("multimodal_content", None)
            await self.lightrag.doc_status.upsert(
                {
                    doc_pre_id: handling_status,
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
                # Persist the end of MinerU's output and remediation advice for
                # recognized MinerU failures in the doc status, not just in the
                # logs.
                if getattr(e, "output", None):
                    error_message = f"{error_message}\n\n{e.output}"
                if getattr(e, "hint", None):
                    error_message = f"{error_message}\n\n{e.hint}"
                failed_status = {
                    **current_doc_status,
                    "status": DocStatus.FAILED,
                    "error_msg": error_message,
                }
                failed_status.pop("content", None)
                failed_status.pop("multimodal_content", None)
                await self.lightrag.doc_status.upsert(
                    {
                        doc_pre_id: failed_status,
                    }
                )
                self.logger.info(
                    f"Error processing document {file_path}: MineruExecutionError"
                )
                return False
            except Exception as e:
                failed_status = {
                    **current_doc_status,
                    "status": DocStatus.FAILED,
                    "error_msg": str(e),
                }
                failed_status.pop("content", None)
                failed_status.pop("multimodal_content", None)
                await self.lightrag.doc_status.upsert(
                    {
                        doc_pre_id: failed_status,
                    }
                )
                self.logger.info(f"Error processing document {file_path}: {e!s}")
                return False

            # Use provided doc_id or fall back to content-based doc_id
            if doc_id is None:
                doc_id = content_based_doc_id
            self._record_parsed_output_location(
                doc_id,
                file_path,
                output_dir,
                fallback_doc_id=content_based_doc_id,
            )

            # Step 2: Separate text and multimodal content
            text_content, multimodal_items, page_intervals = (
                separate_content_with_page_map(content_list)
            )

            # LightRAG creates the initial doc_status entry during text
            # insertion. Pre-registering the same doc_id here makes LightRAG
            # treat a fresh document insert as a duplicate and skip indexing
            # entirely, so only create the record up front for multimodal-only
            # content that will not reach ainsert().
            if not text_content.strip():
                await self._upsert_doc_status(
                    doc_id,
                    file_name,
                    scheme_name=scheme_name,
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

            # Step 3: Insert pure text content and multimodal content with all parameters
            if text_content.strip():
                await self._drop_placeholder_doc_status(doc_id)
                track_id = await insert_text_content_with_multimodal_content(
                    self.lightrag,
                    input=text_content,
                    multimodal_content=multimodal_items,
                    file_paths=file_name,
                    split_by_character=split_by_character,
                    split_by_character_only=split_by_character_only,
                    ids=doc_id,
                    scheme_name=scheme_name,
                )
                await self._annotate_text_chunk_pages(
                    doc_id,
                    track_id,
                    text_content,
                    page_intervals,
                    split_by_character,
                    split_by_character_only,
                )

            self.logger.info(f"Document {file_path} processing completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error processing document {file_path}: {e!s}")
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
                            f"RAGAnything processing failed for {file_name}: {e!s}"
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

    @document_context
    async def insert_content_list(
        self,
        content_list: list[dict[str, Any]],
        file_path: str = "unknown_document",
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        doc_id: str | None = None,
        display_stats: bool = None,
        force_multimodal_reprocess: bool = False,
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
            force_multimodal_reprocess: If True, re-run multimodal (image/table/equation)
                processing even if this document was already marked as fully
                processed. Defaults to False (original behavior: already-processed
                documents are skipped). This is useful after switching to a new
                graph/vector storage backend, since a fresh backend will not yet
                contain the multimodal entities/relations that were written to the
                previous one (see https://github.com/HKUDS/RAG-Anything/issues/154).
                Text content is unaffected by this flag.

        Note:
            - img_path must be an absolute path to the image file
            - page_idx represents the page number where the content appears (0-based indexing)
            - Items are processed in the order they appear in the list
        """
        if len(content_list) == 0:
            raise ValueError("content_list cannot be empty")

        if getattr(self.config, "merge_continued_tables", False):
            content_list = merge_continued_tables(content_list)

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

        if file_path and file_path != "unknown_document":
            self._record_parsed_output_location(
                doc_id,
                file_path,
                getattr(getattr(self, "config", None), "parser_output_dir", None),
            )

        file_ref = self._get_file_reference(file_path)

        # Display content statistics if requested
        if display_stats:
            self.logger.info("\nContent Information:")
            self.logger.info(f"* Total blocks in content_list: {len(content_list)}")

            # Count elements by type
            block_types: dict[str, int] = {}
            for block in content_list:
                if isinstance(block, dict):
                    block_type = block.get("type", "unknown")
                    if isinstance(block_type, str):
                        block_types[block_type] = block_types.get(block_type, 0) + 1

            self.logger.info("* Content block types:")
            for block_type, count in block_types.items():
                self.logger.info(f"  - {block_type}: {count}")

        # Step 1: Separate text and multimodal content
        text_content, multimodal_items, page_intervals = separate_content_with_page_map(
            content_list
        )

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
            await self._drop_placeholder_doc_status(doc_id)
            track_id = await insert_text_content(
                self.lightrag,
                input=text_content,
                file_paths=file_ref,
                split_by_character=split_by_character,
                split_by_character_only=split_by_character_only,
                ids=doc_id,
            )
            await self._wait_for_text_processing(
                doc_id, split_by_character, split_by_character_only
            )
            await self._annotate_text_chunk_pages(
                doc_id,
                track_id,
                text_content,
                page_intervals,
                split_by_character,
                split_by_character_only,
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

        # Step 3: Process multimodal content (using specialized processors)
        if multimodal_items:
            await self._process_multimodal_content(
                multimodal_items,
                file_ref,
                doc_id,
                force_reprocess=force_multimodal_reprocess,
            )
        else:
            # If no multimodal content, mark multimodal processing as complete
            # This ensures the document status properly reflects completion of all processing
            await self._mark_multimodal_processing_complete(doc_id)
            self.logger.debug(
                f"No multimodal content found in document {doc_id}, marked multimodal processing as complete"
            )

        self.logger.info(f"Content list insertion complete for: {file_path}")
        if callback_manager is not None:
            duration = time.time() - doc_start_time
            callback_manager.dispatch(
                "on_document_complete",
                file_path=file_path,
                doc_id=doc_id,
                duration_seconds=duration,
            )
        return doc_id

    @document_context
    async def process_preprocessed_output(
        self,
        output_dir: str | Path,
        file_path: str | Path | None = None,
        file_stem: str | None = None,
        parse_method: str = "auto",
        display_stats: bool | None = None,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        doc_id: str | None = None,
        force_multimodal_reprocess: bool = False,
        include_layout_blocks: bool = False,
        **kwargs,
    ) -> tuple[list[dict[str, Any]], str]:
        """Ingest already-parsed MinerU output files from an output directory into LightRAG.

        Bypasses document parsing when documents have already been processed
        by MinerU (e.g. offline on a GPU server or batch preprocessing pipeline).

        Args:
            output_dir: Path to the directory containing MinerU output (or subdirectories).
            file_path: Original file path or citation reference name.
            file_stem: Document name without extension. Auto-detected if None.
            parse_method: Parse method subdirectory ("auto", "ocr", "txt").
            display_stats: Whether to log content stats.
            split_by_character: Optional character to split text by.
            split_by_character_only: If True, split only by specified character.
            doc_id: Optional document ID. Generated from content if None.
            force_multimodal_reprocess: If True, re-process multimodal items.
            include_layout_blocks: If True, keep v2 headers/footers.
            **kwargs: Extra parameters passed to insert_content_list.

        Returns:
            Tuple of (content_list, doc_id).
        """
        out_path = Path(output_dir)
        if not out_path.exists():
            raise FileNotFoundError(f"Output directory does not exist: {out_path}")

        if not out_path.is_dir():
            raise NotADirectoryError(f"Not an output directory: {out_path}")
        resolved_file_stem = file_stem or (Path(file_path).stem if file_path else None)
        # Accept a bundle root, a document directory, or its backend directory.
        directories = [out_path, *sorted(p for p in out_path.iterdir() if p.is_dir())]
        directories += [
            p
            for directory in directories[1:]
            for p in sorted(directory.iterdir())
            if p.is_dir()
        ]
        suffixes = ("_content_list_v2.json", "_content_list.json")
        named_stems = {
            path.name.removesuffix(suffix)
            for directory in directories
            for suffix in suffixes
            for path in directory.glob(f"*{suffix}")
        }
        if resolved_file_stem is None:
            if len(named_stems) > 1:
                raise ValueError(
                    "Multiple documents found; specify file_stem or use process_preprocessed_directory"
                )
            resolved_file_stem = next(iter(named_stems), out_path.name)
        names = [f"{resolved_file_stem}{suffix}" for suffix in suffixes]
        exact_dirs = [
            d for d in directories if any((d / name).is_file() for name in names)
        ]
        bundle_dirs = exact_dirs or [
            d
            for d in directories
            if any(
                (d / name).is_file()
                for name in ("content_list_v2.json", "content_list.json")
            )
        ]
        preferred = [d for d in bundle_dirs if d.name == parse_method]
        bundle_dirs = preferred or bundle_dirs
        if len(bundle_dirs) > 1:
            raise ValueError(
                "Multiple MinerU bundles found; pass the specific backend output directory"
            )
        if not bundle_dirs:
            raise FileNotFoundError(
                f"No MinerU content list found in '{output_dir}' for stem '{resolved_file_stem}'"
            )
        read_dir = bundle_dirs[0]
        resolved_file_path = (
            str(file_path) if file_path is not None else f"{resolved_file_stem}.pdf"
        )
        # This API always reads MinerU output, regardless of the configured parser.
        doc_parser = get_parser("mineru")

        content_list, _md_content = doc_parser._read_output_files(
            read_dir,
            resolved_file_stem,
            method=parse_method,
            include_layout_blocks=include_layout_blocks,
        )
        if not content_list:
            raise FileNotFoundError(
                f"No MinerU content list found in '{output_dir}' for stem '{resolved_file_stem}'"
            )

        if doc_id is None:
            doc_id = self._generate_content_based_doc_id(content_list)

        # Imported files remain caller-owned; deleting the index must not remove them.

        await self.insert_content_list(
            content_list=content_list,
            file_path=resolved_file_path,
            split_by_character=split_by_character,
            split_by_character_only=split_by_character_only,
            doc_id=doc_id,
            display_stats=display_stats,
            force_multimodal_reprocess=force_multimodal_reprocess,
            **kwargs,
        )
        return content_list, doc_id

    async def process_preprocessed_directory(
        self,
        base_dir: str | Path,
        parse_method: str = "auto",
        display_stats: bool | None = None,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        force_multimodal_reprocess: bool = False,
        include_layout_blocks: bool = False,
        concurrency: int = 1,
        continue_on_error: bool = False,
        **kwargs,
    ) -> list[tuple[str, tuple[list[dict[str, Any]], str]]]:
        """Batch-import all preprocessed MinerU document folders from a directory.

        Iterates over each subdirectory in base_dir and ingests its preprocessed output
        with bounded concurrency and optional error tolerance.

        Args:
            base_dir: Directory containing per-document output subdirectories.
            parse_method: MinerU parse method subdirectory ("auto", "ocr", "txt").
            display_stats: Whether to log content stats.
            split_by_character: Optional character to split text by.
            split_by_character_only: If True, split only by specified character.
            force_multimodal_reprocess: If True, re-process multimodal items.
            include_layout_blocks: If True, keep v2 headers/footers.
            concurrency: Number of concurrent document ingestion tasks (default: 1).
            continue_on_error: If True, log errors and continue batch on individual failures.
            **kwargs: Extra parameters passed to process_preprocessed_output.

        Returns:
            List of (folder_name, (content_list, doc_id)) tuples for successfully ingested docs.
        """
        base_path = Path(base_dir)
        if not base_path.is_dir():
            raise NotADirectoryError(f"Directory not found: {base_dir}")

        doc_dirs = []
        for item in sorted(base_path.iterdir()):
            if item.is_dir() and (
                any(item.glob("*content_list*.json"))
                or any(item.glob("*/*content_list*.json"))
            ):
                doc_dirs.append(item)

        if not doc_dirs and (
            any(base_path.glob("*content_list*.json"))
            or any(base_path.glob("*/*content_list*.json"))
        ):
            doc_dirs.append(base_path)

        if not doc_dirs:
            return []

        results: list[tuple[str, tuple[list[dict[str, Any]], str]]] = []
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _process_one(doc_dir: Path):
            async with semaphore:
                self.logger.info(f"Ingesting preprocessed directory: {doc_dir.name}")
                try:
                    res = await self.process_preprocessed_output(
                        output_dir=doc_dir,
                        parse_method=parse_method,
                        display_stats=display_stats,
                        split_by_character=split_by_character,
                        split_by_character_only=split_by_character_only,
                        force_multimodal_reprocess=force_multimodal_reprocess,
                        include_layout_blocks=include_layout_blocks,
                        **kwargs,
                    )
                    return doc_dir.name, res, None
                except Exception as exc:
                    self.logger.error(
                        f"Failed ingesting preprocessed directory {doc_dir.name}: {exc}"
                    )
                    if not continue_on_error:
                        raise
                    return doc_dir.name, None, exc

        if concurrency > 1 and len(doc_dirs) > 1:
            tasks = [_process_one(d) for d in doc_dirs]
            batch_outcomes = await asyncio.gather(*tasks, return_exceptions=False)
            for folder_name, res, _err in batch_outcomes:
                if res is not None:
                    results.append((folder_name, res))
        else:
            for doc_dir in doc_dirs:
                folder_name, res, _err = await _process_one(doc_dir)
                if res is not None:
                    results.append((folder_name, res))

        return results

    async def _process_multimodal_content_batch_type_aware(
        self, multimodal_items: list[dict[str, Any]], file_path: str, doc_id: str
    ):
        """Type-aware batch processing that selects correct processors based on content type."""
        if not multimodal_items:
            self.logger.debug("No multimodal content to process")
            return

        try:
            existing_doc_status = await self.lightrag.doc_status.get_by_id(doc_id)
            existing_chunks_count = (
                existing_doc_status.get("chunks_count", 0) if existing_doc_status else 0
            )
        except Exception:
            existing_chunks_count = 0

        modal_limit = None
        config = getattr(self, "config", None)
        if config is not None:
            modal_limit = getattr(config, "max_parallel_modal_items", None)
        if modal_limit is None:
            modal_limit = getattr(self.lightrag, "max_parallel_insert", 2)
        try:
            modal_limit = int(modal_limit)
        except (TypeError, ValueError):
            modal_limit = 2
        modal_limit = max(modal_limit, 1)
        semaphore = asyncio.Semaphore(modal_limit)

        total_items = len(multimodal_items)
        completed_count = 0
        progress_lock = asyncio.Lock()

        self.logger.info(f"Starting to process {total_items} multimodal content items")

        async def process_single_item_with_correct_processor(
            item: dict[str, Any], index: int, file_path: str
        ):
            nonlocal completed_count
            async with semaphore:
                try:
                    content_type = item.get("type", "unknown")
                    processor = get_processor_for_type(
                        self.modal_processors, content_type
                    )

                    if not processor:
                        self.logger.warning(
                            f"No processor found for type: {content_type}"
                        )
                        return None

                    item_info = {
                        "page_idx": item.get("page_idx", 0),
                        "index": item.get("_content_list_index", index),
                        "type": content_type,
                    }

                    sections = await processor.generate_chunk_sections(
                        modal_content=item,
                        content_type=content_type,
                        item_info=item_info,
                        entity_name=None,
                    )

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

                    section_results = []
                    for section in sections:
                        window_meta = section.get("window_meta")
                        section_item = (
                            {**item, "_window_meta": window_meta}
                            if window_meta
                            else item
                        )
                        section_results.append(
                            {
                                "index": index,
                                "content_type": content_type,
                                "description": section["description"],
                                "entity_info": section["entity_info"],
                                "original_item": section_item,
                                "item_info": item_info,
                                "processor": processor,
                                "file_path": file_path,
                            }
                        )
                    return section_results

                except Exception as e:
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

        tasks = [
            asyncio.create_task(
                process_single_item_with_correct_processor(item, i, file_path)
            )
            for i, item in enumerate(multimodal_items)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        multimodal_data_list = []
        running_offset = 0
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Task failed: {result}")
                continue
            if not result:
                continue
            for data in result:
                data["chunk_order_index"] = existing_chunks_count + running_offset
                running_offset += 1
                multimodal_data_list.append(data)

        if not multimodal_data_list:
            self.logger.warning("No valid multimodal descriptions generated")
            return

        self.logger.info(
            f"Generated descriptions for {len(multimodal_data_list)}/{len(multimodal_items)} multimodal items using correct processors"
        )

        lightrag_chunks = self._convert_to_lightrag_chunks_type_aware(
            multimodal_data_list, file_path, doc_id
        )

        await self._store_chunks_to_lightrag_storage_type_aware(lightrag_chunks)

        await self._store_multimodal_main_entities(
            multimodal_data_list, lightrag_chunks, file_path, doc_id
        )

        chunk_ids = list(lightrag_chunks.keys())

        kg_mode = "legacy"
        if config is not None:
            kg_mode = (
                getattr(config, "multimodal_kg_extraction_mode", "legacy") or "legacy"
            )
        kg_mode = str(kg_mode).strip().lower()
        if kg_mode not in {"legacy", "packed", "per_item", "skip"}:
            self.logger.warning(
                f"Unknown multimodal_kg_extraction_mode={kg_mode!r}; using legacy"
            )
            kg_mode = "legacy"

        if kg_mode == "skip":
            self.logger.info(
                "Skipping multimodal entity extraction/merge "
                f"(multimodal_kg_extraction_mode=skip); "
                f"kept {len(chunk_ids)} retrieval chunks and main entities"
            )
        else:
            extraction_chunks = self._build_multimodal_extraction_chunks(
                multimodal_data_list, lightrag_chunks, mode=kg_mode
            )
            if kg_mode == "packed":
                await self._store_chunks_to_lightrag_storage_type_aware(
                    extraction_chunks
                )
                chunk_ids.extend(extraction_chunks)
                await self._update_doc_status_with_chunks_type_aware(doc_id, chunk_ids)
            self.logger.info(
                f"Multimodal KG extraction mode={kg_mode}: "
                f"{len(multimodal_data_list)} items -> "
                f"{len(extraction_chunks)} extraction chunk(s)"
            )
            chunk_results = (
                await self._batch_extract_entities_lightrag_style_type_aware(
                    extraction_chunks
                )
            )

            if kg_mode in {"legacy", "per_item"}:
                enhanced_chunk_results = (
                    await self._batch_add_belongs_to_relations_type_aware(
                        chunk_results, multimodal_data_list
                    )
                )
            else:
                enhanced_chunk_results = chunk_results
                self.logger.debug(
                    "Skipping belongs_to enrichment in packed KG extraction mode"
                )

            await self._batch_merge_lightrag_style_type_aware(
                enhanced_chunk_results, file_path, doc_id
            )

        if kg_mode != "packed":
            await self._update_doc_status_with_chunks_type_aware(doc_id, chunk_ids)

    async def _store_multimodal_entities_to_full_entities(
        self, entities_to_store: dict[str, Any], doc_id: str
    ):
        """Store multimodal main entities to full_entities storage."""
        try:
            current_doc_entities = await self.lightrag.full_entities.get_by_id(doc_id)

            if current_doc_entities is None:
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
