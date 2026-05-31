#!/usr/bin/env python
"""
Enhanced Markdown Conversion Example for RAG-Anything

This example demonstrates the enhanced markdown to PDF conversion capabilities
with multiple backends, advanced styling, and professional formatting.

Features demonstrated:
- Basic markdown to PDF conversion
- Multiple conversion backends (WeasyPrint, Pandoc)
- Custom CSS styling and configuration
- Backend detection and selection
- Error handling and fallback mechanisms
- Command-line interface usage
"""

import logging
from pathlib import Path
import tempfile

# Add project root directory to Python path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig


def create_sample_markdown_content():
    """Create comprehensive sample markdown content for testing"""

    # Basic sample
    basic_content = """# Basic Markdown Sample

## Introduction
This is a simple markdown document demonstrating basic formatting.

### Text Formatting
- **Bold text** and *italic text*
- `Inline code` examples
- [Links to external sites](https://github.com)

### Lists
1. First ordered item
2. Second ordered item
3. Third ordered item

- Unordered item
- Another unordered item
  - Nested item
  - Another nested item

### Blockquotes
> This is a blockquote with important information.
> It can span multiple lines.

### Code Block
```python
def hello_world():
    print("Hello, World!")
    return "Success"
```
"""

    # Technical documentation sample
    technical_content = """# Technical Documentation

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Implementation](#implementation)
- [Performance](#performance)

## Overview
This document provides comprehensive technical specifications for the enhanced markdown conversion system.

## Architecture

### Core Components
1. **Markdown Parser**: Processes markdown syntax
2. **CSS Engine**: Applies styling and layout
3. **PDF Generator**: Creates final PDF output
4. **Backend Manager**: Handles multiple conversion engines

### Data Flow
```mermaid
graph LR
    A[Markdown Input] --> B[Parser]
    B --> C[CSS Processor]
    C --> D[PDF Generator]
    D --> E[PDF Output]
```

## Implementation

### Python Code Example
```python
from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig

# Configure converter
config = MarkdownConfig(
    page_size="A4",
    margin="1in",
    include_toc=True,
    syntax_highlighting=True
)

# Create converter
converter = EnhancedMarkdownConverter(config)

# Convert to PDF
success = converter.convert_file_to_pdf(
    input_path="document.md",
    output_path="output.pdf",
    method="weasyprint"
)
```

### Configuration Options
```yaml
converter:
  page_size: A4
  margin: 1in
  font_size: 12pt
  include_toc: true
  syntax_highlighting: true
  backend: weasyprint
```

## Performance

### Benchmark Results
| Backend | Speed | Quality | Features |
|---------|-------|---------|----------|
| WeasyPrint | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Pandoc | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

### Processing Times
- **Small documents** (< 10 pages): 1-3 seconds
- **Medium documents** (10-50 pages): 3-10 seconds
- **Large documents** (> 50 pages): 10-30 seconds

## Advanced Features

### Custom CSS Styling
The system supports advanced CSS customization:

```css
body {
    font-family: 'Georgia', serif;
    line-height: 1.6;
    color: #333;
}

h1 {
    color: #2c3e50;
    border-bottom: 2px solid #3498db;
    padding-bottom: 0.3em;
}

code {
    background-color: #f8f9fa;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
}

pre {
    background-color: #f8f9fa;
    border-left: 4px solid #3498db;
    padding: 15px;
    border-radius: 5px;
    overflow-x: auto;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

th, td {
    border: 1px solid #ddd;
    padding: 8px 12px;
    text-align: left;
}

th {
    background-color: #f2f2f2;
    font-weight: bold;
}
```

### Image Support
![Sample Image](https://via.placeholder.com/400x200/3498db/ffffff?text=Sample+Image)

Images are automatically scaled and positioned appropriately in the PDF output.

## Conclusion
The enhanced markdown conversion system provides professional-quality PDF generation with extensive customization options and multiple backend support.

---

*Generated on: 2024-01-15*
*Version: 1.0.0*
"""

    # Academic paper sample
    academic_content = """# Research Paper: Advanced Document Processing

**Authors:** Alice Johnson¹, Bob Smith², Carol Williams¹
**Affiliations:**
¹ University of Technology
² Research Institute

## Abstract

This paper presents a comprehensive analysis of advanced document processing techniques using enhanced markdown conversion. Our research demonstrates significan't improvements in processing speed and output quality through optimized backend selection and custom styling approaches.

**Keywords:** document processing, markdown conversion, PDF generation, performance optimization

## 1. Introduction

Document processing has become increasingly important in modern information systems. The ability to convert markdown documents to high-quality PDF outputs with professional formatting is crucial for academic, technical, and business applications.

### 1.1 Research Objectives

1. Evaluate different markdown conversion backends
2. Analyze performance characteristics of each approach
3. Develop optimization strategies for large-scale processing
4. Design flexible configuration systems for diverse use cases

### 1.2 Contributions

This work makes the following contributions:
- Comprehensive comparison of markdown conversion backends
- Performance optimization techniques for large documents
- Flexible configuration framework for customization
- Integration patterns for document processing pipelines

## 2. Methodology

### 2.1 Experimental Setup

We conducted experiments using the following configuration:

```python
# Experimental configuration
config = MarkdownConfig(
    page_size="A4",
    margin="1in",
    font_size="11pt",
    line_height="1.4",
    include_toc=True,
    syntax_highlighting=True
)
```

### 2.2 Test Documents

| Category | Count | Avg Size | Complexity |
|----------|-------|----------|------------|
| Simple | 100 | 2 pages | Low |
| Medium | 50 | 10 pages | Medium |
| Complex | 25 | 25 pages | High |

### 2.3 Metrics

We evaluated performance using the following metrics:
- **Conversion Speed**: Time to generate PDF (seconds)
- **Memory Usage**: Peak memory consumption (MB)
- **Output Quality**: Visual assessment score (1-10)
- **Feature Support**: Number of supported markdown features

## 3. Results

### 3.1 Performance Comparison

The following table summarizes our performance results:

| Backend | Speed (s) | Memory (MB) | Quality | Features |
|---------|-----------|-------------|---------|----------|
| WeasyPrint | 2.3 ± 0.5 | 85 ± 15 | 8.5 | 85% |
| Pandoc | 4.7 ± 1.2 | 120 ± 25 | 9.2 | 95% |

### 3.2 Quality Analysis

#### 3.2.1 Typography
WeasyPrint excels in web-style typography with excellent CSS support, while Pandoc provides superior academic formatting with LaTeX-quality output.

#### 3.2.2 Code Highlighting
Both backends support syntax highlighting through Pygments:

```python
def analyze_performance(backend, documents):
    '''Analyze conversion performance for given backend'''
    results = []

    for doc in documents:
        start_time = time.time()
        success = backend.convert(doc)
        end_time = time.time()

        results.append({
            'document': doc,
            'time': end_time - start_time,
            'success': success
        })

    return results
```

### 3.3 Scalability

Our scalability analysis shows:
- Linear scaling with document size for both backends
- Memory usage proportional to content complexity
- Optimal batch sizes of 10-20 documents for parallel processing

## 4. Discussion

### 4.1 Backend Selection Guidelines

Choose **WeasyPrint** for:
- Web-style documents with custom CSS
- Fast conversion requirements
- Simple to medium complexity documents

Choose **Pandoc** for:
- Academic papers and publications
- Complex document structures
- Maximum feature support requirements

### 4.2 Optimization Strategies

1. **Image Optimization**: Compress images before embedding
2. **CSS Minimization**: Use efficient CSS selectors
3. **Content Chunking**: Process large documents in sections
4. **Caching**: Cache converted content for repeated use

## 5. Conclusion

This research demonstrates that enhanced markdown conversion provides significan't benefits for document processing workflows. The choice between WeasyPrint and Pandoc depends on specific requirements for speed, quality, and features.

### 5.1 Future Work

- Integration with cloud processing services
- Real-time collaborative editing support
- Advanced template systems
- Performance optimization for very large documents

## References

1. Johnson, A. et al. (2024). "Advanced Document Processing Techniques." *Journal of Information Systems*, 15(3), 45-62.
2. Smith, B. (2023). "PDF Generation Optimization." *Technical Computing Review*, 8(2), 12-28.
3. Williams, C. (2024). "Markdown Processing Frameworks." *Software Engineering Quarterly*, 22(1), 78-95.

---

**Manuscript received:** January 10, 2024
**Accepted for publication:** January 15, 2024
**Published online:** January 20, 2024
"""

    return {
        "basic": basic_content,
        "technical": technical_content,
        "academic": academic_content,
    }


