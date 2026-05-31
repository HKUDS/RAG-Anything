# Enhanced Markdown Conversion

This document describes the enhanced markdown conversion feature for RAG-Anything, which provides high-quality PDF generation from markdown files with multiple backend options and advanced styling.

## Overview

The enhanced markdown conversion feature provides professional-quality PDF generation from markdown files. It supports multiple conversion backends, advanced styling options, syntax highlighting, and seamless integration with RAG-Anything's document processing pipeline.

## Key Features

- **Multiple Backends**: WeasyPrint, Pandoc, and automatic backend selection
- **Advanced Styling**: Custom CSS, syntax highlighting, and professional layouts
- **Image Support**: Embedded images with proper scaling and positioning
- **Table Support**: Formatted tables with borders and professional styling
- **Code Highlighting**: Syntax highlighting for code blocks using Pygments
- **Custom Templates**: Support for custom CSS and document templates
- **Table of Contents**: Automatic TOC generation with navigation links
- **Professional Typography**: High-quality fonts and spacing

## Installation

### Required Dependencies

```bash
# Basic installation
pip install raganything[all]

# Required for enhanced markdown conversion
pip install markdown weasyprint pygments
```

### Optional Dependencies

```bash
# For Pandoc backend (system installation required)
# Ubuntu/Debian:
sudo apt-get install pandoc wkhtmltopdf

# macOS:
brew install pandoc wkhtmltopdf

# Or using conda:
conda install -c conda-forge pandoc wkhtmltopdf
```

### Backend-Specific Installation

#### WeasyPrint (Recommended)
```bash
# Install WeasyPrint with system dependencies
pip install weasyprint

# Ubuntu/Debian system dependencies:
sudo apt-get install -y build-essential python3-dev python3-pip \
    python3-setuptools python3-wheel python3-cffi libcairo2 \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev shared-mime-info
```

#### Pandoc
- Download from: https://pandoc.org/installing.html
- Requires system-wide installation
- Used for complex document structures and LaTeX-quality output

## Usage

### Basic Conversion

```python
from raganything.enhanced_markdown import EnhancedMarkdownConverter, MarkdownConfig

# Create converter with default settings
converter = EnhancedMarkdownConverter()

# Convert markdown file to PDF
success = converter.convert_file_to_pdf(
    input_path="document.md",
    output_path="document.pdf",
    method="auto"  # Automatically select best available backend
)

if success:
    print("✅ Conversion successful!")
else:
    print("❌ Conversion failed")
```

### Advanced Configuration

```python
# Create custom configuration
config = MarkdownConfig(
    page_size="A4",           # A4, Letter, Legal, etc.
    margin="1in",             # CSS-style margins
    font_size="12pt",         # Base font size
    line_height="1.5",        # Line spacing
    include_toc=True,         # Generate table of contents
    syntax_highlighting=True, # Enable code syntax highlighting

    # Custom CSS styling
    custom_css="""
    body {
        font-family: 'Georgia', serif;
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
    }
    pre {
        background-color: #f8f9fa;
        border-left: 4px solid #3498db;
        padding: 15px;
        border-radius: 5px;
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
    """
)

converter = EnhancedMarkdownConverter(config)
```

### Backend Selection

```python
# Check available backends
converter = EnhancedMarkdownConverter()
backend_info = converter.get_backend_info()

print("Available backends:")
for backend, available in backend_info["available_backends"].items():
    status = "✅" if available else "❌"
    print(f"  {status} {backend}")

print(f"Recommended backend: {backend_info['recommended_backend']}")

# Use specific backend
converter.convert_file_to_pdf(
    input_path="document.md",
    output_path="document.pdf",
    method="weasyprint"  # or "pandoc", "pandoc_system", "auto"
)
```

### Content Conversion

```python
# Convert markdown content directly (not from file)
markdown_content = """
# Sample Document

## Introduction
This is a **bold** statement with *italic* text.

## Code Example
```python
def hello_world():
    print("Hello, World!")
    return "Success"
```

## Table
| Feature | Status | Notes |
|---------|--------|-------|
| PDF Generation | ✅ | Working |
| Syntax Highlighting | ✅ | Pygments |
| Custom CSS | ✅ | Full support |
"""

success = converter.convert_markdown_to_pdf(
    markdown_content=markdown_content,
    output_path="sample.pdf",
    method="auto"
)
```

### Command Line Interface

```bash
# Basic conversion
python -m raganything.enhanced_markdown document.md --output document.pdf

# With specific backend
python -m raganything.enhanced_markdown document.md --method weasyprint

# With custom CSS file
python -m raganything.enhanced_markdown document.md --css custom_style.css

# Show backend information
python -m raganything.enhanced_markdown --info

# Help
python -m raganything.enhanced_markdown --help
```

## Backend Comparison

