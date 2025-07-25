#!/usr/bin/env python
"""
Example script demonstrating batch processing and enhanced markdown conversion

This example shows how to:
1. Process multiple documents in parallel using batch processing
2. Convert markdown files to PDF with enhanced formatting
3. Use different conversion backends for markdown
"""

import asyncio
import logging
from pathlib import Path
import tempfile

# Add project root directory to Python path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from raganything import RAGAnything, RAGAnythingConfig
from raganything.batch_parser import BatchParser
from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig


def create_sample_markdown_files():
    """Create sample markdown files for testing"""
    sample_files = []
    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp())
    # Sample 1: Basic markdown
    sample1_content = """# Sample Document 1

This is a basic markdown document with various elements.

## Headers
This document demonstrates different markdown features.

### Lists
- Item 1
- Item 2
- Item 3

### Code
```python
def hello_world():
    print("Hello, World!")
```

### Tables
| Name | Age | City |
|------|-----|------|
| Alice | 25 | New York |
| Bob | 30 | London |
| Carol | 28 | Paris |

### Blockquotes
> This is a blockquote with some important information.

### Links and Images
Visit [GitHub](https://github.com) for more information.
"""

    sample1_path = temp_dir / "sample1.md"
    with open(sample1_path, "w", encoding="utf-8") as f:
        f.write(sample1_content)
    sample_files.append(str(sample1_path))

    # Sample 2: Technical document
    sample2_content = """# Technical Documentation

## Overview
This document provides technical specifications for the RAG-Anything system.

## Architecture

### Core Components
1. **Document Parser**: Handles multiple file formats
2. **Multimodal Processor**: Processes images, tables, equations
3. **Knowledge Graph**: Stores relationships and entities
4. **Query Engine**: Provides intelligent retrieval

### Code Examples

#### Python Implementation
```python
from raganything import RAGAnything

# Initialize the system
rag = RAGAnything()

# Process documents
await rag.process_document_complete("document.pdf")
```

#### Configuration
```yaml
working_dir: "./rag_storage"
enable_image_processing: true
enable_table_processing: true
max_concurrent_files: 4
```

## Performance Metrics

| Metric | Value | Unit |
|--------|-------|------|
| Processing Speed | 100 | docs/hour |
| Memory Usage | 2.5 | GB |
| Accuracy | 95.2 | % |

## Conclusion
The system provides excellent performance for multimodal document processing.
"""

    sample2_path = temp_dir / "sample2.md"
    with open(sample2_path, "w", encoding="utf-8") as f:
        f.write(sample2_content)
    sample_files.append(str(sample2_path))

    return sample_files, temp_dir


def demonstrate_batch_processing():
    """Demonstrate batch processing functionality"""
    print("\n" + "=" * 50)
    print("BATCH PROCESSING DEMONSTRATION")
    print("=" * 50)

    # Create sample files
    sample_files, temp_dir = create_sample_markdown_files()

    try:
        # Create batch parser
        batch_parser = BatchParser(
            parser_type="mineru",
            max_workers=2,
            show_progress=True,
            timeout_per_file=60,
            skip_installation_check=True,  # Add this parameter to bypass installation check
        )

        print(f"Created {len(sample_files)} sample markdown files:")
        for file_path in sample_files:
            print(f"  - {file_path}")

        # Process files in batch
        output_dir = temp_dir / "batch_output"
        result = batch_parser.process_batch(
            file_paths=sample_files,
            output_dir=str(output_dir),
            parse_method="auto",
            recursive=False,
        )

        # Display results
        print("\nBatch Processing Results:")
        print(result.summary())

        if result.failed_files:
            print("\nFailed files:")
            for file_path in result.failed_files:
                print(
                    f"  - {file_path}: {result.errors.get(file_path, 'Unknown error')}"
                )

        return result

    except Exception as e:
        print(f"Batch processing failed: {str(e)}")
        return None