def demonstrate_basic_conversion():
    """Demonstrate basic markdown to PDF conversion"""
    print("\n" + "=" * 60)
    print("BASIC MARKDOWN CONVERSION DEMONSTRATION")
    print("=" * 60)

    try:
        # Create converter with default settings
        converter = EnhancedMarkdownConverter()

        # Show backend information
        backend_info = converter.get_backend_info()
        print("Available conversion backends:")
        for backend, available in backend_info["available_backends"].items():
            status = "✅" if available else "❌"
            print(f"  {status} {backend}")
        print(f"Recommended backend: {backend_info['recommended_backend']}")

        # Get sample content
        samples = create_sample_markdown_content()
        temp_dir = Path(tempfile.mkdtemp())

        # Convert basic sample
        basic_md_path = temp_dir / "basic_sample.md"
        with open(basic_md_path, "w", encoding="utf-8") as f:
            f.write(samples["basic"])

        print(f"\nConverting basic sample: {basic_md_path}")

        success = converter.convert_file_to_pdf(
            input_path=str(basic_md_path),
            output_path=str(temp_dir / "basic_sample.pdf"),
            method="auto",  # Let the system choose the best backend
        )

        if success:
            print("✅ Basic conversion successful!")
            print(f"   Output: {temp_dir / 'basic_sample.pdf'}")
        else:
            print("❌ Basic conversion failed")

        return success, temp_dir

    except Exception as e:
        print(f"❌ Basic conversion demonstration failed: {str(e)}")
        return False, None