| Backend | Pros | Cons | Best For | Quality |
|---------|------|------|----------|---------|
| **WeasyPrint** | • Excellent CSS support<br>• Fast rendering<br>• Great web-style layouts<br>• Python-based | • Limited LaTeX features<br>• Requires system deps | • Web-style documents<br>• Custom styling<br>• Fast conversion | ⭐⭐⭐⭐ |
| **Pandoc** | • Extensive features<br>• LaTeX-quality output<br>• Academic formatting<br>• Many input/output formats | • Slower conversion<br>• System installation<br>• Complex setup | • Academic papers<br>• Complex documents<br>• Publication quality | ⭐⭐⭐⭐⭐ |
| **Auto** | • Automatic selection<br>• Fallback support<br>• User-friendly | • May not use optimal backend | • General use<br>• Quick setup<br>• Development | ⭐⭐⭐⭐ |

## Configuration Options

### MarkdownConfig Parameters

```python
@dataclass
class MarkdownConfig:
    # Page layout
    page_size: str = "A4"              # A4, Letter, Legal, A3, etc.
    margin: str = "1in"                # CSS margin format
    font_size: str = "12pt"            # Base font size
    line_height: str = "1.5"           # Line spacing multiplier

    # Content options
    include_toc: bool = True           # Generate table of contents
    syntax_highlighting: bool = True   # Enable code highlighting
    image_max_width: str = "100%"      # Maximum image width
    table_style: str = "..."           # Default table CSS

    # Styling
    css_file: Optional[str] = None     # External CSS file path
    custom_css: Optional[str] = None   # Inline CSS content
    template_file: Optional[str] = None # Custom HTML template

    # Output options
    output_format: str = "pdf"         # Currently only PDF supported
    output_dir: Optional[str] = None   # Output directory

    # Metadata
    metadata: Optional[Dict[str, str]] = None  # Document metadata
```

### Supported Markdown Features

#### Basic Formatting
- **Headers**: `# ## ### #### ##### ######`
- **Emphasis**: `*italic*`, `**bold**`, `***bold italic***`
- **Links**: `[text](url)`, `[text][ref]`
- **Images**: `![alt](url)`, `![alt][ref]`
- **Lists**: Ordered and unordered, nested
- **Blockquotes**: `> quote`
- **Line breaks**: Double space or `\n\n`

#### Advanced Features
- **Tables**: GitHub-style tables with alignment
- **Code blocks**: Fenced code blocks with language specification
- **Inline code**: `backtick code`
- **Horizontal rules**: `---` or `***`
- **Footnotes**: `[^1]` references
- **Definition lists**: Term and definition pairs
- **Attributes**: `{#id .class key=value}`

#### Code Highlighting

```markdown
```python
def example_function():
    """This will be syntax highlighted"""
    return "Hello, World!"
```

```javascript
function exampleFunction() {
    // This will also be highlighted
    return "Hello, World!";
}
```
```

## Integration with RAG-Anything

The enhanced markdown conversion integrates seamlessly with RAG-Anything:

```python
from raganything import RAGAnything

# Initialize RAG-Anything
rag = RAGAnything()

# Process markdown files - enhanced conversion is used automatically
await rag.process_document_complete("document.md")

# Batch processing with enhanced markdown conversion
result = rag.process_documents_batch(
    file_paths=["doc1.md", "doc2.md", "doc3.md"],
    output_dir="./output"
)

# The .md files will be converted to PDF using enhanced conversion
# before being processed by the RAG system
```

## Performance Considerations

### Conversion Speed
- **WeasyPrint**: ~1-3 seconds for typical documents
- **Pandoc**: ~3-10 seconds for typical documents
- **Large documents**: Time scales roughly linearly with content

### Memory Usage
- **WeasyPrint**: ~50-100MB per conversion
- **Pandoc**: ~100-200MB per conversion
- **Images**: Large images increase memory usage significan'tly

### Optimization Tips
1. **Resize large images** before embedding
2. **Use compressed images** (JPEG for photos, PNG for graphics)
3. **Limit concurrent conversions** to avoid memory issues
4. **Cache converted content** when processing multiple times

## Examples

### Sample Markdown Document

```markdown
# Technical Documentation

## Table of Contents
[TOC]

## Overview
This document provides comprehensive technical specifications.

## Architecture

### System Components
1. **Parser Engine**: Handles document processing
2. **Storage Layer**: Manages data persistence
3. **Query Interface**: Provides search capabilities

### Code Implementation
```python
from raganything import RAGAnything

# Initialize system
rag = RAGAnything(config={
    "working_dir": "./storage",
    "enable_image_processing": True
})