def demonstrate_enhanced_markdown():
    """Demonstrate enhanced markdown conversion"""
    print("\n" + "=" * 50)
    print("ENHANCED MARKDOWN CONVERSION DEMONSTRATION")
    print("=" * 50)

    # Create sample files
    sample_files, temp_dir = create_sample_markdown_files()

    try:
        # Create enhanced markdown converter
        config = MarkdownConfig(
            page_size="A4",
            margin="1in",
            font_size="12pt",
            include_toc=True,
            syntax_highlighting=True,
        )

        converter = EnhancedMarkdownConverter(config)

        # Show backend information
        backend_info = converter.get_backend_info()
        print("Available backends:")
        for backend, available in backend_info["available_backends"].items():
            status = "✅" if available else "❌"
            print(f"  {status} {backend}")
        print(f"Recommended backend: {backend_info['recommended_backend']}")

        # Convert each sample file
        conversion_results = []

        for i, markdown_file in enumerate(sample_files, 1):
            print(f"\nConverting sample {i}...")
            # Try different conversion methods
            for method in ["auto", "weasyprint", "pandoc"]:
                try:
                    output_path = temp_dir / f"sample{i}_{method}.pdf"

                    success = converter.convert_file_to_pdf(
                        input_path=markdown_file,
                        output_path=str(output_path),
                        method=method,
                    )

                    if success:
                        print(f"  ✅ {method}: {output_path}")
                        conversion_results.append(
                            {
                                "file": markdown_file,
                                "method": method,
                                "output": str(output_path),
                                "success": True,
                            }
                        )
                        break  # Use first successful method
                    else:
                        print(f"  ❌ {method}: Failed")

                except Exception as e:
                    print(f"  ❌ {method}: {str(e)}")
                    continue

        # Summary
        print("\nConversion Summary:")
        print(f"  Total files: {len(sample_files)}")
        print(f"  Successful conversions: {len(conversion_results)}")

        return conversion_results

    except Exception as e:
        print(f"Enhanced markdown conversion failed: {str(e)}")
        return None


async def demonstrate_integration():
    """Demonstrate integration with RAG-Anything"""
    print("\n" + "=" * 50)
    print("RAG-ANYTHING INTEGRATION DEMONSTRATION")
    print("=" * 50)

    # Create sample files
    sample_files, temp_dir = create_sample_markdown_files()

    try:
        # Initialize RAG-Anything (without API keys for demo)
        config = RAGAnythingConfig(
            working_dir=str(temp_dir / "rag_storage"),
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )

        rag = RAGAnything(config=config)

        # Demonstrate batch processing with RAG
        print("Processing documents with batch functionality...")

        # Note: This would require actual API keys for full functionality
        # For demo purposes, we'll just show the interface
        print("  - Batch processing interface available")
        print("  - Enhanced markdown conversion available")
        print("  - Integration with multimodal processors available")

        # Show that rag object has the expected methods
        print(f"  - RAG instance created: {type(rag).__name__}")
        print(
            f"  - Available batch methods: {[m for m in dir(rag) if 'batch' in m.lower()]}"
        )

        return True

    except Exception as e:
        print(f"Integration demonstration failed: {str(e)}")
        return False


def main():
    """Main demonstration function"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("RAG-Anything Batch Processing and Enhanced Markdown Demo")
    print("=" * 60)

    # Demonstrate batch processing
    batch_result = demonstrate_batch_processing()

    # Demonstrate enhanced markdown conversion
    markdown_result = demonstrate_enhanced_markdown()

    # Demonstrate integration
    asyncio.run(demonstrate_integration())

    # Summary
    print("\n" + "=" * 60)
    print("DEMONSTRATION SUMMARY")
    print("=" * 60)
    if batch_result:
        print(f"Batch Processing: {batch_result.success_rate:.1f}% success rate")
    else:
        print("Batch Processing: Failed")

    if markdown_result:
        print(f"Enhanced Markdown: {len(markdown_result)} successful conversions")
    else:
        print("Enhanced Markdown: Failed")

    print("\nFeatures demonstrated:")
    print("  - Parallel document processing with progress tracking")
    print("  - Multiple markdown conversion backends (WeasyPrint, Pandoc)")
    print("  - Enhanced styling and formatting")
    print("  - Integration with RAG-Anything pipeline")
    print("  - Comprehensive error handling and reporting")


if __name__ == "__main__":
    main()
