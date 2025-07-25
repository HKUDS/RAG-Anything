# Batch Processing and Enhanced Markdown Conversion

This document describes the new batch processing and enhanced markdown conversion features added to RAG-Anything.

## Batch Processing

### Overview

The batch processing feature allows you to process multiple documents in parallel, significantly improving throughput for large document collections.

### Key Features

- **Parallel Processing**: Process multiple files concurrently using thread pools
- **Progress Tracking**: Real-time progress bars with `tqdm`
- **Error Handling**: Comprehensive error reporting and recovery
- **Flexible Input**: Support for files, directories, and recursive search
- **Configurable Workers**: Adjustable number of parallel workers

### Usage

#### Basic Batch Processing

```python
from raganything.batch_parser import BatchParser

# Create batch parser
batch_parser = BatchParser(
    parser_type="mineru",  # or "docling"
    max_workers=4,
    show_progress=True,
    timeout_per_file=300
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
```

#### Integration with RAG-Anything

```python
from raganything import RAGAnything

rag = RAGAnything()

# Process documents with RAG integration
result = await rag.process_documents_with_rag_batch(
    file_paths=["doc1.pdf", "doc2.docx"],
    output_dir="./output",
    max_workers=4,
    show_progress=True
)

print(f"Processed {result['successful_rag_files']} files with RAG")
```

#### Command Line Interface

```bash
# Basic batch processing
python -m raganything.batch_parser path/to/docs/ --output ./output --workers 4

# With specific parser
python -m raganything.batch_parser path/to/docs/ --parser mineru --method auto

# Show progress
python -m raganything.batch_parser path/to/docs/ --output ./output --no-progress
```

### Configuration

The batch processing can be configured through environment variables:

```env
# Batch processing configuration
MAX_CONCURRENT_FILES=4
SUPPORTED_FILE_EXTENSIONS=.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt,.md
RECURSIVE_FOLDER_PROCESSING=true
```

### Supported File Types

- **PDF files**: `.pdf`
- **Office documents**: `.doc`, `.docx`, `.ppt`, `.pptx`, `.xls`, `.xlsx`
- **Images**: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.tif`, `.gif`, `.webp`
- **Text files**: `.txt`, `.md`

## Enhanced Markdown Conversion

### Overview

The enhanced markdown conversion feature provides high-quality PDF generation from markdown files with multiple backend options and advanced styling.

### Key Features

- **Multiple Backends**: WeasyPrint, Pandoc, and ReportLab support
- **Advanced Styling**: Custom CSS, syntax highlighting, and professional layouts
- **Image Support**: Embedded images with proper scaling
- **Table Support**: Formatted tables with borders and styling
- **Code Highlighting**: Syntax highlighting for code blocks
- **Custom Templates**: Support for custom CSS and templates

### Usage

#### Basic Conversion

```python
from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig

# Create converter with custom configuration
config = MarkdownConfig(
    page_size="A4",
    margin="1in",
    font_size="12pt",
    include_toc=True,
    syntax_highlighting=True
)

converter = EnhancedMarkdownConverter(config)

# Convert markdown to PDF
success = converter.convert_file_to_pdf(
    input_path="document.md",
    output_path="document.pdf",
    method="auto"  # or "weasyprint", "pandoc"
)
```

#### Advanced Configuration

```python
# Custom CSS styling
config = MarkdownConfig(
    custom_css="""
    body { font-family: 'Arial', sans-serif; }
    h1 { color: #2c3e50; border-bottom: 2px solid #3498db; }
    code { background-color: #f8f9fa; padding: 2px 4px; }
    """,
    include_toc=True,
    syntax_highlighting=True
)

converter = EnhancedMarkdownConverter(config)
```

#### Command Line Interface

```bash
# Basic conversion
python -m raganything.enhanced_markdown document.md --output document.pdf

# With specific method
python -m raganything.enhanced_markdown document.md --method weasyprint

# With custom CSS
python -m raganything.enhanced_markdown document.md --css style.css

# Show backend information
python -m raganything.enhanced_markdown --info
```

### Backend Comparison

| Backend | Pros | Cons | Best For |
|---------|------|------|----------|
| **WeasyPrint** | Excellent CSS support, fast, reliable | Requires more dependencies | Web-style documents, custom styling |
| **Pandoc** | Most features, LaTeX quality | Slower, requires system installation | Academic papers, complex documents |
| **ReportLab** | Lightweight, no external deps | Basic styling only | Simple documents, minimal setup |

### Installation

#### Required Dependencies

```bash
# Basic installation
pip install raganything[all]

# For enhanced markdown conversion
pip install markdown weasyprint pygments

# For Pandoc backend (optional)
# Download from: https://pandoc.org/installing.html
```

#### Optional Dependencies

- **WeasyPrint**: `pip install weasyprint`
- **Pandoc**: System installation required
- **Pygments**: `pip install pygments` (for syntax highlighting)

### Examples

#### Sample Markdown Input

```markdown
# Technical Documentation

## Overview
This document provides technical specifications.

### Code Example
```python
def process_document(file_path):
    return "Processed: " + file_path
```

### Performance Metrics

| Metric | Value |
|--------|-------|
| Speed | 100 docs/hour |
| Memory | 2.5 GB |

### Conclusion
The system provides excellent performance.
```

#### Generated PDF Features

- Professional typography and layout
- Syntax-highlighted code blocks
- Formatted tables with borders
- Table of contents (if enabled)
- Custom styling and branding
- Responsive image handling

### Integration with RAG-Anything

The enhanced markdown conversion integrates seamlessly with the RAG-Anything pipeline:

```python
from raganything import RAGAnything

# Initialize RAG-Anything
rag = RAGAnything()

# Process markdown files with enhanced conversion
await rag.process_documents_batch(
    file_paths=["document.md"],
    output_dir="./output",
    # Enhanced markdown conversion will be used automatically
    # for .md files
)
```

## Performance Considerations

### Batch Processing

- **Memory Usage**: Each worker uses additional memory
- **CPU Usage**: Parallel processing utilizes multiple cores
- **I/O Bottlenecks**: Disk I/O may become limiting factor
- **Recommended Settings**: 2-4 workers for most systems

### Enhanced Markdown

- **WeasyPrint**: Fastest for most documents
- **Pandoc**: Best quality but slower
- **Large Documents**: Consider chunking for very large files
- **Image Processing**: Large images may slow conversion

## Troubleshooting

### Common Issues

#### Batch Processing

1. **Memory Errors**: Reduce `max_workers`
2. **Timeout Errors**: Increase `timeout_per_file`
3. **File Not Found**: Check file paths and permissions
4. **Parser Errors**: Verify parser installation

#### Enhanced Markdown

1. **WeasyPrint Errors**: Install system dependencies
2. **Pandoc Not Found**: Install Pandoc system-wide
3. **CSS Issues**: Check CSS syntax and file paths
4. **Image Problems**: Ensure images are accessible

### Debug Mode

Enable debug logging for detailed information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Conclusion

The batch processing and enhanced markdown conversion features significantly improve RAG-Anything's capabilities for processing large document collections and generating high-quality PDFs from markdown content. These features are designed to be easy to use while providing advanced configuration options for power users.