def demonstrate_backend_comparison():
    """Demonstrate different conversion backends"""
    print("\n" + "=" * 60)
    print("BACKEND COMPARISON DEMONSTRATION")
    print("=" * 60)

    try:
        samples = create_sample_markdown_content()
        temp_dir = Path(tempfile.mkdtemp())

        # Create technical document
        tech_md_path = temp_dir / "technical.md"
        with open(tech_md_path, "w", encoding="utf-8") as f:
            f.write(samples["technical"])

        print("Testing different backends with technical document...")

        # Test different backends
        backends = ["auto", "weasyprint", "pandoc"]
        results = {}

        for backend in backends:
            try:
                print(f"\nTesting {backend} backend...")

                converter = EnhancedMarkdownConverter()
                output_path = temp_dir / f"technical_{backend}.pdf"

                import time

                start_time = time.time()

                success = converter.convert_file_to_pdf(
                    input_path=str(tech_md_path),
                    output_path=str(output_path),
                    method=backend,
                )

                end_time = time.time()
                conversion_time = end_time - start_time

                if success:
                    file_size = (
                        output_path.stat().st_size if output_path.exists() else 0
                    )
                    print(
                        f"  ✅ {backend}: Success in {conversion_time:.2f}s, {file_size} bytes"
                    )
                    results[backend] = {
                        "success": True,
                        "time": conversion_time,
                        "size": file_size,
                        "output": str(output_path),
                    }
                else:
                    print(f"  ❌ {backend}: Failed")
                    results[backend] = {"success": False, "time": conversion_time}

            except Exception as e:
                print(f"  ❌ {backend}: Error - {str(e)}")
                results[backend] = {"success": False, "error": str(e)}

        # Summary
        print("\n" + "-" * 40)
        print("BACKEND COMPARISON SUMMARY")
        print("-" * 40)
        successful_backends = [b for b, r in results.items() if r.get("success", False)]
        print(f"Successful backends: {successful_backends}")

        if successful_backends:
            fastest = min(successful_backends, key=lambda b: results[b]["time"])
            print(f"Fastest backend: {fastest} ({results[fastest]['time']:.2f}s)")

        return results, temp_dir

    except Exception as e:
        print(f"❌ Backend comparison demonstration failed: {str(e)}")
        return None, None


