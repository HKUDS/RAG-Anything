"""
Batch processing functionality for RAGAnything

Contains methods for processing multiple documents in batch mode
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING
import time

from .batch_parser import BatchParser, BatchProcessingResult

if TYPE_CHECKING:
    from .config import RAGAnythingConfig


class BatchMixin:
    """BatchMixin class containing batch processing functionality for RAGAnything"""

    # Type hints for mixin attributes (will be available when mixed into RAGAnything)
    config: "RAGAnythingConfig"
    logger: logging.Logger

    # Type hints for methods that will be available from other mixins
    async def _ensure_lightrag_initialized(self) -> None: ...
    async def process_document_complete(self, file_path: str, **kwargs) -> None: ...

    # ==========================================
    # ORIGINAL BATCH PROCESSING METHOD (RESTORED)
    # ==========================================

    # ------------------------------------------------------------------
    # Incremental scan helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _file_md5(file_path: Path, block_size: int = 65536) -> str:
        """Return the hex MD5 digest of *file_path*."""
        h = hashlib.md5()
        with open(file_path, "rb") as fh:
            for block in iter(lambda: fh.read(block_size), b""):
                h.update(block)
        return h.hexdigest()

    def _manifest_path(self, folder_path: Path) -> Path:
        """Return the path to the incremental-scan manifest for *folder_path*.

        The manifest is stored inside the RAG working directory so it is not
        mixed in with the source documents.
        """
        working_dir = Path(self.config.working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)
        # Use a deterministic name derived from the folder path so that
        # multiple source folders can each have their own manifest.
        folder_hash = hashlib.md5(str(folder_path.resolve()).encode()).hexdigest()[:8]
        return working_dir / f".folder_manifest_{folder_hash}.json"

    def _load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_manifest(self, manifest_path: Path, manifest: Dict[str, Any]) -> None:
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)

    # ------------------------------------------------------------------

    async def process_folder_complete(
        self,
        folder_path: str,
        output_dir: str = None,
        parse_method: str = None,
        display_stats: bool = None,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        file_extensions: Optional[List[str]] = None,
        recursive: bool = None,
        max_workers: int = None,
        incremental: bool = False,
    ):
        """
        Process all supported files in a folder.

        Args:
            folder_path: Path to the folder containing files to process
            output_dir: Directory for parsed outputs (optional)
            parse_method: Parsing method to use (optional)
            display_stats: Whether to display statistics (optional)
            split_by_character: Character to split by (optional)
            split_by_character_only: Whether to split only by character (optional)
            file_extensions: List of file extensions to process (optional)
            recursive: Whether to process folders recursively (optional)
            max_workers: Maximum number of workers for concurrent processing (optional)
            incremental: When *True*, skip files whose MD5 digest has not changed
                since the last successful run.  A manifest file is stored inside
                ``config.working_dir`` to track previously processed files.
                New files and files whose content has changed are always
                (re-)processed.
        """
        if output_dir is None:
            output_dir = self.config.parser_output_dir
        if parse_method is None:
            parse_method = self.config.parse_method
        if display_stats is None:
            display_stats = True
        if file_extensions is None:
            file_extensions = self.config.supported_file_extensions
        if recursive is None:
            recursive = self.config.recursive_folder_processing
        if max_workers is None:
            max_workers = self.config.max_concurrent_files

        await self._ensure_lightrag_initialized()

        # Get all files in the folder
        folder_path_obj = Path(folder_path)
        if not folder_path_obj.exists():
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        # Collect files based on supported extensions
        files_to_process = []
        for file_ext in file_extensions:
            if recursive:
                pattern = f"**/*{file_ext}"
            else:
                pattern = f"*{file_ext}"
            files_to_process.extend(folder_path_obj.glob(pattern))

        if not files_to_process:
            self.logger.warning(f"No supported files found in {folder_path}")
            return

        # ---- Incremental filtering ----------------------------------------
        manifest: Dict[str, Any] = {}
        manifest_path: Optional[Path] = None
        skipped_files: List[str] = []

        if incremental:
            manifest_path = self._manifest_path(folder_path_obj)
            manifest = self._load_manifest(manifest_path)
            filtered: List[Path] = []
            for fp in files_to_process:
                key = str(fp.resolve())
                try:
                    current_md5 = self._file_md5(fp)
                    current_mtime = fp.stat().st_mtime
                except OSError:
                    # File disappeared between glob and now — skip it.
                    continue
                entry = manifest.get(key)
                if entry and entry.get("md5") == current_md5:
                    skipped_files.append(str(fp))
                else:
                    # Store prospective MD5 so we can update after success.
                    manifest[key] = {
                        "md5": current_md5,
                        "mtime": current_mtime,
                        "processed": False,
                    }
                    filtered.append(fp)
            files_to_process = filtered
            if skipped_files:
                self.logger.info(
                    f"Incremental scan: skipping {len(skipped_files)} unchanged "
                    f"file(s), processing {len(files_to_process)} new/changed file(s)"
                )
        # ---- End incremental filtering ------------------------------------

        if not files_to_process:
            if incremental:
                self.logger.info(
                    "Incremental scan: all files are up to date, nothing to process"
                )
            else:
                self.logger.warning(f"No supported files found in {folder_path}")
            return

        self.logger.info(
            f"Found {len(files_to_process)} files to process in {folder_path}"
        )

        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Process files with controlled concurrency
        semaphore = asyncio.Semaphore(max_workers)
        tasks = []

        async def process_single_file(file_path: Path):
            async with semaphore:
                is_in_subdir = (
                    lambda file_path, dir_path: (
                        len(file_path.relative_to(dir_path).parents) > 1
                    )
                )(file_path, folder_path_obj)

                try:
                    await self.process_document_complete(
                        str(file_path),
                        output_dir=(
                            output_dir
                            if not is_in_subdir
                            else str(
                                output_path
                                / file_path.parent.relative_to(folder_path_obj)
                            )
                        ),
                        parse_method=parse_method,
                        split_by_character=split_by_character,
                        split_by_character_only=split_by_character_only,
                        file_name=(
                            None
                            if not is_in_subdir
                            else str(file_path.relative_to(folder_path_obj))
                        ),
                    )
                    return True, str(file_path), None
                except Exception as e:
                    self.logger.error(f"Failed to process {file_path}: {str(e)}")
                    return False, str(file_path), str(e)

        # Create tasks for all files
        for file_path in files_to_process:
            task = asyncio.create_task(process_single_file(file_path))
            tasks.append(task)

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        successful_files = []
        failed_files = []
        for result in results:
            if isinstance(result, Exception):
                failed_files.append(("unknown", str(result)))
            else:
                success, file_path, error = result
                if success:
                    successful_files.append(file_path)
                else:
                    failed_files.append((file_path, error))

        # ---- Update incremental manifest ----------------------------------
        if incremental and manifest_path is not None:
            successful_set = set(successful_files)
            for key in list(manifest.keys()):
                # Only mark as processed if it was actually in this run.
                if key in successful_set or Path(key).resolve() in {
                    Path(f).resolve() for f in successful_set
                }:
                    manifest[key]["processed"] = True
                elif not manifest[key].get("processed"):
                    # Failed file: remove from manifest so it is retried next run.
                    del manifest[key]
            self._save_manifest(manifest_path, manifest)
        # ---- End manifest update ------------------------------------------

        # Display statistics if requested
        if display_stats:
            self.logger.info("Processing complete!")
            self.logger.info(f"  Successful: {len(successful_files)} files")
            self.logger.info(f"  Failed: {len(failed_files)} files")
            if incremental and skipped_files:
                self.logger.info(f"  Skipped (unchanged): {len(skipped_files)} files")
            if failed_files:
                self.logger.warning("Failed files:")
                for file_path, error in failed_files:
                    self.logger.warning(f"  - {file_path}: {error}")

    # ==========================================
    # NEW ENHANCED BATCH PROCESSING METHODS
    # ==========================================

    def process_documents_batch(
        self,
        file_paths: List[str],
        output_dir: Optional[str] = None,
        parse_method: Optional[str] = None,
        max_workers: Optional[int] = None,
        recursive: Optional[bool] = None,
        show_progress: bool = True,
        **kwargs,
    ) -> BatchProcessingResult:
        """
        Process multiple documents in batch using the new BatchParser

        Args:
            file_paths: List of file paths or directories to process
            output_dir: Output directory for parsed files
            parse_method: Parsing method to use
            max_workers: Maximum number of workers for parallel processing
            recursive: Whether to process directories recursively
            show_progress: Whether to show progress bar
            **kwargs: Additional arguments passed to the parser

        Returns:
            BatchProcessingResult: Results of the batch processing
        """
        # Use config defaults if not specified
        if output_dir is None:
            output_dir = self.config.parser_output_dir
        if parse_method is None:
            parse_method = self.config.parse_method
        if max_workers is None:
            max_workers = self.config.max_concurrent_files
        if recursive is None:
            recursive = self.config.recursive_folder_processing

        # Create batch parser
        batch_parser = BatchParser(
            parser_type=self.config.parser,
            max_workers=max_workers,
            show_progress=show_progress,
            skip_installation_check=True,  # Skip installation check for better UX
        )

        # Process batch
        return batch_parser.process_batch(
            file_paths=file_paths,
            output_dir=output_dir,
            parse_method=parse_method,
            recursive=recursive,
            **kwargs,
        )

    async def process_documents_batch_async(
        self,
        file_paths: List[str],
        output_dir: Optional[str] = None,
        parse_method: Optional[str] = None,
        max_workers: Optional[int] = None,
        recursive: Optional[bool] = None,
        show_progress: bool = True,
        **kwargs,
    ) -> BatchProcessingResult:
        """
        Asynchronously process multiple documents in batch

        Args:
            file_paths: List of file paths or directories to process
            output_dir: Output directory for parsed files
            parse_method: Parsing method to use
            max_workers: Maximum number of workers for parallel processing
            recursive: Whether to process directories recursively
            show_progress: Whether to show progress bar
            **kwargs: Additional arguments passed to the parser

        Returns:
            BatchProcessingResult: Results of the batch processing
        """
        # Use config defaults if not specified
        if output_dir is None:
            output_dir = self.config.parser_output_dir
        if parse_method is None:
            parse_method = self.config.parse_method
        if max_workers is None:
            max_workers = self.config.max_concurrent_files
        if recursive is None:
            recursive = self.config.recursive_folder_processing

        # Create batch parser
        batch_parser = BatchParser(
            parser_type=self.config.parser,
            max_workers=max_workers,
            show_progress=show_progress,
            skip_installation_check=True,  # Skip installation check for better UX
        )

        # Process batch asynchronously
        return await batch_parser.process_batch_async(
            file_paths=file_paths,
            output_dir=output_dir,
            parse_method=parse_method,
            recursive=recursive,
            **kwargs,
        )

    def get_supported_file_extensions(self) -> List[str]:
        """Get list of supported file extensions for batch processing"""
        batch_parser = BatchParser(parser_type=self.config.parser)
        return batch_parser.get_supported_extensions()

    def filter_supported_files(
        self, file_paths: List[str], recursive: Optional[bool] = None
    ) -> List[str]:
        """
        Filter file paths to only include supported file types

        Args:
            file_paths: List of file paths to filter
            recursive: Whether to process directories recursively

        Returns:
            List of supported file paths
        """
        if recursive is None:
            recursive = self.config.recursive_folder_processing

        batch_parser = BatchParser(parser_type=self.config.parser)
        return batch_parser.filter_supported_files(file_paths, recursive)

    async def process_documents_with_rag_batch(
        self,
        file_paths: List[str],
        output_dir: Optional[str] = None,
        parse_method: Optional[str] = None,
        max_workers: Optional[int] = None,
        recursive: Optional[bool] = None,
        show_progress: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Process documents in batch and then add them to RAG

        This method combines document parsing and RAG insertion:
        1. First, parse all documents using batch processing
        2. Then, process each successfully parsed document with RAG

        Args:
            file_paths: List of file paths or directories to process
            output_dir: Output directory for parsed files
            parse_method: Parsing method to use
            max_workers: Maximum number of workers for parallel processing
            recursive: Whether to process directories recursively
            show_progress: Whether to show progress bar
            **kwargs: Additional arguments passed to the parser

        Returns:
            Dict containing both parse results and RAG processing results
        """
        start_time = time.time()
        callback_manager = getattr(self, "callback_manager", None)
        total_files = len(file_paths)

        if callback_manager is not None:
            callback_manager.dispatch(
                "on_batch_start",
                file_count=total_files,
            )

        # Use config defaults if not specified
        if output_dir is None:
            output_dir = self.config.parser_output_dir
        if parse_method is None:
            parse_method = self.config.parse_method
        if max_workers is None:
            max_workers = self.config.max_concurrent_files
        if recursive is None:
            recursive = self.config.recursive_folder_processing

        self.logger.info("Starting batch processing with RAG integration")

        # Step 1: Parse documents in batch
        parse_result = self.process_documents_batch(
            file_paths=file_paths,
            output_dir=output_dir,
            parse_method=parse_method,
            max_workers=max_workers,
            recursive=recursive,
            show_progress=show_progress,
            **kwargs,
        )

        # Step 2: Process with RAG
        # Initialize RAG system
        await self._ensure_lightrag_initialized()

        # Then, process each successful file with RAG
        rag_results = {}

        if parse_result.successful_files:
            self.logger.info(
                f"Processing {len(parse_result.successful_files)} files with RAG"
            )

            # Process files with RAG (this could be parallelized in the future)
            for file_path in parse_result.successful_files:
                try:
                    # Process the successfully parsed file with RAG
                    await self.process_document_complete(
                        file_path,
                        output_dir=output_dir,
                        parse_method=parse_method,
                        **kwargs,
                    )

                    # Get some statistics about the processed content
                    # This would require additional tracking in the RAG system
                    rag_results[file_path] = {"status": "success", "processed": True}

                except Exception as e:
                    self.logger.error(
                        f"Failed to process {file_path} with RAG: {str(e)}"
                    )
                    rag_results[file_path] = {
                        "status": "failed",
                        "error": str(e),
                        "processed": False,
                    }

        processing_time = time.time() - start_time

        successful_rag_files = len([r for r in rag_results.values() if r["processed"]])
        failed_rag_files = len([r for r in rag_results.values() if not r["processed"]])

        if callback_manager is not None:
            callback_manager.dispatch(
                "on_batch_complete",
                total_files=total_files,
                successful=successful_rag_files,
                failed=failed_rag_files,
                duration_seconds=processing_time,
            )

        return {
            "parse_result": parse_result,
            "rag_results": rag_results,
            "total_processing_time": processing_time,
            "successful_rag_files": successful_rag_files,
            "failed_rag_files": failed_rag_files,
        }
