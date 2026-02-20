# Batch Processing

This document describes the batch processing feature for RAG-Anything, which allows you to process multiple documents in parallel for improved throughput.

## Overview

The batch processing feature allows you to process multiple documents concurrently, significantly improving throughput for large document collections. It provides parallel processing, progress tracking, error handling, and flexible configuration options.

## Key Features

- **Parallel Processing**: Process multiple files concurrently using thread pools
- **Progress Tracking**: Real-time progress bars with `tqdm`
- **Error Handling**: Comprehensive error reporting and recovery
- **Flexible Input**: Support for files, directories, and recursive search
- **Dry Run**: Preview which files would be processed without running parsers
- **Configurable Workers**: Adjustable number of parallel workers
- **Installation Check Bypass**: Optional skip for environments with package conflicts

## Installation

```bash
# Basic installation
pip install raganything[all]

# Required for batch processing
pip install tqdm

# Optional for parser='paddleocr'
pip install raganything[paddleocr]
```

## Usage

### Basic Batch Processing

```python
from raganything.batch_parser import BatchParser

# Create batch parser
batch_parser = BatchParser(
    parser_type="mineru",  # or "docling" or "paddleocr"
    max_workers=4,
    show_progress=True,
    timeout_per_file=300,
    skip_installation_check=False  # Set to True if having parser installation issues
)

# Process multiple files
result = batch_parser.process_batch(
    file_paths=["doc1.pdf", "doc2.docx", "folder/"],
    output_dir="./batch_output",
    parse_method="auto",
    recursive=True
)

# Check results
print(result.summary())
print(f"Success rate: {result.success_rate:.1f}%")
print(f"Processing time: {result.processing_time:.2f} seconds")
```

### Asynchronous Batch Processing

```python
import asyncio
from raganything.batch_parser import BatchParser

async def async_batch_processing():
    batch_parser = BatchParser(
        parser_type="mineru",
        max_workers=4,
        show_progress=True
    )

    # Process files asynchronously
    result = await batch_parser.process_batch_async(
        file_paths=["doc1.pdf", "doc2.docx"],
        output_dir="./output",
        parse_method="auto"
    )

    return result

# Run async processing
result = asyncio.run(async_batch_processing())
```

### Integration with RAG-Anything

```python
from raganything import RAGAnything

rag = RAGAnything()

# Process documents with batch functionality
result = rag.process_documents_batch(
    file_paths=["doc1.pdf", "doc2.docx"],
    output_dir="./output",
    max_workers=4,
    show_progress=True
)

print(f"Processed {len(result.successful_files)} files successfully")
```

### Process Documents with RAG Integration

```python
# Process documents in batch and then add them to RAG
result = await rag.process_documents_with_rag_batch(
    file_paths=["doc1.pdf", "doc2.docx"],
    output_dir="./output",
    max_workers=4,
    show_progress=True
)

print(f"Processed {result['successful_rag_files']} files with RAG")
print(f"Total processing time: {result['total_processing_time']:.2f} seconds")
```

### Command Line Interface

```bash
# Basic batch processing
python -m raganything.batch_parser examples/sample_docs/ --output ./output --workers 4

# With specific parser
python -m raganything.batch_parser examples/sample_docs/ --parser mineru --method auto
python -m raganything.batch_parser examples/sample_docs/ --parser paddleocr --method ocr

# Without progress bar
python -m raganything.batch_parser examples/sample_docs/ --output ./output --no-progress

# Dry run (list supported files without processing)
python -m raganything.batch_parser examples/sample_docs/ --output ./output --dry-run

# Help
python -m raganything.batch_parser --help
```

## Configuration

### Environment Variables

```env
# Batch processing configuration
MAX_CONCURRENT_FILES=4
SUPPORTED_FILE_EXTENSIONS=.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt,.md
RECURSIVE_FOLDER_PROCESSING=true
PARSER_OUTPUT_DIR=./parsed_output
```

### BatchParser Parameters

- **parser_type**: `"mineru"`, `"docling"`, or `"paddleocr"` (default: `"mineru"`)
- **max_workers**: Number of parallel workers (default: `4`)
- **show_progress**: Show progress bar (default: `True`)
- **timeout_per_file**: Timeout per file in seconds (default: `300`)
- **skip_installation_check**: Skip parser installation check (default: `False`)

## Supported File Types