def demonstrate_custom_styling():
    """Demonstrate custom CSS styling and configuration"""
    print("\n" + "=" * 60)
    print("CUSTOM STYLING DEMONSTRATION")
    print("=" * 60)

    try:
        samples = create_sample_markdown_content()
        temp_dir = Path(tempfile.mkdtemp())

        # Create custom CSS
        custom_css = """
        body {
            font-family: 'Times New Roman', serif;
            font-size: 11pt;
            line-height: 1.4;
            color: #2c3e50;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }

        h1 {
            color: #c0392b;
            font-size: 2.2em;
            border-bottom: 3px solid #e74c3c;
            padding-bottom: 0.5em;
            margin-top: 2em;
        }

        h2 {
            color: #8e44ad;
            font-size: 1.6em;
            border-bottom: 2px solid #9b59b6;
            padding-bottom: 0.3em;
            margin-top: 1.5em;
        }

        h3 {
            color: #2980b9;
            font-size: 1.3em;
            margin-top: 1.2em;
        }

        code {
            background-color: #ecf0f1;
            color: #e74c3c;
            padding: 3px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }

        pre {
            background-color: #2c3e50;
            color: #ecf0f1;
            padding: 20px;
            border-radius: 8px;
            border-left: 5px solid #3498db;
            overflow-x: auto;
            font-size: 0.9em;
        }

        pre code {
            background-color: transparent;
            color: inherit;
            padding: 0;
        }

        blockquote {
            background-color: #f8f9fa;
            border-left: 5px solid #3498db;
            margin: 1em 0;
            padding: 15px 20px;
            font-style: italic;
            color: #555;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            margin: 1.5em 0;
            background-color: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        th {
            background-color: #3498db;
            color: white;
            padding: 12px 15px;
            text-align: left;
            font-weight: bold;
        }

        td {
            padding: 10px 15px;
            border-bottom: 1px solid #ecf0f1;
        }

        tr:nth-child(even) {
            background-color: #f8f9fa;
        }

        tr:hover {
            background-color: #e8f4fd;
        }

        ul, ol {
            margin-bottom: 1em;
            padding-left: 2em;
        }

        li {
            margin-bottom: 0.5em;
            line-height: 1.6;
        }

        a {
            color: #3498db;
            text-decoration: none;
            border-bottom: 1px dotted #3498db;
        }

        a:hover {
            color: #2980b9;
            border-bottom: 1px solid #2980b9;
        }

        .toc {
            background-color: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            margin: 2em 0;
        }

        .toc h2 {
            color: #2c3e50;
            margin-top: 0;
            border-bottom: none;
        }

        .toc ul {
            list-style-type: none;
            padding-left: 0;
        }

        .toc li {
            margin-bottom: 0.8em;
        }

        .toc a {
            color: #2c3e50;
            font-weight: 500;
            border-bottom: none;
        }
        """

        # Create custom configuration
        config = MarkdownConfig(
            page_size="A4",
            margin="0.8in",
            font_size="11pt",
            line_height="1.4",
            include_toc=True,
            syntax_highlighting=True,
            custom_css=custom_css,
        )

        converter = EnhancedMarkdownConverter(config)

        # Convert academic sample with custom styling
        academic_md_path = temp_dir / "academic_styled.md"
        with open(academic_md_path, "w", encoding="utf-8") as f:
            f.write(samples["academic"])

        print("Converting academic paper with custom styling...")
        print("Custom styling features:")
        print("  - Custom color scheme (reds, purples, blues)")
        print("  - Times New Roman serif font")
        print("  - Enhanced table styling with hover effects")
        print("  - Styled code blocks with dark theme")
        print("  - Custom blockquote styling")
        print("  - Professional header styling")

        success = converter.convert_file_to_pdf(
            input_path=str(academic_md_path),
            output_path=str(temp_dir / "academic_styled.pdf"),
            method="weasyprint",  # WeasyPrint is best for custom CSS
        )

        if success:
            print("✅ Custom styling conversion successful!")
            print(f"   Output: {temp_dir / 'academic_styled.pdf'}")

            # Also create a default version for comparison
            default_converter = EnhancedMarkdownConverter()
            default_success = default_converter.convert_file_to_pdf(
                input_path=str(academic_md_path),
                output_path=str(temp_dir / "academic_default.pdf"),
                method="weasyprint",
            )

            if default_success:
                print(f"   Comparison (default): {temp_dir / 'academic_default.pdf'}")
        else:
            print("❌ Custom styling conversion failed")

        return success, temp_dir

    except Exception as e:
        print(f"❌ Custom styling demonstration failed: {str(e)}")
        return False, None


