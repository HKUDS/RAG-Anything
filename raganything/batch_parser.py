"""
Batch and Parallel Document Parsing

This module provides functionality for processing multiple documents in parallel,
with progress reporting and error handling.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import time

from tqdm import tqdm

from .parser import MineruParser, DoclingParser


@dataclass
class BatchProcessingResult:
    """Result of batch processing operation"""

    successful_files: List[str]
    failed_files: List[str]
    total_files: int
    processing_time: float
    errors: Dict[str, str]
    output_dir: str

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_files == 0:
            return 0.0
        return (len(self.successful_files) / self.total_files) * 100

    def summary(self) -> str:
        """Generate a summary of the batch processing results"""
        return (
            f"Batch Processing Summary:\n"
            f"  Total files: {self.total_files}\n"
            f"  Successful: {len(self.successful_files)} ({self.success_rate:.1f}%)\n"
            f"  Failed: {len(self.failed_files)}\n"
            f"  Processing time: {self.processing_time:.2f} seconds\n"
            f"  Output directory: {self.output_dir}"
        )


class BatchParser:
    """
    Batch document parser with parallel processing capabilities

    Supports processing multiple documents concurrently with progress tracking
    and comprehensive error handling.
    """

    def __init__(
        self,
        parser_type: str = "mineru",
        max_workers: int = 4,
        show_progress: bool = True,
        timeout_per_file: int = 300,
        skip_installation_check: bool = False,
    ):
        """
        Initialize batch parser

        Args:
            parser_type: Type of parser to use ("mineru" or "docling")
            max_workers: Maximum number of parallel workers
            show_progress: Whether to show progress bars
            timeout_per_file: Timeout in seconds for each file
            skip_installation_check: Skip parser installation check (useful for testing)
        """
        self.parser_type = parser_type
        self.max_workers = max_workers
        self.show_progress = show_progress
        self.timeout_per_file = timeout_per_file
        self.logger = logging.getLogger(__name__)

        # Initialize parser
        if parser_type == "mineru":
            self.parser = MineruParser()
        elif parser_type == "docling":
            self.parser = DoclingParser()
        else:
            raise ValueError(f"Unsupported parser type: {parser_type}")

        # Check parser installation (optional)
        if not skip_installation_check:
            if not self.parser.check_installation():
                self.logger.warning(
                    f"{parser_type.title()} parser installation check failed. "
                    f"This may be due to package conflicts. "
                    f"Use skip_installation_check=True to bypass this check."
                )
                # Don't raise an error, just warn - the parser might still work

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions"""
        return list(
            self.parser.OFFICE_FORMATS
            | self.parser.IMAGE_FORMATS
            | self.parser.TEXT_FORMATS
            | {".pdf"}
        )

    def filter_supported_files(
        self, file_paths: List[str], recursive: bool = True
    ) -> List[str]:
        """
        Filter file paths to only include supported file types

        Args:
            file_paths: List of file paths or directories
            recursive: Whether to search directories recursively

        Returns:
            List of supported file paths
        """
        supported_extensions = set(self.get_supported_extensions())
        supported_files = []

        for path_str in file_paths:
            path = Path(path_str)

            if path.is_file():
                if path.suffix.lower() in supported_extensions:
                    supported_files.append(str(path))
                else:
                    self.logger.warning(f"Unsupported file type: {path}")

            elif path.is_dir():
                if recursive:
                    # Recursively find all files
                    for file_path in path.rglob("*"):
                        if (
                            file_path.is_file()
                            and file_path.suffix.lower() in supported_extensions
                        ):
                            supported_files.append(str(file_path))
                else:
                    # Only files in the directory (not subdirectories)
                    for file_path in path.glob("*"):
                        if (
                            file_path.is_file()
                            and file_path.suffix.lower() in supported_extensions
                        ):
                            supported_files.append(str(file_path))

            else:
                self.logger.warning(f"Path does not exist: {path}")

        return supported_files

    def process_single_file(
        self, file_path: str, output_dir: str, parse_method: str = "auto", **kwargs
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Process a single file

        Args:
            file_path: Path to the file to process
            output_dir: Output directory
            parse_method: Parsing method
            **kwargs: Additional parser arguments

        Returns:
            Tuple of (success, file_path, error_message)
        """
        try:
            start_time = time.time()

            # Create file-specific output directory
            file_name = Path(file_path).stem
            file_output_dir = Path(output_dir) / file_name
            file_output_dir.mkdir(parents=True, exist_ok=True)

            # Parse the document
            content_list = self.parser.parse_document(
                file_path=file_path,
                output_dir=str(file_output_dir),
                method=parse_method,
                **kwargs,
            )

            processing_time = time.time() - start_time

            self.logger.info(
                f"Successfully processed {file_path} "
                f"({len(content_list)} content blocks, {processing_time:.2f}s)"
            )

            return True, file_path, None

        except Exception as e:
            error_msg = f"Failed to process {file_path}: {str(e)}"
            self.logger.error(error_msg)
            return False, file_path, error_msg

    def process_batch(
        self,
        file_paths: List[str],
        output_dir: str,
        parse_method: str = "auto",
        recursive: bool = True,
        **kwargs,
    ) -> BatchProcessingResult:
        """
        Process multiple files in parallel

        Args:
            file_paths: List of file paths or directories to process
            output_dir: Base output directory
            parse_method: Parsing method for all files
            recursive: Whether to search directories recursively
            **kwargs: Additional parser arguments

        Returns:
            BatchProcessingResult with processing statistics
        """
        start_time = time.time()

        # Filter to supported files
        supported_files = self.filter_supported_files(file_paths, recursive)

        if not supported_files:
            self.logger.warning("No supported files found to process")
            return BatchProcessingResult(
                successful_files=[],
                failed_files=[],
                total_files=0,
                processing_time=0.0,
                errors={},
                output_dir=output_dir,
            )

        self.logger.info(f"Found {len(supported_files)} files to process")

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Process files in parallel
        successful_files = []
        failed_files = []
        errors = {}

        # Create progress bar if requested
        pbar = None
        if self.show_progress:
            pbar = tqdm(
                total=len(supported_files),
                desc=f"Processing files ({self.parser_type})",
                unit="file",
            )

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                future_to_file = {
                    executor.submit(
                        self.process_single_file,
                        file_path,
                        output_dir,
                        parse_method,
                        **kwargs,
                    ): file_path
                    for file_path in supported_files
                }

                # Process completed tasks
                for future in as_completed(
                    future_to_file, timeout=self.timeout_per_file
                ):
                    success, file_path, error_msg = future.result()

                    if success:
                        successful_files.append(file_path)
                    else:
                        failed_files.append(file_path)
                        errors[file_path] = error_msg

                    if pbar:
                        pbar.update(1)

        except Exception as e:
            self.logger.error(f"Batch processing failed: {str(e)}")
            # Mark remaining files as failed
            for future in future_to_file:
                if not future.done():
                    file_path = future_to_file[future]
                    failed_files.append(file_path)
                    errors[file_path] = f"Processing interrupted: {str(e)}"
                    if pbar:
                        pbar.update(1)

        finally:
            if pbar:
                pbar.close()

        processing_time = time.time() - start_time

        # Create result
        result = BatchProcessingResult(
            successful_files=successful_files,
            failed_files=failed_files,
            total_files=len(supported_files),
            processing_time=processing_time,
            errors=errors,
            output_dir=output_dir,
        )

        # Log summary
        self.logger.info(result.summary())

        return result

    async def process_batch_async(
        self,
        file_paths: List[str],
        output_dir: str,
        parse_method: str = "auto",
        recursive: bool = True,
        **kwargs,
    ) -> BatchProcessingResult:
        """
        Async version of batch processing

        Args:
            file_paths: List of file paths or directories to process
            output_dir: Base output directory
            parse_method: Parsing method for all files
            recursive: Whether to search directories recursively
            **kwargs: Additional parser arguments

        Returns:
            BatchProcessingResult with processing statistics
        """
        # Run the sync version in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.process_batch,
            file_paths,
            output_dir,
            parse_method,
            recursive,
            **kwargs,
        )


def main():
    """Command-line interface for batch parsing"""
    import argparse

    parser = argparse.ArgumentParser(description="Batch document parsing")
    parser.add_argument("paths", nargs="+", help="File paths or directories to process")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument(
        "--parser",
        choices=["mineru", "docling"],
        default="mineru",
        help="Parser to use",
    )
    parser.add_argument(
        "--method",
        choices=["auto", "txt", "ocr"],
        default="auto",
        help="Parsing method",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of parallel workers"
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bar"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Search directories recursively",
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="Timeout per file (seconds)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        # Create batch parser
        batch_parser = BatchParser(
            parser_type=args.parser,
            max_workers=args.workers,
            show_progress=not args.no_progress,
            timeout_per_file=args.timeout,
        )

        # Process files
        result = batch_parser.process_batch(
            file_paths=args.paths,
            output_dir=args.output,
            parse_method=args.method,
            recursive=args.recursive,
        )

        # Print summary
        print("\n" + result.summary())

        # Exit with error code if any files failed
        if result.failed_files:
            return 1

        return 0

    except Exception as e:
        print(f"Error: {str(e)}")
        return 1


if __name__ == "__main__":
    exit(main())