- **PDF files**: `.pdf`
- **Office documents**: `.doc`, `.docx`, `.ppt`, `.pptx`, `.xls`, `.xlsx`
- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.tif`, `.gif`, `.webp`
- **Text files**: `.txt`, `.md`

## API Reference

### BatchProcessingResult

```python
@dataclass
class BatchProcessingResult:
    successful_files: List[str]      # Successfully processed files
    failed_files: List[str]          # Failed files
    total_files: int                 # Total number of files
    processing_time: float           # Total processing time in seconds
    errors: Dict[str, str]           # Error messages for failed files
    output_dir: str                  # Output directory used
    dry_run: bool                    # True if run was a dry-run

    def summary(self) -> str:        # Human-readable summary
    def success_rate(self) -> float: # Success rate as percentage
```

### BatchParser Methods

```python
class BatchParser:
    def __init__(self, parser_type: str = "mineru", max_workers: int = 4, ...):
        """Initialize batch parser"""

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions"""

    def filter_supported_files(self, file_paths: List[str], recursive: bool = True) -> List[str]:
        """Filter files to only supported types"""

    def process_batch(self, file_paths: List[str], output_dir: str, ...) -> BatchProcessingResult:
        """Process files in batch"""

    async def process_batch_async(self, file_paths: List[str], output_dir: str, ...) -> BatchProcessingResult:
        """Process files in batch asynchronously"""
```

## Performance Considerations

### Memory Usage
- Each worker uses additional memory
- Recommended: 2-4 workers for most systems
- Monitor memory usage with large files

### CPU Usage
- Parallel processing utilizes multiple cores
- Optimal worker count depends on CPU cores and file sizes
- I/O may become bottleneck with many small files

### Recommended Settings
- **Small files** (< 1MB): Higher worker count (6-8)
- **Large files** (> 100MB): Lower worker count (2-3)
- **Mixed sizes**: Start with 4 workers and adjust

## Troubleshooting

### Common Issues

#### Memory Errors
```python
# Solution: Reduce max_workers
batch_parser = BatchParser(max_workers=2)
```

#### Timeout Errors
```python
# Solution: Increase timeout_per_file
batch_parser = BatchParser(timeout_per_file=600)  # 10 minutes
```

#### Parser Installation Issues
```python
# Solution: Skip installation check
batch_parser = BatchParser(skip_installation_check=True)
```

#### File Not Found Errors
- Check file paths and permissions
- Ensure input files exist
- Verify directory access rights

### Debug Mode

Enable debug logging for detailed information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Create batch parser with debug logging
batch_parser = BatchParser(parser_type="mineru", max_workers=2)
```

### Error Handling

The batch processor provides comprehensive error handling:

```python
result = batch_parser.process_batch(file_paths=["doc1.pdf", "doc2.docx"])

# Check for errors
if result.failed_files:
    print("Failed files:")
    for file_path in result.failed_files:
        error_message = result.errors.get(file_path, "Unknown error")
        print(f"  - {file_path}: {error_message}")

# Process only successful files
for file_path in result.successful_files:
    print(f"Successfully processed: {file_path}")
```

## Examples

### Process Entire Directory

```python
from pathlib import Path

# Process all supported files in a directory
batch_parser = BatchParser(max_workers=4)
directory_path = Path("./documents")

result = batch_parser.process_batch(
    file_paths=[str(directory_path)],
    output_dir="./processed",
    recursive=True  # Include subdirectories
)

print(f"Processed {len(result.successful_files)} out of {result.total_files} files")
```

### Filter Files Before Processing

```python
# Get all files in directory
all_files = ["doc1.pdf", "image.png", "spreadsheet.xlsx", "unsupported.xyz"]

# Filter to supported files only
supported_files = batch_parser.filter_supported_files(all_files)
print(f"Will process {len(supported_files)} out of {len(all_files)} files")

# Process only supported files
result = batch_parser.process_batch(
    file_paths=supported_files,
    output_dir="./output"
)
```

### Custom Error Handling

```python
def process_with_retry(file_paths, max_retries=3):
    """Process files with retry logic"""

    for attempt in range(max_retries):
        result = batch_parser.process_batch(file_paths, "./output")

        if not result.failed_files:
            break  # All files processed successfully

        print(f"Attempt {attempt + 1}: {len(result.failed_files)} files failed")
        file_paths = result.failed_files  # Retry failed files

    return result
```

## Best Practices

1. **Start with default settings** and adjust based on performance
2. **Monitor system resources** during batch processing
3. **Use appropriate worker counts** for your hardware
4. **Handle errors gracefully** with retry logic
5. **Test with small batches** before processing large collections
6. **Use skip_installation_check** if facing parser installation issues
7. **Enable progress tracking** for long-running operations
8. **Set appropriate timeouts** based on expected file processing times

## Conclusion

The batch processing feature significantly improves RAG-Anything's throughput for large document collections. It provides flexible configuration options, comprehensive error handling, and seamless integration with the existing RAG-Anything pipeline.