def demonstrate_content_conversion():
    """Demonstrate converting markdown content directly (not from file)"""
    print("\n" + "=" * 60)
    print("CONTENT CONVERSION DEMONSTRATION")
    print("=" * 60)

    try:
        # Create markdown content programmatically
        dynamic_content = f"""# Dynamic Content Example

## Generated Information
This document was generated programmatically on {Path(__file__).name}.

## System Information
- **Python Path**: {sys.executable}
- **Script Location**: {Path(__file__).absolute()}
- **Working Directory**: {Path.cwd()}

## Dynamic Table
| Property | Value |
|----------|-------|
| Script Name | {Path(__file__).name} |
| Python Version | {sys.version.split()[0]} |
| Platform | {sys.platform} |

## Code Example
```python
# This content was generated dynamically
import sys
from pathlib import Path

def generate_report():
    return f"Report generated from {{Path(__file__).name}}"

print(generate_report())
```

## Features Demonstrated
This example shows how to:
1. Generate markdown content programmatically
2. Convert content directly without saving to file first
3. Include dynamic information in documents
4. Use different conversion methods

> **Note**: This content was created in memory and converted directly to PDF
> without intermediate file storage.

## Conclusion
Direct content conversion is useful for:
- Dynamic report generation
- Programmatic document creation
- API-based document services
- Real-time content processing
"""

        temp_dir = Path(tempfile.mkdtemp())
        converter = EnhancedMarkdownConverter()

        print("Converting dynamically generated markdown content...")
        print("Content includes:")
        print("  - System information")
        print("  - Dynamic tables with current values")
        print("  - Generated timestamps")
        print("  - Programmatic examples")

        # Convert content directly to PDF
        output_path = temp_dir / "dynamic_content.pdf"

        success = converter.convert_markdown_to_pdf(
            markdown_content=dynamic_content,
            output_path=str(output_path),
            method="auto",
        )

        if success:
            print("✅ Content conversion successful!")
            print(f"   Output: {output_path}")

            # Show file size
            file_size = output_path.stat().st_size
            print(f"   Generated PDF size: {file_size} bytes")
        else:
            print("❌ Content conversion failed")

        return success, temp_dir

    except Exception as e:
        print(f"❌ Content conversion demonstration failed: {str(e)}")
        return False, None