# Process document
await rag.process_document_complete("document.pdf")
```

### Performance Metrics

| Component | Throughput | Latency | Memory |
|-----------|------------|---------|--------|
| Parser | 100 docs/hour | 36s avg | 2.5 GB |
| Storage | 1000 ops/sec | 1ms avg | 512 MB |
| Query | 50 queries/sec | 20ms avg | 1 GB |

## Integration Notes

> **Important**: Always validate input before processing.

## Conclusion
The enhanced system provides excellent performance for document processing workflows.
```

### Generated PDF Features

The enhanced markdown converter produces PDFs with:

- **Professional typography** with proper font selection and spacing
- **Syntax-highlighted code blocks** using Pygments
- **Formatted tables** with borders and alternating row colors
- **Clickable table of contents** with navigation links
- **Responsive images** that scale appropriately
- **Custom styling** through CSS
- **Proper page breaks** and margins
- **Document metadata** and properties

## Troubleshooting

### Common Issues

#### WeasyPrint Installation Problems
```bash
# Ubuntu/Debian: Install system dependencies
sudo apt-get update
sudo apt-get install -y build-essential python3-dev libcairo2 \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev shared-mime-info

# Then reinstall WeasyPrint
pip install --force-reinstall weasyprint
```

#### Pandoc Not Found
```bash
# Check if Pandoc is installed
pandoc --version

# Install Pandoc (Ubuntu/Debian)
sudo apt-get install pandoc wkhtmltopdf

# Or download from: https://pandoc.org/installing.html
```

#### CSS Issues
- Check CSS syntax in custom_css
- Verify CSS file paths exist
- Test CSS with simple HTML first
- Use browser developer tools to debug styling

#### Image Problems
- Ensure images are accessible (correct paths)
- Check image file formats (PNG, JPEG, GIF supported)
- Verify image file permissions
- Consider image size and format optimization

#### Font Issues
```python
# Use web-safe fonts
config = MarkdownConfig(
    custom_css="""
    body {
        font-family: 'Arial', 'Helvetica', sans-serif;
    }
    """
)
```

### Debug Mode

Enable detailed logging for troubleshooting:

```python
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create converter with debug logging
converter = EnhancedMarkdownConverter()
result = converter.convert_file_to_pdf("test.md", "test.pdf")
```

### Error Handling

```python
def robust_conversion(input_path, output_path):
    """Convert with fallback backends"""
    converter = EnhancedMarkdownConverter()

    # Try backends in order of preference
    backends = ["weasyprint", "pandoc", "auto"]

    for backend in backends:
        try:
            success = converter.convert_file_to_pdf(
                input_path=input_path,
                output_path=output_path,
                method=backend
            )
            if success:
                print(f"✅ Conversion successful with {backend}")
                return True
        except Exception as e:
            print(f"❌ {backend} failed: {str(e)}")
            continue

    print("❌ All backends failed")
    return False
```

## API Reference

### EnhancedMarkdownConverter

```python
class EnhancedMarkdownConverter:
    def __init__(self, config: Optional[MarkdownConfig] = None):
        """Initialize converter with optional configuration"""

    def convert_file_to_pdf(self, input_path: str, output_path: str, method: str = "auto") -> bool:
        """Convert markdown file to PDF"""

    def convert_markdown_to_pdf(self, markdown_content: str, output_path: str, method: str = "auto") -> bool:
        """Convert markdown content to PDF"""

    def get_backend_info(self) -> Dict[str, Any]:
        """Get information about available backends"""

    def convert_with_weasyprint(self, markdown_content: str, output_path: str) -> bool:
        """Convert using WeasyPrint backend"""

    def convert_with_pandoc(self, markdown_content: str, output_path: str) -> bool:
        """Convert using Pandoc backend"""
```

## Best Practices

1. **Choose the right backend** for your use case:
   - **WeasyPrint** for web-style documents and custom CSS
   - **Pandoc** for academic papers and complex formatting
   - **Auto** for general use and development

2. **Optimize images** before embedding:
   - Use appropriate formats (JPEG for photos, PNG for graphics)
   - Compress images to reduce file size
   - Set reasonable maximum widths

3. **Design responsive layouts**:
   - Use relative units (%, em) instead of absolute (px)
   - Test with different page sizes
   - Consider print-specific CSS

4. **Test your styling**:
   - Start with default styling and incrementally customize
   - Test with sample content before production use
   - Validate CSS syntax

5. **Handle errors gracefully**:
   - Implement fallback backends
   - Provide meaningful error messages
   - Log conversion attempts for debugging

6. **Performance optimization**:
   - Cache converted content when possible
   - Process large batches with appropriate worker counts
   - Monitor memory usage with large documents

## Conclusion

The enhanced markdown conversion feature provides professional-quality PDF generation with flexible styling options and multiple backend support. It seamlessly integrates with RAG-Anything's document processing pipeline while offering standalone functionality for markdown-to-PDF conversion needs.
