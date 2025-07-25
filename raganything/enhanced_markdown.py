"""
Enhanced Markdown to PDF Conversion

This module provides improved Markdown to PDF conversion with:
- Better formatting and styling
- Image support
- Table support
- Code syntax highlighting
- Custom templates
- Multiple output formats
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
import tempfile
import subprocess

try:
    import markdown

    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from weasyprint import HTML

    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

try:
    # Check if pandoc module exists (not used directly, just for detection)
    import importlib.util

    spec = importlib.util.find_spec("pandoc")
    PANDOC_AVAILABLE = spec is not None
except ImportError:
    PANDOC_AVAILABLE = False


@dataclass
class MarkdownConfig:
    """Configuration for Markdown to PDF conversion"""

    # Styling options
    css_file: Optional[str] = None
    template_file: Optional[str] = None
    page_size: str = "A4"
    margin: str = "1in"
    font_size: str = "12pt"
    line_height: str = "1.5"

    # Content options
    include_toc: bool = True
    syntax_highlighting: bool = True
    image_max_width: str = "100%"
    table_style: str = "border-collapse: collapse; width: 100%;"

    # Output options
    output_format: str = "pdf"  # pdf, html, docx
    output_dir: Optional[str] = None

    # Advanced options
    custom_css: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None


class EnhancedMarkdownConverter:
    """
    Enhanced Markdown to PDF converter with multiple backends

    Supports multiple conversion methods:
    - WeasyPrint (recommended for HTML/CSS styling)
    - Pandoc (recommended for complex documents)
    - ReportLab (fallback, basic styling)
    """

    def __init__(self, config: Optional[MarkdownConfig] = None):
        """
        Initialize the converter

        Args:
            config: Configuration for conversion
        """
        self.config = config or MarkdownConfig()
        self.logger = logging.getLogger(__name__)

        # Check available backends
        self.available_backends = self._check_backends()
        self.logger.info(f"Available backends: {list(self.available_backends.keys())}")

    def _check_backends(self) -> Dict[str, bool]:
        """Check which conversion backends are available"""
        backends = {
            "weasyprint": WEASYPRINT_AVAILABLE,
            "pandoc": PANDOC_AVAILABLE,
            "markdown": MARKDOWN_AVAILABLE,
        }

        # Check if pandoc is installed on system
        try:
            subprocess.run(["pandoc", "--version"], capture_output=True, check=True)
            backends["pandoc_system"] = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            backends["pandoc_system"] = False

        return backends

    def _get_default_css(self) -> str:
        """Get default CSS styling"""
        return """
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }

        h1, h2, h3, h4, h5, h6 {
            color: #2c3e50;
            margin-top: 1.5em;
            margin-bottom: 0.5em;
        }

        h1 { font-size: 2em; border-bottom: 2px solid #3498db; padding-bottom: 0.3em; }
        h2 { font-size: 1.5em; border-bottom: 1px solid #bdc3c7; padding-bottom: 0.2em; }
        h3 { font-size: 1.3em; }
        h4 { font-size: 1.1em; }

        p { margin-bottom: 1em; }

        code {
            background-color: #f8f9fa;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }

        pre {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border-left: 4px solid #3498db;
        }

        pre code {
            background-color: transparent;
            padding: 0;
        }

        blockquote {
            border-left: 4px solid #3498db;
            margin: 0;
            padding-left: 20px;
            color: #7f8c8d;
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

        img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 1em auto;
        }

        ul, ol {
            margin-bottom: 1em;
        }

        li {
            margin-bottom: 0.5em;
        }

        a {
            color: #3498db;
            text-decoration: none;
        }

        a:hover {
            text-decoration: underline;
        }

        .toc {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 2em;
        }

        .toc ul {
            list-style-type: none;
            padding-left: 0;
        }

        .toc li {
            margin-bottom: 0.3em;
        }

        .toc a {
            color: #2c3e50;
        }
        """

    def _process_markdown_content(self, content: str) -> str:
        """Process Markdown content with extensions"""
        if not MARKDOWN_AVAILABLE:
            raise RuntimeError(
                "Markdown library not available. Install with: pip install markdown"
            )

        # Configure Markdown extensions
        extensions = [
            "markdown.extensions.tables",
            "markdown.extensions.fenced_code",
            "markdown.extensions.codehilite",
            "markdown.extensions.toc",
            "markdown.extensions.attr_list",
            "markdown.extensions.def_list",
            "markdown.extensions.footnotes",
        ]

        extension_configs = {
            "codehilite": {
                "css_class": "highlight",
                "use_pygments": True,
            },
            "toc": {
                "title": "Table of Contents",
                "permalink": True,
            },
        }

        # Convert Markdown to HTML
        md = markdown.Markdown(
            extensions=extensions, extension_configs=extension_configs
        )

        html_content = md.convert(content)

        # Add CSS styling
        css = self.config.custom_css or self._get_default_css()

        # Create complete HTML document
        html_doc = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Converted Document</title>
            <style>
                {css}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        return html_doc

    def convert_with_weasyprint(self, markdown_content: str, output_path: str) -> bool:
        """Convert using WeasyPrint (best for styling)"""
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError(
                "WeasyPrint not available. Install with: pip install weasyprint"
            )

        try:
            # Process Markdown to HTML
            html_content = self._process_markdown_content(markdown_content)

            # Convert HTML to PDF
            html = HTML(string=html_content)
            html.write_pdf(output_path)

            self.logger.info(
                f"Successfully converted to PDF using WeasyPrint: {output_path}"
            )
            return True

        except Exception as e:
            self.logger.error(f"WeasyPrint conversion failed: {str(e)}")
            return False

    def convert_with_pandoc(
        self, markdown_content: str, output_path: str, use_system_pandoc: bool = False
    ) -> bool:
        """Convert using Pandoc (best for complex documents)"""
        if (
            not self.available_backends.get("pandoc_system", False)
            and not use_system_pandoc
        ):
            raise RuntimeError(
                "Pandoc not available. Install from: https://pandoc.org/installing.html"
            )

        try:
            import subprocess

            # Create temporary markdown file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False
            ) as temp_file:
                temp_file.write(markdown_content)
                temp_md_path = temp_file.name

            # Build pandoc command with wkhtmltopdf engine
            cmd = [
                "pandoc",
                temp_md_path,
                "-o",
                output_path,
                "--pdf-engine=wkhtmltopdf",
                "--standalone",
                "--toc",
                "--number-sections",
            ]

            # Run pandoc
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            # Clean up temp file
            os.unlink(temp_md_path)

            if result.returncode == 0:
                self.logger.info(
                    f"Successfully converted to PDF using Pandoc: {output_path}"
                )
                return True
            else:
                self.logger.error(f"Pandoc conversion failed: {result.stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Pandoc conversion failed: {str(e)}")
            return False

    def convert_markdown_to_pdf(
        self, markdown_content: str, output_path: str, method: str = "auto"
    ) -> bool:
        """
        Convert markdown content to PDF

        Args:
            markdown_content: Markdown content to convert
            output_path: Output PDF file path
            method: Conversion method ("auto", "weasyprint", "pandoc", "pandoc_system")

        Returns:
            True if conversion successful, False otherwise
        """
        if method == "auto":
            method = self._get_recommended_backend()

        try:
            if method == "weasyprint":
                return self.convert_with_weasyprint(markdown_content, output_path)
            elif method == "pandoc":
                return self.convert_with_pandoc(markdown_content, output_path)
            elif method == "pandoc_system":
                return self.convert_with_pandoc(
                    markdown_content, output_path, use_system_pandoc=True
                )
            else:
                raise ValueError(f"Unknown conversion method: {method}")

        except Exception as e:
            self.logger.error(f"{method.title()} conversion failed: {str(e)}")
            return False

    def convert_file_to_pdf(
        self, input_path: str, output_path: Optional[str] = None, method: str = "auto"
    ) -> bool:
        """
        Convert Markdown file to PDF

        Args:
            input_path: Input Markdown file path
            output_path: Output PDF file path (optional)
            method: Conversion method

        Returns:
            bool: True if conversion successful
        """
        input_path_obj = Path(input_path)

        if not input_path_obj.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # Read markdown content
        try:
            with open(input_path_obj, "r", encoding="utf-8") as f:
                markdown_content = f.read()
        except UnicodeDecodeError:
            # Try with different encodings
            for encoding in ["gbk", "latin-1", "cp1252"]:
                try:
                    with open(input_path_obj, "r", encoding=encoding) as f:
                        markdown_content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise RuntimeError(
                    f"Could not decode file {input_path} with any supported encoding"
                )

        # Determine output path
        if output_path is None:
            output_path = str(input_path_obj.with_suffix(".pdf"))

        return self.convert_markdown_to_pdf(markdown_content, output_path, method)

    def get_backend_info(self) -> Dict[str, Any]:
        """Get information about available backends"""
        return {
            "available_backends": self.available_backends,
            "recommended_backend": self._get_recommended_backend(),
            "config": {
                "page_size": self.config.page_size,
                "margin": self.config.margin,
                "font_size": self.config.font_size,
                "include_toc": self.config.include_toc,
                "syntax_highlighting": self.config.syntax_highlighting,
            },
        }

    def _get_recommended_backend(self) -> str:
        """Get recommended backend based on availability"""
        if self.available_backends.get("pandoc_system", False):
            return "pandoc"
        elif self.available_backends.get("weasyprint", False):
            return "weasyprint"
        else:
            return "none"


def main():
    """Command-line interface for enhanced markdown conversion"""
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced Markdown to PDF conversion")
    parser.add_argument("input", nargs="?", help="Input markdown file")
    parser.add_argument("--output", "-o", help="Output PDF file")
    parser.add_argument(
        "--method",
        choices=["auto", "weasyprint", "pandoc", "pandoc_system"],
        default="auto",
        help="Conversion method",
    )
    parser.add_argument("--css", help="Custom CSS file")
    parser.add_argument("--info", action="store_true", help="Show backend information")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create converter
    config = MarkdownConfig()
    if args.css:
        config.css_file = args.css

    converter = EnhancedMarkdownConverter(config)

    # Show backend info if requested
    if args.info:
        info = converter.get_backend_info()
        print("Backend Information:")
        for backend, available in info["available_backends"].items():
            status = "✅" if available else "❌"
            print(f"  {status} {backend}")
        print(f"Recommended backend: {info['recommended_backend']}")
        return 0

    # Check if input file is provided
    if not args.input:
        parser.error("Input file is required when not using --info")

    # Convert file
    try:
        success = converter.convert_file_to_pdf(
            input_path=args.input, output_path=args.output, method=args.method
        )

        if success:
            print(f"✅ Successfully converted {args.input} to PDF")
            return 0
        else:
            print("❌ Conversion failed")
            return 1

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return 1


if __name__ == "__main__":
    exit(main())