def demonstrate_error_handling():
    """Demonstrate error handling and fallback mechanisms"""
    print("\n" + "=" * 60)
    print("ERROR HANDLING DEMONSTRATION")
    print("=" * 60)

    try:
        temp_dir = Path(tempfile.mkdtemp())

        # Test cases with various issues
        test_cases = {
            "invalid_markdown": """# Invalid Markdown

This markdown has some {{invalid}} syntax and [broken links](http://nonexistent.invalid).

```unknown_language
This code block uses an unknown language
```

![Missing Image](nonexistent_image.png)
""",
            "complex_content": """# Complex Content Test

## Mathematical Expressions
This tests content that might be challenging for some backends:

$$ E = mc^2 $$

$$\\sum_{i=1}^{n} x_i = \\frac{n(n+1)}{2}$$

## Complex Tables
| A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| Very long content that might wrap | Short | Medium length content | X | Y | Z | End |
| Another row with different lengths | A | B | C | D | E | F |

## Special Characters
Unicode: α, β, γ, δ, ε, ζ, η, θ, ι, κ, λ, μ, ν, ξ, ο, π, ρ, σ, τ, υ, φ, χ, ψ, ω
Symbols: ♠ ♣ ♥ ♦ ☀ ☁ ☂ ☃ ☄ ★ ☆ ☉ ☊ ☋ ☌ ☍ ☎ ☏
Arrows: ← ↑ → ↓ ↔ ↕ ↖ ↗ ↘ ↙
""",
            "empty_content": "",
            "minimal_content": "# Just a title",
        }

        print("Testing error handling with various content types...")

        results = {}

        for test_name, content in test_cases.items():
            print(f"\nTesting: {test_name}")

            try:
                # Try multiple backends for each test case
                for backend in ["auto", "weasyprint", "pandoc"]:
                    try:
                        converter = EnhancedMarkdownConverter()
                        output_path = temp_dir / f"{test_name}_{backend}.pdf"

                        success = converter.convert_markdown_to_pdf(
                            markdown_content=content,
                            output_path=str(output_path),
                            method=backend,
                        )

                        if success:
                            file_size = (
                                output_path.stat().st_size
                                if output_path.exists()
                                else 0
                            )
                            print(f"  ✅ {backend}: Success ({file_size} bytes)")
                            results[f"{test_name}_{backend}"] = {
                                "success": True,
                                "size": file_size,
                            }
                        else:
                            print(f"  ❌ {backend}: Failed")
                            results[f"{test_name}_{backend}"] = {"success": False}

                    except Exception as e:
                        print(f"  ❌ {backend}: Error - {str(e)[:60]}...")
                        results[f"{test_name}_{backend}"] = {
                            "success": False,
                            "error": str(e),
                        }

            except Exception as e:
                print(f"  ❌ Test case failed: {str(e)}")

        # Demonstrate robust conversion with fallbacks
        print("\nDemonstrating robust conversion with fallback logic...")

        def robust_convert(content, output_path):
            """Convert with multiple backend fallbacks"""
            backends = ["weasyprint", "pandoc", "auto"]

            for backend in backends:
                try:
                    converter = EnhancedMarkdownConverter()
                    success = converter.convert_markdown_to_pdf(
                        markdown_content=content,
                        output_path=output_path,
                        method=backend,
                    )
                    if success:
                        return backend, True
                except Exception:
                    continue

            return None, False

        # Test robust conversion
        test_content = test_cases["complex_content"]
        robust_output = temp_dir / "robust_conversion.pdf"

        successful_backend, success = robust_convert(test_content, str(robust_output))

        if success:
            print(f"✅ Robust conversion successful using {successful_backend}")
            print(f"   Output: {robust_output}")
        else:
            print("❌ All backends failed for robust conversion")

        # Summary
        print("\n" + "-" * 40)
        print("ERROR HANDLING SUMMARY")
        print("-" * 40)
        successful_conversions = sum(
            1 for r in results.values() if r.get("success", False)
        )
        total_attempts = len(results)
        success_rate = (
            (successful_conversions / total_attempts * 100) if total_attempts > 0 else 0
        )

        print(f"Total conversion attempts: {total_attempts}")
        print(f"Successful conversions: {successful_conversions}")
        print(f"Success rate: {success_rate:.1f}%")

        return results, temp_dir

    except Exception as e:
        print(f"❌ Error handling demonstration failed: {str(e)}")
        return None, None


def main():
    """Main demonstration function"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("RAG-Anything Enhanced Markdown Conversion Demonstration")
    print("=" * 70)
    print(
        "This example demonstrates various enhanced markdown conversion capabilities:"
    )
    print("  - Basic markdown to PDF conversion")
    print("  - Multiple backend comparison (WeasyPrint vs Pandoc)")
    print("  - Custom CSS styling and professional formatting")
    print("  - Direct content conversion without file I/O")
    print("  - Comprehensive error handling and fallback mechanisms")

    results = {}

    # Run demonstrations
    print("\n🚀 Starting demonstrations...")

    # Basic conversion
    success, temp_dir = demonstrate_basic_conversion()
    results["basic"] = success

    # Backend comparison
    backend_results, _ = demonstrate_backend_comparison()
    results["backends"] = backend_results

    # Custom styling
    styling_success, _ = demonstrate_custom_styling()
    results["styling"] = styling_success

    # Content conversion
    content_success, _ = demonstrate_content_conversion()
    results["content"] = content_success

    # Error handling
    error_results, _ = demonstrate_error_handling()
    results["error_handling"] = error_results

    # Summary
    print("\n" + "=" * 70)
    print("DEMONSTRATION SUMMARY")
    print("=" * 70)

    print("✅ Features Successfully Demonstrated:")
    if results["basic"]:
        print("  - Basic markdown to PDF conversion")
    if results["backends"]:
        successful_backends = [
            b for b, r in results["backends"].items() if r.get("success", False)
        ]
        print(f"  - Multiple backends: {successful_backends}")
    if results["styling"]:
        print("  - Custom CSS styling and professional formatting")
    if results["content"]:
        print("  - Direct content conversion without file I/O")
    if results["error_handling"]:
        success_rate = (
            sum(
                1 for r in results["error_handling"].values() if r.get("success", False)
            )
            / len(results["error_handling"])
            * 100
        )
        print(f"  - Error handling with {success_rate:.1f}% overall success rate")

    print("\n📊 Key Capabilities Highlighted:")
    print("  - Professional PDF generation with high-quality typography")
    print("  - Multiple conversion backends with automatic selection")
    print("  - Extensive CSS customization for branded documents")
    print("  - Syntax highlighting for code blocks using Pygments")
    print("  - Table formatting with professional styling")
    print("  - Image embedding with proper scaling")
    print("  - Table of contents generation with navigation")
    print("  - Comprehensive error handling and fallback mechanisms")

    print("\n💡 Best Practices Demonstrated:")
    print("  - Choose WeasyPrint for web-style documents and custom CSS")
    print("  - Choose Pandoc for academic papers and complex formatting")
    print("  - Use 'auto' method for general-purpose conversion")
    print("  - Implement fallback logic for robust conversion")
    print("  - Optimize images before embedding in documents")
    print("  - Test custom CSS with simple content first")
    print("  - Handle errors gracefully with multiple backend attempts")
    print("  - Use appropriate page sizes and margins for target use case")

    print("\n🎯 Integration Patterns:")
    print("  - Standalone conversion for document generation")
    print("  - Integration with RAG-Anything document pipeline")
    print("  - API-based document services")
    print("  - Batch processing for multiple documents")
    print("  - Dynamic content generation from templates")


if __name__ == "__main__":
    main()
