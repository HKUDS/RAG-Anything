# type: ignore
"""
Generic Document Parser Utility

This module provides functionality for parsing documents using the built-in
MinerU, Docling, and PaddleOCR parsers, and exposes a small registry for
**in-process** custom parsers (see :func:`register_parser`).

Important notes:

- The custom parser registry is primarily intended for Python usage, where your
  application imports a parser implementation and calls :func:`register_parser`
  before invoking RAGAnything APIs.
- The standalone CLI (``python -m raganything.parser`` or the installed console
  script) does **not** perform automatic plugin discovery; it will only see
  custom parsers that have already been registered in the current process
  (for example via a wrapper script or :mod:`sitecustomize`).

MinerU 2.0 no longer includes LibreOffice document conversion module.
For Office documents (.doc, .docx, .ppt, .pptx), please convert them to PDF
format first.
"""

from __future__ import annotations


import os
import platform
import hashlib
import json
import argparse
import base64
import hashlib
import subprocess
import tempfile
import threading
import logging
import os
import inspect
import re
import shutil
import zlib
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Union,
    Tuple,
    Any,
    Iterator,
)

from raganything.asset_urls import attach_public_media_urls

_IS_WINDOWS: bool = platform.system() == "Windows"


def _split_text_blocks(text: str) -> List[str]:
    """Split text into paragraph-like blocks for content_list."""
    if not text:
        return []
    parts = [p.strip() for p in str(text).split("\n\n") if p.strip()]
    return parts if parts else [str(text)]


class MineruExecutionError(Exception):
    """catch mineru error"""

    def __init__(self, return_code, error_msg):
        self.return_code = return_code
        self.error_msg = error_msg
        super().__init__(
            f"Mineru command failed with return code {return_code}: {error_msg}"
        )


class Parser:
    """
    Base class for document parsing utilities.

    Defines common functionality and constants for parsing different document types.
    """

    # Define common file formats
    OFFICE_FORMATS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
    IMAGE_FORMATS = {".png", ".jpeg", ".jpg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
    TEXT_FORMATS = {".txt", ".md"}

    # Class-level logger
    logger = logging.getLogger(__name__)

    @staticmethod
    def _is_url(path: str) -> bool:
        """Check if the path is a URL."""
        try:
            result = urllib.parse.urlparse(str(path))
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _download_file(self, url: str) -> Path:
        """
        Download a file from a URL to a temporary file.
        Attempts to preserve the file extension from the URL or Content-Type header.
        """
        tmp_path = None
        response = None
        try:
            self.logger.info(f"Downloading file from URL: {url}")

            # Parse URL to get path and extension
            parsed_url = urllib.parse.urlparse(url)
            path = Path(parsed_url.path)
            suffix = path.suffix if path.suffix else ""

            # Create request with User-Agent to avoid 403 Forbidden from some sites
            req = urllib.request.Request(
                url,
                data=None,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
                },
            )

            # Open connection to get headers (with an explicit timeout to prevent hanging)
            response = urllib.request.urlopen(req, timeout=30)

            # If no extension in URL, try Content-Type header
            if not suffix:
                content_type = (
                    response.headers.get("Content-Type", "").split(";")[0].strip()
                )
                if content_type:
                    import mimetypes

                    guessed_ext = mimetypes.guess_extension(content_type)
                    if guessed_ext:
                        suffix = guessed_ext
                        self.logger.info(
                            f"Inferred file extension '{suffix}' from Content-Type: {content_type}"
                        )

            # Create a temporary file with the correct extension
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            tmp_path = Path(tmp_path)

            # Download the file content
            with open(tmp_path, "wb") as out_file:
                shutil.copyfileobj(response, out_file)

            self.logger.info(
                f"Downloaded to temporary file: {tmp_path} ({tmp_path.stat().st_size} bytes)"
            )
            return tmp_path

        except Exception as e:
            # Clean up temp file if it was created
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                    self.logger.debug(
                        f"Cleaned up temporary file after failed download: {tmp_path}"
                    )
                except Exception as cleanup_error:
                    self.logger.warning(
                        f"Failed to clean up temp file {tmp_path}: {cleanup_error}"
                    )

            self.logger.error(f"Failed to download file from {url}: {e}")
            raise RuntimeError(f"Failed to download file from {url}: {e}")
        finally:
            if response:
                response.close()

    def __init__(self) -> None:
        """Initialize the base parser."""
        pass

    @staticmethod
    def _unique_output_dir(
        base_dir: Union[str, Path], file_path: Union[str, Path]
    ) -> Path:
        """Create a unique output subdirectory for a file to prevent same-name collisions.

        When multiple files share the same name (e.g. dir1/paper.pdf and dir2/paper.pdf),
        their parser output would collide in the same output directory. This creates a
        unique subdirectory by appending a short hash of the file's absolute path. (Fixes #51)

        Args:
            base_dir: The base output directory
            file_path: Path to the input file

        Returns:
            Path like base_dir/paper_a1b2c3d4/ unique per absolute file path.
        """
        file_path = Path(file_path).resolve()
        stem = file_path.stem
        path_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
        return Path(base_dir) / f"{stem}_{path_hash}"

    @classmethod
    def convert_office_to_pdf(
        cls, doc_path: Union[str, Path], output_dir: Optional[str] = None
    ) -> Path:
        """
        Convert Office document (.doc, .docx, .ppt, .pptx, .xls, .xlsx) to PDF.
        Requires LibreOffice to be installed.

        Args:
            doc_path: Path to the Office document file
            output_dir: Output directory for the PDF file

        Returns:
            Path to the generated PDF file
        """
        try:
            # Convert to Path object for easier handling
            doc_path = Path(doc_path)
            if not doc_path.exists():
                raise FileNotFoundError(f"Office document does not exist: {doc_path}")

            name_without_suff = doc_path.stem

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
            else:
                base_output_dir = doc_path.parent / "libreoffice_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            # Create temporary directory for PDF conversion
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Convert to PDF using LibreOffice
                cls.logger.info(
                    f"Converting {doc_path.name} to PDF using LibreOffice..."
                )

                # Prepare subprocess parameters to hide console window on Windows
                # Try LibreOffice commands in order of preference
                commands_to_try = ["libreoffice", "soffice"]

                conversion_successful = False
                last_cmd = commands_to_try[-1]
                for cmd in commands_to_try:
                    is_last = cmd == last_cmd
                    try:
                        convert_cmd = [
                            cmd,
                            "--headless",
                            "--convert-to",
                            "pdf",
                            "--outdir",
                            str(temp_path),
                            str(doc_path),
                        ]

                        # Prepare conversion subprocess parameters
                        convert_subprocess_kwargs = {
                            "capture_output": True,
                            "text": True,
                            "timeout": 60,  # 60 second timeout
                            "encoding": "utf-8",
                            "errors": "ignore",
                        }

                        # Hide console window on Windows
                        if _IS_WINDOWS:
                            convert_subprocess_kwargs["creationflags"] = (
                                subprocess.CREATE_NO_WINDOW
                            )

                        result = subprocess.run(
                            convert_cmd, **convert_subprocess_kwargs
                        )

                        if result.returncode == 0:
                            conversion_successful = True
                            cls.logger.info(
                                f"Successfully converted {doc_path.name} to PDF using {cmd}"
                            )
                            break
                        else:
                            cls.logger.warning(
                                f"LibreOffice command '{cmd}' failed: {result.stderr}"
                            )
                    except FileNotFoundError:
                        # Only warn when all candidates are exhausted; otherwise
                        # log at debug level so that the normal fallback from
                        # 'libreoffice' → 'soffice' does not surface a spurious
                        # WARNING to users whose system only has 'soffice'.
                        if is_last:
                            cls.logger.warning(f"LibreOffice command '{cmd}' not found")
                        else:
                            cls.logger.debug(
                                f"LibreOffice command '{cmd}' not found, "
                                f"trying next candidate"
                            )
                    except subprocess.TimeoutExpired:
                        cls.logger.warning(f"LibreOffice command '{cmd}' timed out")
                    except Exception as e:
                        cls.logger.error(
                            f"LibreOffice command '{cmd}' failed with exception: {e}"
                        )

                if not conversion_successful:
                    raise RuntimeError(
                        f"LibreOffice conversion failed for {doc_path.name}. "
                        f"Please ensure LibreOffice is installed:\n"
                        "- Windows: Download from https://www.libreoffice.org/download/download/\n"
                        "- macOS: brew install --cask libreoffice\n"
                        "- Ubuntu/Debian: sudo apt-get install libreoffice\n"
                        "- CentOS/RHEL: sudo yum install libreoffice\n"
                        "Alternatively, convert the document to PDF manually."
                    )

                # Find the generated PDF
                pdf_files = list(temp_path.glob("*.pdf"))
                if not pdf_files:
                    raise RuntimeError(
                        f"PDF conversion failed for {doc_path.name} - no PDF file generated. "
                        f"Please check LibreOffice installation or try manual conversion."
                    )

                pdf_path = pdf_files[0]
                cls.logger.info(
                    f"Generated PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes)"
                )

                # Validate the generated PDF
                if pdf_path.stat().st_size < 100:  # Very small file, likely empty
                    raise RuntimeError(
                        "Generated PDF appears to be empty or corrupted. "
                        "Original file may have issues or LibreOffice conversion failed."
                    )

                # Copy PDF to final output directory
                final_pdf_path = base_output_dir / f"{name_without_suff}.pdf"
                import shutil

                shutil.copy2(pdf_path, final_pdf_path)

                return final_pdf_path

        except Exception as e:
            cls.logger.error(f"Error in convert_office_to_pdf: {str(e)}")
            raise

    @classmethod
    def convert_text_to_pdf(
        cls, text_path: Union[str, Path], output_dir: Optional[str] = None
    ) -> Path:
        """
        Convert text file (.txt, .md) to PDF using ReportLab with full markdown support.

        Args:
            text_path: Path to the text file
            output_dir: Output directory for the PDF file

        Returns:
            Path to the generated PDF file
        """
        try:
            text_path = Path(text_path)
            if not text_path.exists():
                raise FileNotFoundError(f"Text file does not exist: {text_path}")

            # Supported text formats
            supported_text_formats = {".txt", ".md"}
            if text_path.suffix.lower() not in supported_text_formats:
                raise ValueError(f"Unsupported text format: {text_path.suffix}")

            # Read the text content
            try:
                with open(text_path, "r", encoding="utf-8") as f:
                    text_content = f.read()
            except UnicodeDecodeError:
                # Try with different encodings
                for encoding in ["gbk", "latin-1", "cp1252"]:
                    try:
                        with open(text_path, "r", encoding=encoding) as f:
                            text_content = f.read()
                        cls.logger.info(
                            f"Successfully read file with {encoding} encoding"
                        )
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    raise RuntimeError(
                        f"Could not decode text file {text_path.name} with any supported encoding"
                    )

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
            else:
                base_output_dir = text_path.parent / "reportlab_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = base_output_dir / f"{text_path.stem}.pdf"

            # Convert text to PDF
            cls.logger.info(f"Converting {text_path.name} to PDF...")

            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import inch
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont

                support_chinese = True
                try:
                    if "WenQuanYi" not in pdfmetrics.getRegisteredFontNames():
                        if not Path(
                            "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc"
                        ).exists():
                            support_chinese = False
                            cls.logger.warning(
                                "WenQuanYi font not found at /usr/share/fonts/wqy-microhei/wqy-microhei.ttc. Chinese characters may not render correctly."
                            )
                        else:
                            pdfmetrics.registerFont(
                                TTFont(
                                    "WenQuanYi",
                                    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
                                )
                            )
                except Exception as e:
                    support_chinese = False
                    cls.logger.warning(
                        f"Failed to register WenQuanYi font: {e}. Chinese characters may not render correctly."
                    )

                # Create PDF document
                doc = SimpleDocTemplate(
                    str(pdf_path),
                    pagesize=A4,
                    leftMargin=inch,
                    rightMargin=inch,
                    topMargin=inch,
                    bottomMargin=inch,
                )

                # Get styles
                styles = getSampleStyleSheet()
                normal_style = styles["Normal"]
                heading_style = styles["Heading1"]
                if support_chinese:
                    normal_style.fontName = "WenQuanYi"
                    heading_style.fontName = "WenQuanYi"

                # Try to register a font that supports Chinese characters
                # UnicodeCIDFont only supports specific CID font names:
                #   STSong-Light (Chinese), MSung-Light (Chinese Traditional),
                #   HeiseiMin-W3 / HeiseiKakuGo-W5 (Japanese),
                #   HYSMyeongJo-Medium (Korean)
                # System font names like "SimSun", "SimHei", "STHeiti" are
                # NOT valid CID names and silently fail (#24).
                try:
                    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

                    # STSong-Light is the standard CID font for Simplified
                    # Chinese and works cross-platform (reportlab ships the
                    # required CID resources internally).
                    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
                    if not support_chinese:
                        normal_style.fontName = "STSong-Light"
                        heading_style.fontName = "STSong-Light"
                except Exception:
                    pass  # Use default fonts if Chinese font setup fails

                # Build content
                story = []

                # Handle markdown or plain text
                if text_path.suffix.lower() == ".md":
                    # Handle markdown content - simplified implementation
                    lines = text_content.split("\n")
                    for line in lines:
                        line = line.strip()
                        if not line:
                            story.append(Spacer(1, 12))
                            continue

                        # Headers
                        if line.startswith("#"):
                            level = len(line) - len(line.lstrip("#"))
                            header_text = line.lstrip("#").strip()
                            if header_text:
                                header_style = ParagraphStyle(
                                    name=f"Heading{level}",
                                    parent=heading_style,
                                    fontSize=max(16 - level, 10),
                                    spaceAfter=8,
                                    spaceBefore=16 if level <= 2 else 12,
                                )
                                story.append(Paragraph(header_text, header_style))
                        else:
                            # Regular text
                            story.append(Paragraph(line, normal_style))
                            story.append(Spacer(1, 6))
                else:
                    # Handle plain text files (.txt)
                    cls.logger.info(
                        f"Processing plain text file with {len(text_content)} characters..."
                    )

                    # Split text into lines and process each line
                    lines = text_content.split("\n")
                    line_count = 0

                    for line in lines:
                        line = line.rstrip()
                        line_count += 1

                        # Empty lines
                        if not line.strip():
                            story.append(Spacer(1, 6))
                            continue

                        # Regular text lines
                        # Escape special characters for ReportLab
                        safe_line = (
                            line.replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                        )

                        # Create paragraph
                        story.append(Paragraph(safe_line, normal_style))
                        story.append(Spacer(1, 3))

                    cls.logger.info(f"Added {line_count} lines to PDF")

                    # If no content was added, add a placeholder
                    if not story:
                        story.append(Paragraph("(Empty text file)", normal_style))

                # Build PDF
                doc.build(story)
                cls.logger.info(
                    f"Successfully converted {text_path.name} to PDF ({pdf_path.stat().st_size / 1024:.1f} KB)"
                )

            except ImportError:
                raise RuntimeError(
                    "reportlab is required for text-to-PDF conversion. "
                    "Please install it using: pip install reportlab"
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to convert text file {text_path.name} to PDF: {str(e)}"
                )

            # Validate the generated PDF
            if not pdf_path.exists() or pdf_path.stat().st_size < 100:
                raise RuntimeError(
                    f"PDF conversion failed for {text_path.name} - generated PDF is empty or corrupted."
                )

            return pdf_path

        except Exception as e:
            cls.logger.error(f"Error in convert_text_to_pdf: {str(e)}")
            raise

    @classmethod
    def _process_inline_markdown(cls, text: str) -> str:
        """
        Process inline markdown formatting (bold, italic, code, links)

        Args:
            text: Raw text with markdown formatting

        Returns:
            Text with ReportLab markup
        """
        import re

        # Escape special characters for ReportLab
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Bold text: **text** or __text__
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.*?)__", r"<b>\1</b>", text)

        # Italic text: *text* or _text_ (but not in the middle of words)
        text = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

        # Inline code: `code`
        text = re.sub(
            r"`([^`]+?)`",
            r'<font name="Courier" size="9" color="darkred">\1</font>',
            text,
        )

        # Links: [text](url) - convert to text with URL annotation
        def link_replacer(match):
            link_text = match.group(1)
            url = match.group(2)
            return f'<link href="{url}" color="blue"><u>{link_text}</u></link>'

        text = re.sub(r"\[([^\]]+?)\]\(([^)]+?)\)", link_replacer, text)

        # Strikethrough: ~~text~~
        text = re.sub(r"~~(.*?)~~", r"<strike>\1</strike>", text)

        return text

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Abstract method to parse PDF document.
        Must be implemented by subclasses.

        Args:
            pdf_path: Path to the PDF file
            output_dir: Output directory path
            method: Parsing method (auto, txt, ocr)
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for parser-specific command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        raise NotImplementedError("parse_pdf must be implemented by subclasses")

    def parse_image(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Abstract method to parse image document.
        Must be implemented by subclasses.

        Note: Different parsers may support different image formats.
        Check the specific parser's documentation for supported formats.

        Args:
            image_path: Path to the image file
            output_dir: Output directory path
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for parser-specific command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        raise NotImplementedError("parse_image must be implemented by subclasses")

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Abstract method to parse a document.
        Must be implemented by subclasses.

        Args:
            file_path: Path to the file to be parsed
            method: Parsing method (auto, txt, ocr)
            output_dir: Output directory path
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for parser-specific command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        raise NotImplementedError("parse_document must be implemented by subclasses")

    def check_installation(self) -> bool:
        """
        Abstract method to check if the parser is properly installed.
        Must be implemented by subclasses.

        Returns:
            bool: True if installation is valid, False otherwise
        """
        raise NotImplementedError(
            "check_installation must be implemented by subclasses"
        )


class MineruParser(Parser):
    """
    MinerU 2.0 document parsing utility class

    Supports parsing PDF and image documents, converting the content into structured data
    and generating markdown and JSON output.

    Note: Office documents are no longer directly supported. Please convert them to PDF first.
    """

    __slots__ = ()

    # Class-level logger
    logger = logging.getLogger(__name__)

    def __init__(self) -> None:
        """Initialize MineruParser"""
        super().__init__()

    @classmethod
    def _run_mineru_command(
        cls,
        input_path: Union[str, Path],
        output_dir: Union[str, Path],
        method: str = "auto",
        lang: Optional[str] = None,
        backend: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
        formula: bool = True,
        table: bool = True,
        device: Optional[str] = None,
        source: Optional[str] = None,
        vlm_url: Optional[str] = None,
        timeout: Optional[int] = None,
        **kwargs,
    ) -> None:
        """
        Run mineru command line tool

        Args:
            input_path: Path to input file or directory
            output_dir: Output directory path
            method: Parsing method (auto, txt, ocr)
            lang: Document language for OCR optimization
            backend: Parsing backend
            start_page: Starting page number (0-based)
            end_page: Ending page number (0-based)
            formula: Enable formula parsing
            table: Enable table parsing
            device: Inference device
            source: Model source
            vlm_url: When the backend is `vlm-http-client`, you need to specify the server_url
            timeout: Maximum seconds to wait for MinerU to complete. None means no limit.
                     Raises TimeoutError if the process does not finish within this duration.
            **kwargs: Additional parameters for subprocess (e.g., env)
        """
        cmd = [
            "mineru",
            "-p",
            str(input_path),
            "-o",
            str(output_dir),
            "-m",
            method,
        ]

        if backend:
            cmd.extend(["-b", backend])
        if source:
            cmd.extend(["--source", source])
        if lang:
            cmd.extend(["-l", lang])
        if start_page is not None:
            cmd.extend(["-s", str(start_page)])
        if end_page is not None:
            cmd.extend(["-e", str(end_page)])
        if not formula:
            cmd.extend(["-f", "false"])
        if not table:
            cmd.extend(["-t", "false"])
        if device:
            cmd.extend(["-d", device])
        if vlm_url:
            cmd.extend(["-u", vlm_url])

        output_lines = []
        error_lines = []

        # Handle and validate environment variables
        custom_env = kwargs.pop("env", None)

        # Validate env if provided
        if custom_env is not None:
            if not isinstance(custom_env, dict):
                raise TypeError(
                    f"env must be a dictionary, got {type(custom_env).__name__}"
                )
            for k, v in custom_env.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise TypeError("env keys and values must be strings")

        # Check for unsupported arguments to fail fast
        if kwargs:
            unsupported = ", ".join(kwargs.keys())
            raise TypeError(
                f"MineruParser._run_mineru_command received unexpected keyword argument(s): {unsupported}"
            )

        try:
            # Prepare subprocess parameters to hide console window on Windows
            import threading
            from queue import Queue, Empty

            # Log the command being executed
            cls.logger.info(f"Executing mineru command: {' '.join(cmd)}")

            env = None
            if custom_env:
                env = os.environ.copy()
                env.update(custom_env)

            subprocess_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "ignore",
                "bufsize": 1,  # Line buffered
                "env": env,
            }

            # Hide console window on Windows
            if _IS_WINDOWS:
                subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            # Function to read output from subprocess and add to queue
            def enqueue_output(pipe, queue, prefix):
                try:
                    for line in iter(pipe.readline, ""):
                        if line.strip():  # Only add non-empty lines
                            queue.put((prefix, line.strip()))
                    pipe.close()
                except Exception as e:
                    queue.put((prefix, f"Error reading {prefix}: {e}"))

            # Start subprocess
            process = subprocess.Popen(cmd, **subprocess_kwargs)

            # Create queues for stdout and stderr
            stdout_queue = Queue()
            stderr_queue = Queue()

            # Start threads to read output
            stdout_thread = threading.Thread(
                target=enqueue_output, args=(process.stdout, stdout_queue, "STDOUT")
            )
            stderr_thread = threading.Thread(
                target=enqueue_output, args=(process.stderr, stderr_queue, "STDERR")
            )

            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            # Process output in real time
            start_time = time.monotonic()

            while process.poll() is None:
                # Check stdout queue
                try:
                    while True:
                        prefix, line = stdout_queue.get_nowait()
                        output_lines.append(line)
                        # Log mineru output with INFO level, prefixed with [MinerU]
                        cls.logger.info(f"[MinerU] {line}")
                except Empty:
                    pass

                # Check stderr queue
                try:
                    while True:
                        prefix, line = stderr_queue.get_nowait()
                        # Log mineru errors with WARNING level
                        if "warning" in line.lower():
                            cls.logger.warning(f"[MinerU] {line}")
                        elif "error" in line.lower():
                            cls.logger.error(f"[MinerU] {line}")
                            error_message = line.split("\n")[0]
                            error_lines.append(error_message)
                        else:
                            cls.logger.info(f"[MinerU] {line}")
                except Empty:
                    pass

                # Enforce timeout — kill the process and raise if exceeded
                if timeout is not None and (time.monotonic() - start_time) > timeout:
                    process.kill()
                    process.wait()
                    # Give reader threads a moment to drain before raising
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)
                    raise TimeoutError(
                        f"MinerU did not finish within {timeout}s. "
                        "This often means a model download is stuck due to network issues. "
                        "Check your internet connection or pre-download the required models."
                    )

                # Small delay to prevent busy waiting
                time.sleep(0.1)

            # Process any remaining output after process completion
            try:
                while True:
                    prefix, line = stdout_queue.get_nowait()
                    output_lines.append(line)
                    cls.logger.info(f"[MinerU] {line}")
            except Empty:
                pass

            try:
                while True:
                    prefix, line = stderr_queue.get_nowait()
                    if "warning" in line.lower():
                        cls.logger.warning(f"[MinerU] {line}")
                    elif "error" in line.lower():
                        cls.logger.error(f"[MinerU] {line}")
                        error_message = line.split("\n")[0]
                        error_lines.append(error_message)
                    else:
                        cls.logger.info(f"[MinerU] {line}")
            except Empty:
                pass

            # Wait for process to complete and get return code
            return_code = process.wait()

            # Wait for threads to finish
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)

            if return_code != 0 or error_lines:
                cls.logger.info("[MinerU] Command executed failed")
                raise MineruExecutionError(return_code, error_lines)
            else:
                cls.logger.info("[MinerU] Command executed successfully")

        except MineruExecutionError:
            raise
        except subprocess.CalledProcessError as e:
            cls.logger.error(f"Error running mineru subprocess command: {e}")
            cls.logger.error(f"Command: {' '.join(cmd)}")
            cls.logger.error(f"Return code: {e.returncode}")
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "mineru command not found. Please ensure MinerU 2.0 is properly installed:\n"
                "pip install -U 'mineru[core]' or uv pip install -U 'mineru[core]'"
            )
        except Exception as e:
            error_message = f"Unexpected error running mineru command: {e}"
            cls.logger.error(error_message)
            raise RuntimeError(error_message) from e

    @classmethod
    def _read_output_files(
        cls, output_dir: Path, file_stem: str, method: str = "auto"
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Read the output files generated by mineru

        Args:
            output_dir: Output directory
            file_stem: File name without extension
            method: Parsing method (used as fallback if subdirectory scan fails)

        Returns:
            Tuple containing (content list JSON, Markdown text)
        """
        # MinerU can emit different subdirectory names for the same logical method,
        # e.g. `hybrid_auto/` for `method="auto"`. Prefer an exact match first, then
        # fall back to known aliases and finally scan all generated subdirectories.
        file_stem_subdir = output_dir / file_stem
        candidate_dirs = [output_dir]
        if file_stem_subdir.exists():
            candidate_dirs.append(file_stem_subdir / method)
            if method == "auto":
                candidate_dirs.extend(
                    [
                        file_stem_subdir / "hybrid_auto",
                        file_stem_subdir / "auto",
                    ]
                )
            elif method == "ocr":
                candidate_dirs.append(file_stem_subdir / "hybrid_ocr")
            elif method == "txt":
                candidate_dirs.append(file_stem_subdir / "hybrid_txt")

            candidate_dirs.extend(
                child for child in sorted(file_stem_subdir.iterdir()) if child.is_dir()
            )

        def _select_paths() -> Tuple[Path, Path, Path]:
            for candidate_dir in candidate_dirs:
                json_candidates = [
                    candidate_dir / f"{file_stem}_content_list.json",
                    candidate_dir / f"{file_stem}_content_list_v2.json",
                ]
                for candidate_json in json_candidates:
                    if candidate_json.exists():
                        return (
                            candidate_dir / f"{file_stem}.md",
                            candidate_json,
                            candidate_dir,
                        )

            # Fallback to the original flat output convention.
            return (
                output_dir / f"{file_stem}.md",
                output_dir / f"{file_stem}_content_list.json",
                output_dir,
            )

        md_file, json_file, images_base_dir = _select_paths()

        # Read markdown content
        md_content = ""
        if md_file.exists():
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception as e:
                cls.logger.warning(f"Could not read markdown file {md_file}: {e}")

        # Read JSON content list
        content_list = []
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    content_list = json.load(f)

                # Normalize MinerU 2.0 field names to expected names for backward compatibility.
                # MinerU 2.0 renamed: img_caption -> image_caption, img_footnote -> image_footnote
                # The codebase primarily uses image_caption/image_footnote with img_caption/img_footnote
                # as fallback, but we ensure both fields exist so downstream code works regardless.
                _FIELD_ALIASES = {
                    # MinerU 1.x name -> MinerU 2.0 name (canonical)
                    "img_caption": "image_caption",
                    "img_footnote": "image_footnote",
                }
                for item in content_list:
                    if isinstance(item, dict):
                        for old_name, new_name in _FIELD_ALIASES.items():
                            # If only the old field exists, copy it to the new field name
                            if old_name in item and new_name not in item:
                                item[new_name] = item[old_name]
                            # If only the new field exists, copy it to the old field name (for any legacy code)
                            elif new_name in item and old_name not in item:
                                item[old_name] = item[new_name]

                # Always fix relative paths in content_list to absolute paths
                cls.logger.info(
                    f"Fixing image paths in {json_file} with base directory: {images_base_dir}"
                )
                for item in content_list:
                    if isinstance(item, dict):
                        for field_name in [
                            "img_path",
                            "table_img_path",
                            "equation_img_path",
                        ]:
                            if field_name in item and item[field_name]:
                                img_path = item[field_name]
                                absolute_img_path = (
                                    images_base_dir / img_path
                                ).resolve()

                                # Security check: ensure the image path is within the base directory
                                resolved_base = images_base_dir.resolve()
                                if not absolute_img_path.is_relative_to(resolved_base):
                                    cls.logger.warning(
                                        f"Potential path traversal detected in {field_name}: {img_path}. Skipping."
                                    )
                                    item[field_name] = ""  # Clear unsafe path
                                    continue

                                item[field_name] = str(absolute_img_path)

                        attach_public_media_urls(item)

            except Exception as e:
                cls.logger.warning(f"Could not read JSON file {json_file}: {e}")

        return content_list, md_content

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse PDF document using MinerU 2.0

        Args:
            pdf_path: Path to the PDF file
            output_dir: Output directory path
            method: Parsing method (auto, txt, ocr)
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for mineru command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert to Path object for easier handling
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

            name_without_suff = pdf_path.stem

            # Prepare output directory — use unique subdirectory to prevent
            # same-name file collisions when output_dir is shared (#51)
            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, pdf_path)
            else:
                base_output_dir = pdf_path.parent / "mineru_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            # Run mineru command
            self._run_mineru_command(
                input_path=pdf_path,
                output_dir=base_output_dir,
                method=method,
                lang=lang,
                **kwargs,
            )

            # Read the generated output files
            # Map backend to expected output directory name for better compatibility
            # MinerU 2.7.0+ uses different directory names based on backend:
            # - pipeline -> auto/
            # - vlm-* -> vlm/
            # - hybrid-* -> hybrid_auto/
            # Note: _read_output_files() will scan subdirectories automatically,
            # so this mapping is just for optimization and fallback
            # Use `or ""` to handle both missing keys and explicit None values
            backend = kwargs.get("backend") or ""
            if backend.startswith("vlm-"):
                method = "vlm"
            elif backend.startswith("hybrid-"):
                method = "hybrid_auto"

            content_list, _ = self._read_output_files(
                base_output_dir, name_without_suff, method=method
            )
            return content_list

        except MineruExecutionError:
            raise
        except Exception as e:
            self.logger.error(f"Error in parse_pdf: {str(e)}")
            raise

    def parse_image(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse image document using MinerU 2.0

        Note: MinerU 2.0 natively supports .png, .jpeg, .jpg formats.
        Other formats (.bmp, .tiff, .tif, etc.) will be automatically converted to .png.

        Args:
            image_path: Path to the image file
            output_dir: Output directory path
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for mineru command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert to Path object for easier handling
            image_path = Path(image_path)
            if not image_path.exists():
                raise FileNotFoundError(f"Image file does not exist: {image_path}")

            # Supported image formats by MinerU 2.0
            mineru_supported_formats = {".png", ".jpeg", ".jpg"}

            # All supported image formats (including those we can convert)
            all_supported_formats = {
                ".png",
                ".jpeg",
                ".jpg",
                ".bmp",
                ".tiff",
                ".tif",
                ".gif",
                ".webp",
            }

            ext = image_path.suffix.lower()
            if ext not in all_supported_formats:
                raise ValueError(
                    f"Unsupported image format: {ext}. Supported formats: {', '.join(all_supported_formats)}"
                )

            # Determine the actual image file to process
            actual_image_path = image_path
            temp_converted_file = None

            # If format is not natively supported by MinerU, convert it
            if ext not in mineru_supported_formats:
                self.logger.info(
                    f"Converting {ext} image to PNG for MinerU compatibility..."
                )

                try:
                    from PIL import Image
                except ImportError:
                    raise RuntimeError(
                        "PIL/Pillow is required for image format conversion. "
                        "Please install it using: pip install Pillow"
                    )

                # Create temporary directory for conversion
                temp_dir = Path(tempfile.mkdtemp())
                temp_converted_file = temp_dir / f"{image_path.stem}_converted.png"

                try:
                    # Open and convert image
                    with Image.open(image_path) as img:
                        # Handle different image modes
                        if img.mode in ("RGBA", "LA", "P"):
                            # For images with transparency or palette, convert to RGB first
                            if img.mode == "P":
                                img = img.convert("RGBA")

                            # Create white background for transparent images
                            background = Image.new("RGB", img.size, (255, 255, 255))
                            if img.mode == "RGBA":
                                background.paste(
                                    img, mask=img.split()[-1]
                                )  # Use alpha channel as mask
                            else:
                                background.paste(img)
                            img = background
                        elif img.mode not in ("RGB", "L"):
                            # Convert other modes to RGB
                            img = img.convert("RGB")

                        # Save as PNG
                        img.save(temp_converted_file, "PNG", optimize=True)
                        self.logger.info(
                            f"Successfully converted {image_path.name} to PNG ({temp_converted_file.stat().st_size / 1024:.1f} KB)"
                        )

                        actual_image_path = temp_converted_file

                except Exception as e:
                    if temp_converted_file and temp_converted_file.exists():
                        temp_converted_file.unlink()
                    raise RuntimeError(
                        f"Failed to convert image {image_path.name}: {str(e)}"
                    )

            name_without_suff = image_path.stem

            # Prepare output directory — use unique subdirectory to prevent
            # same-name file collisions when output_dir is shared (#51)
            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, image_path)
            else:
                base_output_dir = image_path.parent / "mineru_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Run mineru command (images are processed with OCR method)
                self._run_mineru_command(
                    input_path=actual_image_path,
                    output_dir=base_output_dir,
                    method="ocr",  # Images require OCR method
                    lang=lang,
                    **kwargs,
                )

                # Read the generated output files
                content_list, _ = self._read_output_files(
                    base_output_dir, name_without_suff, method="ocr"
                )
                return content_list

            except MineruExecutionError:
                raise

            finally:
                # Clean up temporary converted file if it was created
                if temp_converted_file and temp_converted_file.exists():
                    try:
                        temp_converted_file.unlink()
                        temp_converted_file.parent.rmdir()  # Remove temp directory if empty
                    except Exception:
                        pass  # Ignore cleanup errors

        except Exception as e:
            self.logger.error(f"Error in parse_image: {str(e)}")
            raise

    def parse_office_doc(
        self,
        doc_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse office document by first converting to PDF, then parsing with MinerU 2.0

        Note: This method requires LibreOffice to be installed separately for PDF conversion.
        MinerU 2.0 no longer includes built-in Office document conversion.

        Supported formats: .doc, .docx, .ppt, .pptx, .xls, .xlsx

        Args:
            doc_path: Path to the document file (.doc, .docx, .ppt, .pptx, .xls, .xlsx)
            output_dir: Output directory path
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for mineru command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert Office document to PDF using base class method
            pdf_path = self.convert_office_to_pdf(doc_path, output_dir)

            # Parse the converted PDF
            return self.parse_pdf(
                pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
            )

        except Exception as e:
            self.logger.error(f"Error in parse_office_doc: {str(e)}")
            raise

    def parse_text_file(
        self,
        text_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse text file by first converting to PDF, then parsing with MinerU 2.0

        Supported formats: .txt, .md

        Args:
            text_path: Path to the text file (.txt, .md)
            output_dir: Output directory path
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for mineru command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert text file to PDF using base class method
            pdf_path = self.convert_text_to_pdf(text_path, output_dir)

            # Parse the converted PDF
            return self.parse_pdf(
                pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
            )

        except Exception as e:
            self.logger.error(f"Error in parse_text_file: {str(e)}")
            raise

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse document using MinerU 2.0 based on file extension

        Args:
            file_path: Path to the file to be parsed
            method: Parsing method (auto, txt, ocr)
            output_dir: Output directory path
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for mineru command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        # Convert to Path object
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        # Get file extension
        ext = file_path.suffix.lower()

        # Choose appropriate parser based on file type
        if ext == ".pdf":
            return self.parse_pdf(file_path, output_dir, method, lang, **kwargs)
        elif ext in self.IMAGE_FORMATS:
            return self.parse_image(file_path, output_dir, lang, **kwargs)
        elif ext in self.OFFICE_FORMATS:
            self.logger.warning(
                f"Warning: Office document detected ({ext}). "
                f"MinerU 2.0 requires conversion to PDF first."
            )
            return self.parse_office_doc(file_path, output_dir, lang, **kwargs)
        elif ext in self.TEXT_FORMATS:
            return self.parse_text_file(file_path, output_dir, lang, **kwargs)
        else:
            # For unsupported file types, try as PDF
            self.logger.warning(
                f"Warning: Unsupported file extension '{ext}', "
                f"attempting to parse as PDF"
            )
            return self.parse_pdf(file_path, output_dir, method, lang, **kwargs)

    def check_installation(self) -> bool:
        """
        Check if MinerU 2.0 is properly installed

        Returns:
            bool: True if installation is valid, False otherwise
        """
        try:
            # Prepare subprocess parameters to hide console window on Windows
            subprocess_kwargs = {
                "capture_output": True,
                "text": True,
                "check": True,
                "encoding": "utf-8",
                "errors": "ignore",
            }

            # Hide console window on Windows
            if _IS_WINDOWS:
                subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(["mineru", "--version"], **subprocess_kwargs)
            self.logger.debug(f"MinerU version: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.debug(
                "MinerU 2.0 is not properly installed. "
                "Please install it using: pip install -U 'mineru[core]'"
            )
            return False


class DoclingParser(Parser):
    """
    Docling document parsing utility class.

    Specialized in parsing Office documents and HTML files, converting the content
    into structured data and generating markdown and JSON output.

    Backed by the Docling Python API (`docling.document_converter.DocumentConverter`)
    to avoid subprocess overhead and re-initialization of Docling's deep-learning
    models on every call. A `DocumentConverter` instance is built lazily on first
    use and cached per pipeline-option combination so that subsequent parses
    against the same configuration reuse already-loaded models.

    Compatibility changes vs. earlier CLI-subprocess implementation
    ----------------------------------------------------------------
    - `check_installation()` now returns True iff the Docling Python package
      can be imported (`docling.document_converter.DocumentConverter`). The
      previous behavior of probing the `docling` CLI executable on PATH is
      gone; environments that ship the CLI without the importable package
      (or vice versa) will see a different result than before.
    - The legacy `env={...}` kwarg is still accepted for source-level
      compatibility but is **ignored**: the Python API does not run a
      subprocess, so per-call environment overrides no longer take effect.
      Callers needing model-cache, proxy, or CUDA configuration should set
      the corresponding environment variables in the parent process before
      instantiating `DoclingParser`, or configure Docling directly via
      `_get_converter` kwargs (`artifacts_path`, `table_mode`, ...).
    - JSON and Markdown artifacts are still written to
      `<output_dir>/<file_stem>/docling/` for backward compatibility, but
      they are produced by Docling's `export_to_dict()` /
      `export_to_markdown()` rather than by the CLI's serializer; expect the
      same logical content but not byte-identical files (key ordering,
      whitespace, optional fields may differ).

    Concurrency
    -----------
    The internal converter cache is guarded by a lock so that a single
    `DoclingParser` instance can be safely shared across threads without
    duplicating Docling model loads on first use.
    """

    # Define Docling-specific formats
    HTML_FORMATS = {".html", ".htm", ".xhtml"}

    def __init__(self) -> None:
        """Initialize DoclingParser"""
        super().__init__()
        # Cache of DocumentConverter instances keyed by pipeline-option tuple,
        # so that loaded layout/OCR/table models are reused across calls.
        # The lock guards concurrent first-use from creating duplicate
        # converters (and re-loading models) when the same DoclingParser
        # instance is shared across threads.
        self._converter_cache: Dict[Tuple, Any] = {}
        self._converter_cache_lock = threading.Lock()

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse PDF document using Docling

        Args:
            pdf_path: Path to the PDF file
            output_dir: Output directory path
            method: Parsing method (auto, txt, ocr)
            lang: Document language for OCR optimization
            **kwargs: Additional parameters for docling command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert to Path object for easier handling
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

            name_without_suff = pdf_path.stem

            # Prepare output directory — use unique subdirectory to prevent
            # same-name file collisions when output_dir is shared (#51)
            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, pdf_path)
            else:
                base_output_dir = pdf_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)
            command_kwargs = dict(kwargs)
            if lang and "ocr_lang" not in command_kwargs:
                command_kwargs["ocr_lang"] = lang

            # Parse via the Docling Python API and convert directly from the
            # in-memory dict, bypassing the JSON disk round-trip.
            doc_dict = self._run_docling_python(
                input_path=pdf_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **command_kwargs,
            )
            file_subdir = base_output_dir / name_without_suff / "docling"
            content_list = self.read_from_block_recursive(
                doc_dict["body"], "body", file_subdir, 0, "0", doc_dict
            )
            return content_list

        except Exception as e:
            self.logger.error(f"Error in parse_pdf: {str(e)}")
            raise

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse document using Docling based on file extension

        Args:
            file_path: Path to the file to be parsed or URL
            method: Parsing method
            output_dir: Output directory path
            lang: Document language for optimization
            **kwargs: Additional parameters for docling command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        downloaded_temp_file = None

        try:
            # Check if input is a URL
            if self._is_url(file_path):
                file_path = self._download_file(file_path)
                downloaded_temp_file = file_path

            # Convert to Path object
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"File does not exist: {file_path}")

            # Get file extension
            ext = file_path.suffix.lower()

            # Choose appropriate parser based on file type
            if ext == ".pdf":
                return self.parse_pdf(file_path, output_dir, method, lang, **kwargs)
            elif ext in self.OFFICE_FORMATS:
                return self.parse_office_doc(file_path, output_dir, lang, **kwargs)
            elif ext in self.HTML_FORMATS:
                return self.parse_html(file_path, output_dir, lang, **kwargs)
            else:
                raise ValueError(
                    f"Unsupported file format: {ext}. "
                    f"Docling only supports PDF files, Office formats ({', '.join(self.OFFICE_FORMATS)}) "
                    f"and HTML formats ({', '.join(self.HTML_FORMATS)})"
                )
        finally:
            # Clean up temporary file if we downloaded one
            if downloaded_temp_file and downloaded_temp_file.exists():
                try:
                    downloaded_temp_file.unlink()
                    self.logger.debug(f"Removed temporary file: {downloaded_temp_file}")
                except Exception as e:
                    self.logger.warning(
                        f"Failed to remove temporary file {downloaded_temp_file}: {e}"
                    )

    def _get_converter(self, **kwargs) -> Any:
        """
        Lazily build and cache a `DocumentConverter` configured from kwargs.

        Caches one converter per distinct pipeline-option tuple so that Docling's
        layout, OCR, and TableFormer models are loaded only once per process for
        a given configuration, drastically reducing per-document latency on
        multi-document workloads.

        Recognized kwargs (all optional):
            table_mode (str): "fast" (default) or "accurate" – TableFormer mode.
            tables (bool): Enable table structure recognition (default: True).
            allow_ocr (bool): Enable OCR on scanned content (default: True).
            artifacts_path (str): Path to a custom Docling models directory.
        """
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
        )

        table_mode = str(kwargs.get("table_mode", "fast")).lower()
        do_tables = bool(kwargs.get("tables", True))
        do_ocr = bool(kwargs.get("allow_ocr", True))
        artifacts_path = kwargs.get("artifacts_path")

        cache_key = (table_mode, do_tables, do_ocr, artifacts_path)
        # Fast path: snapshot read outside the lock (dict reads are atomic in
        # CPython for hashable keys) so the common cache-hit case stays
        # contention-free.
        cached = self._converter_cache.get(cache_key)
        if cached is not None:
            return cached

        pipeline_options = PdfPipelineOptions()
        if hasattr(pipeline_options, "do_ocr"):
            pipeline_options.do_ocr = do_ocr
        if hasattr(pipeline_options, "do_table_structure"):
            pipeline_options.do_table_structure = do_tables
        if hasattr(pipeline_options, "table_structure_options"):
            try:
                pipeline_options.table_structure_options.mode = (
                    TableFormerMode.ACCURATE
                    if table_mode == "accurate"
                    else TableFormerMode.FAST
                )
            except Exception as e:  # pragma: no cover - defensive
                self.logger.debug(f"Could not set TableFormer mode '{table_mode}': {e}")
        if artifacts_path and hasattr(pipeline_options, "artifacts_path"):
            pipeline_options.artifacts_path = artifacts_path

        # Ask Docling to embed picture bytes in the exported dict so that
        # `read_from_block` can extract them from `block["image"]["uri"]`
        # without a second pass over the source document.
        if hasattr(pipeline_options, "generate_picture_images"):
            pipeline_options.generate_picture_images = True
        if hasattr(pipeline_options, "images_scale"):
            pipeline_options.images_scale = 2.0

        # Slow path: serialize converter construction so that concurrent
        # first-use against the same cache_key doesn't load Docling's models
        # twice. We re-check the cache under the lock to avoid a double build
        # when two threads race past the fast-path check above.
        with self._converter_cache_lock:
            cached = self._converter_cache.get(cache_key)
            if cached is not None:
                return cached
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                }
            )
            self._converter_cache[cache_key] = converter
            return converter

    def _run_docling_python(
        self,
        input_path: Union[str, Path],
        output_dir: Union[str, Path],
        file_stem: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Parse `input_path` through the Docling Python API and return the
        exported document dict.

        Replaces the legacy `_run_docling_command` path that shelled out to the
        `docling` CLI. JSON and Markdown artifacts are still written to
        `<output_dir>/<file_stem>/docling/` for backward compatibility, but the
        document dict is also fed directly to `read_from_block_recursive`
        without an intermediate disk round-trip.

        Args:
            input_path: Source document.
            output_dir: Base output directory (a `<file_stem>/docling`
                subdirectory will be created inside it).
            file_stem: File name without extension, used for the subdirectory
                and the output artifact filenames.
            **kwargs: Forwarded to `_get_converter`. The legacy `env` kwarg is
                still accepted for backward compatibility but has no effect
                under the Python API.

        Returns:
            The Docling document exported via `export_to_dict()`.
        """
        file_output_dir = Path(output_dir) / file_stem / "docling"
        file_output_dir.mkdir(parents=True, exist_ok=True)

        option_map = {
            "device": "--device",
            "ocr_lang": "--ocr-lang",
            "num_threads": "--num-threads",
            "page_batch_size": "--page-batch-size",
            "document_timeout": "--document-timeout",
            "pdf_backend": "--pdf-backend",
            "table_mode": "--table-mode",
            "ocr_engine": "--ocr-engine",
            "artifacts_path": "--artifacts-path",
        }
        docling_args: List[str] = []
        for key, flag in option_map.items():
            value = kwargs.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                value = ",".join(str(v) for v in value if v is not None)
            docling_args.extend([flag, str(value)])

        cmd = [
            "docling",
            "--output",
            str(file_output_dir),
        ]
        cmd.extend(docling_args)
        cmd.extend(["--to", "json", "--to", "md", str(input_path)])

        try:
            # Prepare subprocess parameters to hide console window on Windows
            import platform

            docling_subprocess_kwargs = {
                "capture_output": True,
                "text": True,
                "check": True,
                "encoding": "utf-8",
                "errors": "ignore",
            }

            # Hide console window on Windows
            if platform.system() == "Windows":
                docling_subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            logging.info(f"Executing docling command: {' '.join(cmd)}")
            result = subprocess.run(cmd, **docling_subprocess_kwargs)
            logging.info("Docling command executed successfully")
            if result.stdout:
                logging.debug(f"Docling cmd output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running docling command: {e}")
            if e.stderr:
                logging.error(f"Error details: {e.stderr}")
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "Docling Python API is not available. Install it with: "
                "pip install docling"
            ) from e

        try:
            result = converter.convert(str(input_path))
        except Exception as e:
            self.logger.error(f"Error running Docling Python API on {input_path}: {e}")
            raise

        doc = result.document
        try:
            doc_dict = doc.export_to_dict()
        except Exception as e:
            self.logger.error(f"Failed to export Docling document to dict: {e}")
            raise

        # Persist JSON + Markdown artifacts on disk to preserve the file layout
        # produced by the previous CLI-based implementation. Failures here are
        # logged but do not abort parsing, since callers only require the
        # in-memory dict.
        json_path = file_output_dir / f"{file_stem}.json"
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Could not write Docling JSON to {json_path}: {e}")

        md_path = file_output_dir / f"{file_stem}.md"
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(doc.export_to_markdown())
        except Exception as e:
            self.logger.warning(f"Could not write Docling Markdown to {md_path}: {e}")

        self.logger.info(
            f"Docling Python API parse completed for {Path(input_path).name}"
        )
        return doc_dict

    def read_from_block_recursive(
        self,
        block,
        type: str,
        output_dir: Path,
        cnt: int,
        num: str,
        docling_content: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        content_list = []
        if not block.get("children"):
            cnt += 1
            content_list.append(self.read_from_block(block, type, output_dir, cnt, num))
        else:
            if type not in ["groups", "body"]:
                cnt += 1
                content_list.append(
                    self.read_from_block(block, type, output_dir, cnt, num)
                )
            members = block["children"]
            for member in members:
                cnt += 1
                member_tag = member["$ref"]
                # JSON References follow the form "#/<type>/<index>" (e.g. "#/body/0")
                ref_parts = member_tag.split("/")
                if len(ref_parts) < 3:
                    self.logger.warning(
                        f"Unexpected $ref format (expected #/<type>/<index>): {member_tag!r}"
                    )
                    continue
                member_type = ref_parts[1]
                member_num = ref_parts[2]
                try:
                    member_block = docling_content[member_type][int(member_num)]
                except (KeyError, ValueError, IndexError) as e:
                    self.logger.warning(f"Could not resolve $ref {member_tag!r}: {e}")
                    continue
                content_list.extend(
                    self.read_from_block_recursive(
                        member_block,
                        member_type,
                        output_dir,
                        cnt,
                        member_num,
                        docling_content,
                    )
                )
        return content_list

    def read_from_block(
        self, block, type: str, output_dir: Path, cnt: int, num: str
    ) -> Dict[str, Any]:
        if type == "texts":
            if block["label"] == "formula":
                return {
                    "type": "equation",
                    "img_path": "",
                    "text": block["orig"],
                    "text_format": "unknown",
                    "page_idx": cnt // 10,
                }
            else:
                return {
                    "type": "text",
                    "text": block["orig"],
                    "page_idx": cnt // 10,
                }
        elif type == "pictures":
            try:
                base64_uri = block["image"]["uri"]
                # base64 data URIs have the form "data:<mime>;base64,<data>"
                # but some exporters may omit the prefix
                parts = base64_uri.split(",", 1)
                base64_str = parts[1] if len(parts) == 2 else parts[0]
                # Create images directory within the docling subdirectory
                image_dir = output_dir / "images"
                image_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
                image_path = image_dir / f"image_{num}.png"
                with open(image_path, "wb") as f:
                    f.write(base64.b64decode(base64_str))
                return {
                    "type": "image",
                    "img_path": str(image_path.resolve()),  # Convert to absolute path
                    "image_caption": block.get("caption", ""),
                    "image_footnote": block.get("footnote", ""),
                    "page_idx": cnt // 10,
                }
            except Exception as e:
                self.logger.warning(f"Failed to process image {num}: {e}")
                return {
                    "type": "text",
                    "text": f"[Image processing failed: {block.get('caption', '')}]",
                    "page_idx": cnt // 10,
                }
        else:
            try:
                return {
                    "type": "table",
                    "img_path": "",
                    "table_caption": block.get("caption", ""),
                    "table_footnote": block.get("footnote", ""),
                    "table_body": block.get("data", []),
                    "page_idx": cnt // 10,
                }
            except Exception as e:
                self.logger.warning(f"Failed to process table {num}: {e}")
                return {
                    "type": "text",
                    "text": f"[Table processing failed: {block.get('caption', '')}]",
                    "page_idx": cnt // 10,
                }

    def parse_office_doc(
        self,
        doc_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse office document directly using Docling

        Supported formats: .doc, .docx, .ppt, .pptx, .xls, .xlsx

        Args:
            doc_path: Path to the document file
            output_dir: Output directory path
            lang: Document language for optimization
            **kwargs: Additional parameters for docling command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert to Path object
            doc_path = Path(doc_path)
            if not doc_path.exists():
                raise FileNotFoundError(f"Document file does not exist: {doc_path}")

            if doc_path.suffix.lower() not in self.OFFICE_FORMATS:
                raise ValueError(f"Unsupported office format: {doc_path.suffix}")

            name_without_suff = doc_path.stem

            # Prepare output directory — use unique subdirectory to prevent
            # same-name file collisions when output_dir is shared (#51)
            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, doc_path)
            else:
                base_output_dir = doc_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)
            command_kwargs = dict(kwargs)
            if lang and "ocr_lang" not in command_kwargs:
                command_kwargs["ocr_lang"] = lang

            doc_dict = self._run_docling_python(
                input_path=doc_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **command_kwargs,
            )
            file_subdir = base_output_dir / name_without_suff / "docling"
            content_list = self.read_from_block_recursive(
                doc_dict["body"], "body", file_subdir, 0, "0", doc_dict
            )
            return content_list

        except Exception as e:
            self.logger.error(f"Error in parse_office_doc: {str(e)}")
            raise

    def parse_html(
        self,
        html_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Parse HTML document using Docling

        Supported formats: .html, .htm, .xhtml

        Args:
            html_path: Path to the HTML file
            output_dir: Output directory path
            lang: Document language for optimization
            **kwargs: Additional parameters for docling command

        Returns:
            List[Dict[str, Any]]: List of content blocks
        """
        try:
            # Convert to Path object
            html_path = Path(html_path)
            if not html_path.exists():
                raise FileNotFoundError(f"HTML file does not exist: {html_path}")

            if html_path.suffix.lower() not in self.HTML_FORMATS:
                raise ValueError(f"Unsupported HTML format: {html_path.suffix}")

            name_without_suff = html_path.stem

            # Prepare output directory — use unique subdirectory to prevent
            # same-name file collisions when output_dir is shared (#51)
            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, html_path)
            else:
                base_output_dir = html_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)
            command_kwargs = dict(kwargs)
            if lang and "ocr_lang" not in command_kwargs:
                command_kwargs["ocr_lang"] = lang

            doc_dict = self._run_docling_python(
                input_path=html_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **command_kwargs,
            )
            file_subdir = base_output_dir / name_without_suff / "docling"
            content_list = self.read_from_block_recursive(
                doc_dict["body"], "body", file_subdir, 0, "0", doc_dict
            )
            return content_list

        except Exception as e:
            self.logger.error(f"Error in parse_html: {str(e)}")
            raise

    def check_installation(self) -> bool:
        """
        Check whether the Docling Python package is importable.

        Returns:
            bool: True if `docling.document_converter.DocumentConverter` can be
                imported, False otherwise.

        Note:
            This is a behavior change from the previous CLI-subprocess
            implementation, which probed the `docling` executable on PATH.
            Some environments may have the CLI installed without the Python
            package (or vice versa) and will therefore see a different
            result. The Python-API path is what `parse_pdf`,
            `parse_office_doc`, and `parse_html` actually exercise, so this
            check is now a faithful pre-flight for those entry points.
        """
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401

            return True
        except ImportError:
            self.logger.debug(
                "Docling Python package is not installed. "
                "Install it with: pip install docling"
            )
            return False


class PaddleOCRParser(Parser):
    """PaddleOCR document parser with optional PDF page rendering support."""

    def __init__(self, default_lang: str = "en") -> None:
        super().__init__()
        self.default_lang = default_lang
        self._ocr_instances: Dict[str, Any] = {}

    def _require_paddleocr(self):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ImportError(
                "PaddleOCR parser requires optional dependency `paddleocr`. "
                "Install with `pip install -e '.[paddleocr]'` or "
                "`uv sync --extra paddleocr`. "
                "PaddleOCR also needs `paddlepaddle`; install it from "
                "https://www.paddlepaddle.org.cn/install/quick."
            ) from exc
        return PaddleOCR

    def _get_ocr(self, lang: Optional[str] = None):
        PaddleOCR = self._require_paddleocr()
        language = (lang or self.default_lang).strip() or self.default_lang
        cached = self._ocr_instances.get(language)
        if cached is not None:
            return cached

        init_candidates = [
            {"lang": language, "show_log": False},
            {"lang": language},
            {},
        ]
        last_exception = None
        for candidate_kwargs in init_candidates:
            try:
                ocr = PaddleOCR(**candidate_kwargs)
                self._ocr_instances[language] = ocr
                return ocr
            except Exception as exc:  # pragma: no cover - defensive fallback
                last_exception = exc
                continue

        raise RuntimeError(
            f"Unable to initialize PaddleOCR for language '{language}': {last_exception}"
        )

    def _extract_text_lines(self, result: Any) -> List[str]:
        lines: List[str] = []

        def append_text(text: str) -> None:
            clean_text = text.strip()
            if clean_text:
                lines.append(clean_text)

        if isinstance(result, str):
            append_text(result)
            return lines

        def visit(node: Any) -> None:
            if node is None:
                return

            if hasattr(node, "to_dict"):
                try:
                    visit(node.to_dict())
                    return
                except Exception:
                    pass

            if isinstance(node, dict):
                rec_texts = node.get("rec_texts")
                if isinstance(rec_texts, list):
                    for item in rec_texts:
                        if isinstance(item, str):
                            append_text(item)
                        else:
                            visit(item)

                text_value = node.get("text")
                if isinstance(text_value, str):
                    append_text(text_value)

                texts_value = node.get("texts")
                if isinstance(texts_value, list):
                    for item in texts_value:
                        if isinstance(item, str):
                            append_text(item)
                        else:
                            visit(item)

                # Avoid double-visiting keys we already handled above; this prevents
                # accidental duplication without content-level deduplication.
                for key, value in node.items():
                    if key in {"rec_texts", "text", "texts"}:
                        continue
                    visit(value)
                return

            if isinstance(node, (list, tuple)):
                if node and all(isinstance(item, str) for item in node):
                    for item in node:
                        append_text(item)
                    return

                if (
                    len(node) >= 2
                    and isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 1
                    and isinstance(node[1][0], str)
                ):
                    append_text(node[1][0])
                    return

                if (
                    len(node) >= 1
                    and isinstance(node[0], str)
                    and (len(node) == 1 or isinstance(node[1], (int, float)))
                ):
                    append_text(node[0])
                    return

                for item in node:
                    visit(item)
                return

            if isinstance(node, str):
                append_text(node)
                return

        visit(result)
        return lines

    def _ocr_input(
        self, input_data: Any, lang: Optional[str] = None, cls_enabled: bool = True
    ) -> List[str]:
        ocr = self._get_ocr(lang=lang)

        if hasattr(ocr, "ocr"):
            try:
                result = ocr.ocr(input_data, cls=cls_enabled)
            except TypeError:
                result = ocr.ocr(input_data)
            return self._extract_text_lines(result)

        if hasattr(ocr, "predict"):
            result = ocr.predict(input_data)
            return self._extract_text_lines(result)

        raise RuntimeError(
            "Unsupported PaddleOCR API: expected `ocr` or `predict` method."
        )

    def _extract_pdf_page_inputs(self, pdf_path: Path) -> Iterator[Tuple[int, Any]]:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise ImportError(
                "PDF parsing with parser='paddleocr' requires `pypdfium2`. "
                "Install with `pip install -e '.[paddleocr]'` or "
                "`uv sync --extra paddleocr`."
            ) from exc

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            total_pages = len(pdf)
            for page_idx in range(total_pages):
                page = pdf[page_idx]
                try:
                    rendered = page.render(scale=2.0)
                    if hasattr(rendered, "to_pil"):
                        yield (page_idx, rendered.to_pil())
                    elif hasattr(rendered, "to_numpy"):
                        yield (page_idx, rendered.to_numpy())
                    else:
                        raise RuntimeError(
                            "Unsupported rendered page format from pypdfium2."
                        )
                finally:
                    if hasattr(page, "close"):
                        page.close()
        finally:
            if hasattr(pdf, "close"):
                pdf.close()

    def _ocr_rendered_page(
        self, rendered_page: Any, lang: Optional[str] = None, cls_enabled: bool = True
    ) -> List[str]:
        if hasattr(rendered_page, "save"):
            temp_image_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
                    temp_image_path = Path(temp.name)
                rendered_page.save(temp_image_path)
                return self._ocr_input(
                    str(temp_image_path), lang=lang, cls_enabled=cls_enabled
                )
            finally:
                if temp_image_path is not None and temp_image_path.exists():
                    try:
                        temp_image_path.unlink()
                    except Exception:
                        pass

        return self._ocr_input(rendered_page, lang=lang, cls_enabled=cls_enabled)

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del output_dir, method
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        cls_enabled = kwargs.get("cls", True)
        content_list: List[Dict[str, Any]] = []
        page_inputs = self._extract_pdf_page_inputs(pdf_path)
        try:
            for page_idx, rendered_page in page_inputs:
                page_lines = self._ocr_rendered_page(
                    rendered_page, lang=lang, cls_enabled=cls_enabled
                )
                for text in page_lines:
                    content_list.append(
                        {"type": "text", "text": text, "page_idx": int(page_idx)}
                    )
        finally:
            # Ensure we promptly release PDF handles even if OCR fails mid-stream.
            close = getattr(page_inputs, "close", None)
            if callable(close):
                close()
        return content_list

    def parse_image(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del output_dir
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file does not exist: {image_path}")

        ext = image_path.suffix.lower()
        if ext not in self.IMAGE_FORMATS:
            raise ValueError(
                f"Unsupported image format: {ext}. Supported formats: {', '.join(sorted(self.IMAGE_FORMATS))}"
            )

        cls_enabled = kwargs.get("cls", True)
        page_idx = int(kwargs.get("page_idx", 0))
        text_lines = self._ocr_input(
            str(image_path), lang=lang, cls_enabled=cls_enabled
        )
        return [
            {"type": "text", "text": text, "page_idx": page_idx} for text in text_lines
        ]

    def parse_office_doc(
        self,
        doc_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        pdf_path = self.convert_office_to_pdf(doc_path, output_dir)
        return self.parse_pdf(
            pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
        )

    def parse_text_file(
        self,
        text_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        pdf_path = self.convert_text_to_pdf(text_path, output_dir)
        return self.parse_pdf(
            pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
        )

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del method
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return self.parse_pdf(file_path, output_dir, lang=lang, **kwargs)
        if ext in self.IMAGE_FORMATS:
            return self.parse_image(file_path, output_dir, lang=lang, **kwargs)
        if ext in self.OFFICE_FORMATS:
            return self.parse_office_doc(file_path, output_dir, lang=lang, **kwargs)
        if ext in self.TEXT_FORMATS:
            return self.parse_text_file(file_path, output_dir, lang=lang, **kwargs)

        raise ValueError(
            f"Unsupported file format: {ext}. "
            "PaddleOCR parser supports PDF, image, office, and text formats."
        )

    def check_installation(self) -> bool:
        try:
            self._require_paddleocr()
            return True
        except ImportError:
            return False


class KreuzbergParser(Parser):
    """
    Kreuzberg document parser (primary for multilingual OCR + structured extraction).

    Uses Kreuzberg's extract_file_sync API to generate content, then converts to
    RAGAnything's content_list format.
    """

    def __init__(self) -> None:
        super().__init__()

    def _extract_with_kreuzberg(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ):
        try:
            import importlib

            kreuzberg_mod = importlib.import_module("kreuzberg")
            extract_file_sync = getattr(kreuzberg_mod, "extract_file_sync")
            ExtractionConfig = getattr(kreuzberg_mod, "ExtractionConfig")
            PageConfig = getattr(kreuzberg_mod, "PageConfig", None)
            PdfConfig = getattr(kreuzberg_mod, "PdfConfig", None)
            ImageExtractionConfig = getattr(kreuzberg_mod, "ImageExtractionConfig", None)
            OcrConfig = getattr(kreuzberg_mod, "OcrConfig", None)
            TesseractConfig = getattr(kreuzberg_mod, "TesseractConfig", None)
            ResultFormat = getattr(kreuzberg_mod, "ResultFormat", None)
        except Exception as e:
            raise RuntimeError(
                "Kreuzberg is not installed. Install with: pip install -U kreuzberg"
            ) from e

        def _accepted_kwargs(cls: Optional[type], candidate: Dict[str, Any]) -> Dict[str, Any]:
            """Keep only kwargs supported by class __init__ signature."""
            if cls is None:
                return {}
            try:
                sig = inspect.signature(cls)
                params = [
                    p
                    for p in sig.parameters.values()
                    if p.name != "self"
                ]
                accepts_any = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
                if accepts_any:
                    return candidate
                accepted_names = {p.name for p in params}
                return {k: v for k, v in candidate.items() if k in accepted_names}
            except Exception:
                # If signature introspection fails, keep candidate and let ctor validate.
                return candidate

        def _as_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return [str(v).strip() for v in value if str(v).strip()]
            value_str = str(value).strip()
            if not value_str:
                return []
            if "," in value_str:
                return [s.strip() for s in value_str.split(",") if s.strip()]
            return [value_str]

        # Keep a mutable kwargs map and consume namespaced options while preserving
        # generic keys (e.g. `extract_images`, `extract_tables`) for legacy APIs.
        kwargs = dict(kwargs or {})

        # Map parse method to Kreuzberg config
        config_kwargs: Dict[str, Any] = {}
        if method == "ocr":
            config_kwargs["force_ocr"] = True
        elif method == "txt":
            config_kwargs["force_ocr"] = False

        # Optional page-level extraction controls
        page_config_kwargs: Dict[str, Any] = {}
        if "extract_pages" in kwargs:
            page_config_kwargs["extract_pages"] = kwargs["extract_pages"]

        # Accept page_* aliases for future settings.
        for key in list(kwargs.keys()):
            if key.startswith("page_"):
                page_config_kwargs[key[len("page_"):]] = kwargs.pop(key)

        page_config_kwargs = _accepted_kwargs(PageConfig, page_config_kwargs)
        if page_config_kwargs:
            try:
                config_kwargs["pages"] = PageConfig(**page_config_kwargs)
            except Exception as e:
                logging.debug(f"KreuzbergParser: failed to build PageConfig: {e}")

        extract_images = kwargs.get("extract_images", None)
        extract_tables = kwargs.get("extract_tables", None)

        # Map image extraction knobs to documented config objects.
        # v4 docs: PdfConfig.extract_images and ExtractionConfig.images.
        pdf_cfg_kwargs: Dict[str, Any] = {}
        if "pdf_extract_images" in kwargs:
            pdf_cfg_kwargs["extract_images"] = kwargs.pop("pdf_extract_images")
        if "pdf_extract_metadata" in kwargs:
            pdf_cfg_kwargs["extract_metadata"] = kwargs.pop("pdf_extract_metadata")
        if "pdf_extract_links" in kwargs:
            pdf_cfg_kwargs["extract_links"] = kwargs.pop("pdf_extract_links")
        if "pdf_extract_bookmarks" in kwargs:
            pdf_cfg_kwargs["extract_bookmarks"] = kwargs.pop("pdf_extract_bookmarks")
        if "pdf_extract_annotations" in kwargs:
            pdf_cfg_kwargs["extract_annotations"] = kwargs.pop("pdf_extract_annotations")
        if "pdf_extract_forms" in kwargs:
            pdf_cfg_kwargs["extract_forms"] = kwargs.pop("pdf_extract_forms")
        if "pdf_extract_attachments" in kwargs:
            pdf_cfg_kwargs["extract_attachments"] = kwargs.pop("pdf_extract_attachments")
        if "pdf_passwords" in kwargs:
            pdf_cfg_kwargs["passwords"] = kwargs.pop("pdf_passwords")
        if extract_images is True and "extract_images" not in pdf_cfg_kwargs:
            pdf_cfg_kwargs["extract_images"] = True
        pdf_cfg_kwargs = _accepted_kwargs(PdfConfig, pdf_cfg_kwargs)
        if pdf_cfg_kwargs:
            try:
                config_kwargs["pdf_options"] = PdfConfig(**pdf_cfg_kwargs)
            except Exception as e:
                logging.debug(f"KreuzbergParser: failed to build PdfConfig: {e}")

        images_cfg_kwargs: Dict[str, Any] = {}
        # Accept both explicit and prefixed image config keys.
        if extract_images is True:
            images_cfg_kwargs["extract_images"] = True
        for key in list(kwargs.keys()):
            if key.startswith("image_"):
                images_cfg_kwargs[key[len("image_"):]] = kwargs.pop(key)
        for key in list(kwargs.keys()):
            if key.startswith("images_"):
                images_cfg_kwargs[key[len("images_"):]] = kwargs.pop(key)
        images_cfg_kwargs = _accepted_kwargs(ImageExtractionConfig, images_cfg_kwargs)
        if images_cfg_kwargs:
            try:
                config_kwargs["images"] = ImageExtractionConfig(**images_cfg_kwargs)
            except Exception as e:
                logging.debug(
                    f"KreuzbergParser: failed to build ImageExtractionConfig: {e}"
                )

        # OCR configuration:
        # - modern API: ExtractionConfig.ocr = OcrConfig(...)
        # - table extraction commonly requires tesseract.enable_table_detection=True
        ocr_cfg_kwargs: Dict[str, Any] = {}
        if "ocr_provider" in kwargs:
            ocr_backend = kwargs.pop("ocr_provider")
            ocr_cfg_kwargs["provider"] = ocr_backend
            ocr_cfg_kwargs["backend"] = ocr_backend
        if "ocr_backend" in kwargs:
            ocr_backend = kwargs.pop("ocr_backend")
            ocr_cfg_kwargs["provider"] = ocr_backend
            ocr_cfg_kwargs["backend"] = ocr_backend
        if "ocr_languages" in kwargs:
            lang_values = _as_list(kwargs.pop("ocr_languages"))
            ocr_cfg_kwargs["languages"] = lang_values
            if lang_values:
                ocr_cfg_kwargs["language"] = lang_values[0]
        elif "ocr_langs" in kwargs:
            lang_values = _as_list(kwargs.pop("ocr_langs"))
            ocr_cfg_kwargs["languages"] = lang_values
            if lang_values:
                ocr_cfg_kwargs["language"] = lang_values[0]
        elif lang:
            lang_values = _as_list(lang)
            ocr_cfg_kwargs["languages"] = lang_values
            if lang_values:
                ocr_cfg_kwargs["language"] = lang_values[0]

        tesseract_cfg_kwargs: Dict[str, Any] = {}
        if "ocr_tesseract_enable_table_detection" in kwargs:
            tesseract_cfg_kwargs["enable_table_detection"] = kwargs.pop(
                "ocr_tesseract_enable_table_detection"
            )
        for key in list(kwargs.keys()):
            if key.startswith("ocr_tesseract_"):
                tesseract_cfg_kwargs[key[len("ocr_tesseract_"):]] = kwargs.pop(key)
        if extract_tables is True and "enable_table_detection" not in tesseract_cfg_kwargs:
            tesseract_cfg_kwargs["enable_table_detection"] = True

        tesseract_cfg_kwargs = _accepted_kwargs(TesseractConfig, tesseract_cfg_kwargs)
        if tesseract_cfg_kwargs and TesseractConfig is not None:
            try:
                tesseract_cfg = TesseractConfig(**tesseract_cfg_kwargs)
                ocr_cfg_kwargs["tesseract"] = tesseract_cfg
                ocr_cfg_kwargs["tesseract_config"] = tesseract_cfg
            except Exception as e:
                logging.debug(f"KreuzbergParser: failed to build TesseractConfig: {e}")

        # Generic ocr_* passthrough for newer fields while preserving known keys above.
        for key in list(kwargs.keys()):
            if key.startswith("ocr_"):
                bare = key[len("ocr_"):]
                if bare in {
                    "provider",
                    "backend",
                    "language",
                    "languages",
                    "langs",
                } or bare.startswith("tesseract_"):
                    continue
                ocr_cfg_kwargs[bare] = kwargs.pop(key)

        ocr_cfg_kwargs = _accepted_kwargs(OcrConfig, ocr_cfg_kwargs)
        if ocr_cfg_kwargs and OcrConfig is not None:
            try:
                config_kwargs["ocr"] = OcrConfig(**ocr_cfg_kwargs)
            except Exception as e:
                logging.debug(f"KreuzbergParser: failed to build OcrConfig: {e}")

        # Map string result format for modern API enums if available.
        if "result_format" in kwargs and ResultFormat is not None:
            rf_value = kwargs["result_format"]
            if isinstance(rf_value, str):
                rf_norm = rf_value.strip().lower()
                if rf_norm in {"element_based", "element-based", "elements", "element"}:
                    kwargs["result_format"] = getattr(ResultFormat, "ELEMENT_BASED", rf_value)
                elif rf_norm in {"unified", "default"}:
                    kwargs["result_format"] = getattr(ResultFormat, "UNIFIED", rf_value)

        # Forward any remaining kwargs that are valid for ExtractionConfig.
        extraction_extra_kwargs = _accepted_kwargs(ExtractionConfig, kwargs)
        config_kwargs.update(extraction_extra_kwargs)

        ignored_kwargs = sorted(set(kwargs.keys()) - set(extraction_extra_kwargs.keys()))
        if ignored_kwargs:
            logging.debug(
                f"KreuzbergParser ignored unsupported parser_kwargs: {ignored_kwargs}"
            )

        config = None
        if config_kwargs:
            try:
                config = ExtractionConfig(**config_kwargs)
            except TypeError as e:
                # Compatibility fallback for API/version differences:
                # retry without nested v4-only fields if constructor rejects them.
                retry_kwargs = dict(config_kwargs)
                dropped_keys: List[str] = []
                for key in ["pages", "pdf_options", "images", "ocr", "result_format"]:
                    if key in retry_kwargs:
                        retry_kwargs.pop(key, None)
                        dropped_keys.append(key)
                if retry_kwargs != config_kwargs:
                    logging.debug(
                        "KreuzbergParser fallback config without keys "
                        f"{dropped_keys} due to constructor mismatch: {e}"
                    )
                    config = ExtractionConfig(**retry_kwargs) if retry_kwargs else None
                else:
                    raise
        return extract_file_sync(file_path, config=config)

    def _tables_to_blocks(self, tables: Any) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        if not tables:
            return blocks
        for table in tables:
            if isinstance(table, dict):
                markdown = table.get("markdown") or table.get("md") or ""
                cells = table.get("cells") or table.get("data")
                page_num = (
                    table.get("page_number")
                    or table.get("pageNumber")
                    or table.get("page")
                    or 1
                )
            else:
                markdown = getattr(table, "markdown", "") or ""
                cells = getattr(table, "cells", None)
                page_num = (
                    getattr(table, "page_number", None)
                    or getattr(table, "pageNumber", None)
                    or getattr(table, "page", 1)
                )

            table_body = markdown if markdown else (cells if cells is not None else "")
            blocks.append(
                {
                    "type": "table",
                    "table_body": table_body,
                    "table_caption": [],
                    "table_footnote": [],
                    "page_idx": max(int(page_num) - 1, 0) if page_num else 0,
                }
            )
        return blocks

    @staticmethod
    def _normalize_kreuzberg_type(raw_type: Any) -> str:
        if raw_type is None:
            return ""
        normalized = str(raw_type).strip().lower()
        if "." in normalized:
            normalized = normalized.split(".")[-1]
        return normalized.replace("-", "_")

    @staticmethod
    def _image_ext_from_format(image_format: Any) -> Optional[str]:
        if image_format is None:
            return None
        fmt = str(image_format).strip().lower().replace(".", "")
        mapping = {
            "jpg": "jpg",
            "jpeg": "jpg",
            "png": "png",
            "gif": "gif",
            "webp": "webp",
            "bmp": "bmp",
            "tif": "tif",
            "tiff": "tif",
            "jp2": "jp2",
            "jpx": "jpx",
            "ppm": "ppm",
            "pgm": "pgm",
            "pbm": "pbm",
            "pnm": "pnm",
            "flate": "flate",
            "flatedecode": "flate",
        }
        return mapping.get(fmt)

    @staticmethod
    def _detect_image_ext_from_bytes(data: bytes) -> Optional[str]:
        if not data:
            return None
        signatures = [
            (b"\x89PNG\r\n\x1a\n", "png"),
            (b"\xff\xd8\xff", "jpg"),
            (b"GIF87a", "gif"),
            (b"GIF89a", "gif"),
            (b"RIFF", "webp"),  # needs WEBP marker check
            (b"BM", "bmp"),
            (b"II*\x00", "tif"),
            (b"MM\x00*", "tif"),
        ]
        for sig, ext in signatures:
            if data.startswith(sig):
                if ext == "webp" and len(data) >= 12 and data[8:12] != b"WEBP":
                    continue
                return ext
        return None

    @staticmethod
    def _coerce_to_bytes(value: Any) -> Optional[bytes]:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, memoryview):
            return value.tobytes()
        if isinstance(value, str):
            # Some APIs return base64 encoded payload strings.
            try:
                decoded = base64.b64decode(value, validate=True)
                if decoded:
                    return decoded
            except Exception:
                pass
        return None

    def _raw_raster_to_png(
        self,
        raw_pixels: bytes,
        width: Optional[int],
        height: Optional[int],
        color_space: Optional[str] = None,
        bits_per_component: Optional[int] = None,
    ) -> Optional[bytes]:
        if not raw_pixels or not width or not height:
            return None
        if width <= 0 or height <= 0:
            return None

        pixel_count = width * height
        if pixel_count <= 0:
            return None

        bpc = bits_per_component or 8
        mode = None
        if color_space:
            cs = str(color_space).lower()
            if "gray" in cs:
                mode = "L"
            elif "rgb" in cs:
                mode = "RGB"
            elif "cmyk" in cs:
                mode = "CMYK"

        # Heuristic fallback if colorspace is unavailable.
        if mode is None:
            if len(raw_pixels) == pixel_count:
                mode = "L"
            elif len(raw_pixels) == pixel_count * 3:
                mode = "RGB"
            elif len(raw_pixels) == pixel_count * 4:
                mode = "RGBA"

        if mode is None:
            return None

        try:
            from PIL import Image
            from io import BytesIO
        except Exception:
            return None

        try:
            if mode == "L" and bpc == 1:
                expected = ((width + 7) // 8) * height
                if len(raw_pixels) != expected:
                    return None
                image = Image.frombytes("1", (width, height), raw_pixels)
            else:
                if bpc != 8:
                    return None
                expected = {
                    "L": pixel_count,
                    "RGB": pixel_count * 3,
                    "RGBA": pixel_count * 4,
                    "CMYK": pixel_count * 4,
                }.get(mode)
                if expected is None or len(raw_pixels) != expected:
                    return None
                image = Image.frombytes(mode, (width, height), raw_pixels)

            if image.mode == "CMYK":
                image = image.convert("RGB")

            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception:
            return None

    def _decode_image_payload(
        self,
        data: bytes,
        image_format: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        color_space: Optional[str] = None,
        bits_per_component: Optional[int] = None,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        if not data:
            return None, None

        detected_ext = self._detect_image_ext_from_bytes(data)
        if detected_ext:
            return data, detected_ext

        fmt_ext = self._image_ext_from_format(image_format)
        if fmt_ext and fmt_ext != "flate":
            # Not all formats have strong magic bytes, trust declared format.
            return data, fmt_ext

        # Handle raw PDF FlateDecode streams.
        try:
            inflated = zlib.decompress(data)
        except Exception:
            return None, None

        inflated_ext = self._detect_image_ext_from_bytes(inflated)
        if inflated_ext:
            return inflated, inflated_ext

        png_bytes = self._raw_raster_to_png(
            inflated,
            width=width,
            height=height,
            color_space=color_space,
            bits_per_component=bits_per_component,
        )
        if png_bytes:
            return png_bytes, "png"

        return None, None

    def _images_to_blocks(
        self,
        images: Any,
        output_dir: Optional[Path],
        default_page_idx: int = 0,
    ) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        if not images:
            return blocks
        if output_dir is None:
            return blocks
        images_output_dir = output_dir / "images"
        images_output_dir.mkdir(parents=True, exist_ok=True)

        def _to_int(value: Any) -> Optional[int]:
            if value is None:
                return None
            try:
                return int(value)
            except Exception:
                return None

        def _parse_dims_from_text(value: Any) -> Tuple[Optional[int], Optional[int]]:
            if value is None:
                return None, None
            match = re.search(r"(\d+)\s*[xX]\s*(\d+)", str(value))
            if not match:
                return None, None
            return _to_int(match.group(1)), _to_int(match.group(2))

        for idx, img in enumerate(images):
            img_path = None
            page_num = None
            image_format = None
            width = None
            height = None
            color_space = None
            bits_per_component = None
            if isinstance(img, dict):
                metadata = img.get("metadata", {}) if isinstance(img.get("metadata"), dict) else {}
                img_path = (
                    img.get("path")
                    or img.get("file_path")
                    or img.get("filePath")
                    or metadata.get("path")
                    or metadata.get("file_path")
                    or metadata.get("filePath")
                )
                data = (
                    img.get("data")
                    or img.get("bytes")
                    or img.get("image_data")
                    or img.get("imageData")
                    or metadata.get("data")
                    or metadata.get("bytes")
                    or metadata.get("image_data")
                    or metadata.get("imageData")
                )
                page_num = (
                    img.get("page_number")
                    or img.get("pageNumber")
                    or img.get("page")
                    or metadata.get("page_number")
                    or metadata.get("pageNumber")
                    or metadata.get("page")
                )
                image_format = (
                    img.get("format")
                    or img.get("image_format")
                    or img.get("imageFormat")
                    or metadata.get("format")
                    or metadata.get("image_format")
                    or metadata.get("imageFormat")
                )
                width = (
                    img.get("width")
                    or img.get("image_width")
                    or img.get("imageWidth")
                    or metadata.get("width")
                    or metadata.get("image_width")
                    or metadata.get("imageWidth")
                )
                height = (
                    img.get("height")
                    or img.get("image_height")
                    or img.get("imageHeight")
                    or metadata.get("height")
                    or metadata.get("image_height")
                    or metadata.get("imageHeight")
                )
                color_space = (
                    img.get("color_space")
                    or img.get("colorspace")
                    or img.get("colorSpace")
                    or metadata.get("color_space")
                    or metadata.get("colorspace")
                    or metadata.get("colorSpace")
                )
                bits_per_component = (
                    img.get("bits_per_component")
                    or img.get("bitsPerComponent")
                    or img.get("bpc")
                    or metadata.get("bits_per_component")
                    or metadata.get("bitsPerComponent")
                    or metadata.get("bpc")
                )
                size = img.get("size") or metadata.get("size")
                if isinstance(size, dict):
                    width = width or size.get("width")
                    height = height or size.get("height")
                dimensions = img.get("dimensions") or metadata.get("dimensions")
                if isinstance(dimensions, (list, tuple)) and len(dimensions) >= 2:
                    width = width or dimensions[0]
                    height = height or dimensions[1]
            else:
                metadata = getattr(img, "metadata", None)
                img_path = (
                    getattr(img, "path", None)
                    or getattr(img, "file_path", None)
                    or getattr(img, "filePath", None)
                    or getattr(metadata, "path", None)
                    or getattr(metadata, "file_path", None)
                    or getattr(metadata, "filePath", None)
                )
                data = (
                    getattr(img, "data", None)
                    or getattr(img, "bytes", None)
                    or getattr(img, "image_data", None)
                    or getattr(img, "imageData", None)
                    or getattr(metadata, "data", None)
                    or getattr(metadata, "bytes", None)
                    or getattr(metadata, "image_data", None)
                    or getattr(metadata, "imageData", None)
                )
                page_num = (
                    getattr(img, "page_number", None)
                    or getattr(img, "pageNumber", None)
                    or getattr(img, "page", None)
                    or getattr(metadata, "page_number", None)
                    or getattr(metadata, "pageNumber", None)
                    or getattr(metadata, "page", None)
                )
                image_format = (
                    getattr(img, "format", None)
                    or getattr(img, "image_format", None)
                    or getattr(img, "imageFormat", None)
                    or getattr(metadata, "format", None)
                    or getattr(metadata, "image_format", None)
                    or getattr(metadata, "imageFormat", None)
                )
                width = (
                    getattr(img, "width", None)
                    or getattr(img, "image_width", None)
                    or getattr(img, "imageWidth", None)
                    or getattr(metadata, "width", None)
                    or getattr(metadata, "image_width", None)
                    or getattr(metadata, "imageWidth", None)
                )
                height = (
                    getattr(img, "height", None)
                    or getattr(img, "image_height", None)
                    or getattr(img, "imageHeight", None)
                    or getattr(metadata, "height", None)
                    or getattr(metadata, "image_height", None)
                    or getattr(metadata, "imageHeight", None)
                )
                color_space = (
                    getattr(img, "color_space", None)
                    or getattr(img, "colorspace", None)
                    or getattr(img, "colorSpace", None)
                    or getattr(metadata, "color_space", None)
                    or getattr(metadata, "colorspace", None)
                    or getattr(metadata, "colorSpace", None)
                )
                bits_per_component = (
                    getattr(img, "bits_per_component", None)
                    or getattr(img, "bitsPerComponent", None)
                    or getattr(img, "bpc", None)
                    or getattr(metadata, "bits_per_component", None)
                    or getattr(metadata, "bitsPerComponent", None)
                    or getattr(metadata, "bpc", None)
                )
                size = getattr(img, "size", None) or getattr(metadata, "size", None)
                if isinstance(size, dict):
                    width = width or size.get("width")
                    height = height or size.get("height")
                dimensions = getattr(img, "dimensions", None) or getattr(metadata, "dimensions", None)
                if isinstance(dimensions, (list, tuple)) and len(dimensions) >= 2:
                    width = width or dimensions[0]
                    height = height or dimensions[1]

            width_int = _to_int(width)
            height_int = _to_int(height)
            if width_int is None or height_int is None:
                parsed_w, parsed_h = _parse_dims_from_text(image_format)
                width_int = width_int or parsed_w
                height_int = height_int or parsed_h

            page_idx = (
                max(int(page_num) - 1, 0) if page_num is not None else default_page_idx
            )

            if img_path and os.path.exists(img_path):
                src = Path(img_path)
                suffix = src.suffix.lower().lstrip(".")
                digest = hashlib.md5(str(src.resolve()).encode("utf-8")).hexdigest()[:12]
                ext = suffix if suffix else (self._image_ext_from_format(image_format) or "bin")
                out_path = images_output_dir / f"p{page_idx + 1}_{idx}_{digest}.{ext}"
                try:
                    if src.resolve() != out_path.resolve():
                        shutil.copy2(src, out_path)
                    else:
                        out_path = src
                    blocks.append(
                        {
                            "type": "image",
                            "img_path": str(out_path.resolve()),
                            "image_caption": [],
                            "image_footnote": [],
                            "page_idx": page_idx,
                        }
                    )
                except Exception:
                    pass
                continue

            if data:
                try:
                    raw_data = self._coerce_to_bytes(data)
                    if raw_data is None:
                        continue
                    decoded_bytes, ext = self._decode_image_payload(
                        raw_data,
                        image_format=str(image_format) if image_format is not None else None,
                        width=width_int,
                        height=height_int,
                        color_space=str(color_space) if color_space is not None else None,
                        bits_per_component=_to_int(bits_per_component),
                    )
                    if decoded_bytes is None:
                        logging.debug(
                            "KreuzbergParser: unable to decode image payload "
                            f"(format={image_format}, width={width}, height={height})"
                        )
                        continue
                    ext = ext or "bin"
                    digest = hashlib.md5(decoded_bytes).hexdigest()[:12]
                    out_path = images_output_dir / f"p{page_idx + 1}_{idx}_{digest}.{ext}"
                    with open(out_path, "wb") as f:
                        f.write(decoded_bytes)
                    blocks.append(
                        {
                            "type": "image",
                            "img_path": str(out_path.resolve()),
                            "image_caption": [],
                            "image_footnote": [],
                            "page_idx": page_idx,
                        }
                    )
                except Exception:
                    pass

        return blocks

    def _result_to_content_list(
        self, result: Any, output_dir: Optional[Path]
    ) -> List[Dict[str, Any]]:
        content_list: List[Dict[str, Any]] = []
        seen_image_keys = set()
        seen_table_keys = set()
        seen_text_keys = set()

        def _get(obj: Any, *keys: str) -> Any:
            for key in keys:
                if isinstance(obj, dict) and key in obj:
                    return obj.get(key)
                value = getattr(obj, key, None)
                if value is not None:
                    return value
            return None

        def _append_text(text: Any, page_idx: int):
            if text is None:
                return
            for block in _split_text_blocks(str(text)):
                normalized = block.strip()
                if not normalized:
                    continue
                key = (page_idx, normalized)
                if key in seen_text_keys:
                    continue
                seen_text_keys.add(key)
                content_list.append(
                    {"type": "text", "text": normalized, "page_idx": page_idx}
                )

        def _append_tables(tables: Any):
            if not tables:
                return
            for block in self._tables_to_blocks(tables):
                key = (block.get("page_idx", 0), str(block.get("table_body", "")))
                if key in seen_table_keys:
                    continue
                seen_table_keys.add(key)
                content_list.append(block)

        def _append_images(images: Any, page_idx: int = 0):
            if not images:
                return
            for block in self._images_to_blocks(
                images, output_dir=output_dir, default_page_idx=page_idx
            ):
                img_path = block.get("img_path", "")
                key = img_path or f"page-{block.get('page_idx', 0)}-{len(seen_image_keys)}"
                if key in seen_image_keys:
                    continue
                seen_image_keys.add(key)
                content_list.append(block)

        def _append_elements(elements: Any, include_text_fallback: bool):
            if not elements:
                return
            for element in elements:
                raw_type = _get(element, "type", "element_type", "elementType", "category")
                element_type = self._normalize_kreuzberg_type(raw_type)
                page_num = _get(element, "page_number", "pageNumber", "page")
                if page_num is None:
                    metadata = _get(element, "metadata")
                    page_num = _get(metadata, "page_number", "pageNumber", "page")
                page_idx = max(int(page_num) - 1, 0) if page_num else 0

                # Table-like elements
                if "table" in element_type:
                    table_body = (
                        _get(element, "markdown", "html", "content", "text")
                        or _get(element, "cells", "data")
                        or ""
                    )
                    _append_tables(
                        [
                            {
                                "markdown": table_body if isinstance(table_body, str) else "",
                                "cells": table_body if not isinstance(table_body, str) else None,
                                "page_number": (page_idx + 1),
                            }
                        ]
                    )
                    continue

                # Image-like elements
                if any(token in element_type for token in ["image", "figure", "picture"]):
                    before = len(content_list)
                    _append_images([element], page_idx=page_idx)
                    if len(content_list) > before:
                        continue

                # Skip structural markers (e.g. page breaks) from element streams.
                if element_type in {
                    "page_break",
                    "pagebreak",
                    "line_break",
                    "linebreak",
                    "separator",
                }:
                    continue

                if not include_text_fallback:
                    continue

                # Generic textual element fallback
                text = (
                    _get(element, "content", "text", "markdown", "html", "value")
                    or ""
                )
                _append_text(text, page_idx=page_idx)

        pages = getattr(result, "pages", None) or (
            result.get("pages") if isinstance(result, dict) else None
        )
        if pages:
            for page in pages:
                page_num = getattr(page, "page_number", None)
                if page_num is None and isinstance(page, dict):
                    page_num = page.get("page_number") or page.get("page") or 1
                page_idx = max(int(page_num) - 1, 0) if page_num else 0

                page_text = (
                    getattr(page, "content", None)
                    or (page.get("content") if isinstance(page, dict) else None)
                    or ""
                )
                _append_text(page_text, page_idx=page_idx)

                page_tables = (
                    getattr(page, "tables", None)
                    or (page.get("tables") if isinstance(page, dict) else None)
                    or []
                )
                _append_tables(page_tables)

                page_images = (
                    getattr(page, "images", None)
                    or (page.get("images") if isinstance(page, dict) else None)
                    or []
                )
                _append_images(page_images, page_idx=page_idx)

        elements = _get(result, "elements")
        # If page-level text is available, avoid duplicating it from element stream.
        _append_elements(elements, include_text_fallback=not bool(pages))

        # Also merge top-level modalities because some Kreuzberg outputs expose
        # images/tables at root even when pages are present.
        tables = _get(result, "tables")
        _append_tables(tables)

        images = _get(result, "images")
        _append_images(images, page_idx=0)

        if content_list:
            return content_list

        # Fallback: use whole-document text if page-level structure is unavailable.
        doc_text = (
            _get(result, "content", "markdown", "text")
            or ""
        )
        _append_text(doc_text, page_idx=0)
        return content_list

    @staticmethod
    def _serialize_kreuzberg_obj(obj: Any) -> Any:
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, (bytes, bytearray)):
            return {"__bytes__": len(obj)}
        if isinstance(obj, dict):
            return {
                str(k): KreuzbergParser._serialize_kreuzberg_obj(v)
                for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple, set)):
            return [KreuzbergParser._serialize_kreuzberg_obj(v) for v in obj]
        try:
            import dataclasses

            if dataclasses.is_dataclass(obj):
                return KreuzbergParser._serialize_kreuzberg_obj(dataclasses.asdict(obj))
        except Exception:
            pass
        try:
            payload = vars(obj)
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload:
            return {
                str(k): KreuzbergParser._serialize_kreuzberg_obj(v)
                for k, v in payload.items()
                if not str(k).startswith("_")
            }
        return str(obj)

    def _write_kreuzberg_output_artifacts(
        self,
        result: Any,
        content_list: List[Dict[str, Any]],
        base_output_dir: Path,
        file_stem: str,
    ) -> None:
        """
        Persist lightweight parser artifacts so Kreuzberg benchmark output is inspectable
        in the same way as MinerU/Docling runs.
        """
        artifact_dir = base_output_dir / file_stem / "kreuzberg"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        md_content = (
            getattr(result, "content", None)
            or (result.get("content") if isinstance(result, dict) else None)
            or ""
        )
        with open(artifact_dir / f"{file_stem}.md", "w", encoding="utf-8") as f:
            f.write(str(md_content))

        with open(
            artifact_dir / f"{file_stem}_content_list.json", "w", encoding="utf-8"
        ) as f:
            json.dump(content_list, f, ensure_ascii=False, indent=2)

        result_payload = {
            "content": md_content,
            "pages": self._serialize_kreuzberg_obj(
                getattr(result, "pages", None)
                or (result.get("pages") if isinstance(result, dict) else None)
            ),
            "tables": self._serialize_kreuzberg_obj(
                getattr(result, "tables", None)
                or (result.get("tables") if isinstance(result, dict) else None)
            ),
            "images": self._serialize_kreuzberg_obj(
                getattr(result, "images", None)
                or (result.get("images") if isinstance(result, dict) else None)
            ),
            "elements": self._serialize_kreuzberg_obj(
                getattr(result, "elements", None)
                or (result.get("elements") if isinstance(result, dict) else None)
            ),
            "metadata": self._serialize_kreuzberg_obj(
                getattr(result, "metadata", None)
                or (result.get("metadata") if isinstance(result, dict) else None)
            ),
        }
        with open(artifact_dir / f"{file_stem}_raw_result.json", "w", encoding="utf-8") as f:
            json.dump(result_payload, f, ensure_ascii=False, indent=2)

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        base_output_dir = Path(output_dir) if output_dir else file_path.parent / "kreuzberg_output"
        base_output_dir.mkdir(parents=True, exist_ok=True)

        result = self._extract_with_kreuzberg(
            str(file_path), method=method, lang=lang, **kwargs
        )
        content_list = self._result_to_content_list(result, base_output_dir)
        self._write_kreuzberg_output_artifacts(
            result=result,
            content_list=content_list,
            base_output_dir=base_output_dir,
            file_stem=file_path.stem,
        )
        return content_list

    def parse_pdf(self, pdf_path: Union[str, Path], output_dir: Optional[str] = None, method: str = "auto", lang: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        return self.parse_document(pdf_path, method=method, output_dir=output_dir, lang=lang, **kwargs)

    def parse_image(self, image_path: Union[str, Path], output_dir: Optional[str] = None, lang: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        return self.parse_document(image_path, method="ocr", output_dir=output_dir, lang=lang, **kwargs)

    def parse_office_doc(self, doc_path: Union[str, Path], output_dir: Optional[str] = None, lang: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        return self.parse_document(doc_path, method="auto", output_dir=output_dir, lang=lang, **kwargs)

    def check_installation(self) -> bool:
        try:
            import importlib

            importlib.import_module("kreuzberg")
            return True
        except Exception:
            return False


class MarkerParser(Parser):
    """
    Marker PDF/Image parser (VLM-based document conversion).

    Converts rendered output to RAGAnything content_list.
    """

    def __init__(self) -> None:
        super().__init__()

    def _build_marker_converter(self, method: str = "auto", **kwargs):
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.config.parser import ConfigParser
            from marker.output import text_from_rendered
        except Exception as e:
            raise RuntimeError(
                "Marker is not installed. Install with: pip install -U marker-pdf"
            ) from e

        config = kwargs.pop("marker_config", None)
        config_parser = ConfigParser(config) if config else None

        converter_cls = PdfConverter
        if method == "ocr":
            try:
                from marker.converters.ocr import OCRConverter

                converter_cls = OCRConverter
            except Exception:
                converter_cls = PdfConverter

        if config_parser:
            converter = converter_cls(
                config=config_parser.generate_config_dict(),
                artifact_dict=create_model_dict(),
                processor_list=config_parser.get_processors(),
                renderer=config_parser.get_renderer(),
                llm_service=config_parser.get_llm_service(),
            )
        else:
            converter = converter_cls(artifact_dict=create_model_dict())

        return converter, text_from_rendered

    def _images_to_blocks(self, images: Any, output_dir: Optional[Path]) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        if not images or output_dir is None:
            return blocks
        output_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(images, dict):
            items = images.items()
        else:
            items = enumerate(images)

        for idx, img in items:
            img_obj = img[1] if isinstance(img, tuple) else img
            img_path = None

            if isinstance(img_obj, str) and os.path.exists(img_obj):
                img_path = img_obj
            elif hasattr(img_obj, "save"):
                out_path = output_dir / f"image_{idx}.png"
                try:
                    img_obj.save(out_path)
                    img_path = str(out_path.resolve())
                except Exception:
                    img_path = None
            elif isinstance(img_obj, (bytes, bytearray)):
                out_path = output_dir / f"image_{idx}.png"
                try:
                    with open(out_path, "wb") as f:
                        f.write(img_obj)
                    img_path = str(out_path.resolve())
                except Exception:
                    img_path = None

            if img_path:
                blocks.append(
                    {
                        "type": "image",
                        "img_path": img_path,
                        "image_caption": [],
                        "image_footnote": [],
                        "page_idx": 0,
                    }
                )

        return blocks

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        base_output_dir = Path(output_dir) if output_dir else file_path.parent / "marker_output"
        base_output_dir.mkdir(parents=True, exist_ok=True)

        converter, text_from_rendered = self._build_marker_converter(method=method, **kwargs)
        rendered = converter(str(file_path))
        text, _, images = text_from_rendered(rendered)

        content_list: List[Dict[str, Any]] = []
        for block in _split_text_blocks(text):
            content_list.append({"type": "text", "text": block, "page_idx": 0})

        content_list.extend(self._images_to_blocks(images, base_output_dir / "images"))
        return content_list

    def parse_pdf(self, pdf_path: Union[str, Path], output_dir: Optional[str] = None, method: str = "auto", lang: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        return self.parse_document(pdf_path, method=method, output_dir=output_dir, lang=lang, **kwargs)

    def parse_image(self, image_path: Union[str, Path], output_dir: Optional[str] = None, lang: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        return self.parse_document(image_path, method="ocr", output_dir=output_dir, lang=lang, **kwargs)

    def parse_office_doc(self, doc_path: Union[str, Path], output_dir: Optional[str] = None, lang: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        raise ValueError("Marker does not support Office documents directly. Convert to PDF first.")

    def check_installation(self) -> bool:
        try:
            import importlib

            importlib.import_module("marker")
            return True
        except Exception:
            return False


def main():
    """
    Main function to run the document parser from command line
    """
    parser = argparse.ArgumentParser(
        description="Parse documents using MinerU 2.0, Docling, or PaddleOCR"
    )
    parser.add_argument("file_path", help="Path to the document to parse")
    parser.add_argument("--output", "-o", help="Output directory path")
    parser.add_argument(
        "--method",
        "-m",
        choices=["auto", "txt", "ocr"],
        default="auto",
        help="Parsing method (auto, txt, ocr)",
    )
    parser.add_argument(
        "--lang",
        "-l",
        help="Document language for OCR optimization (e.g., ch, en, ja)",
    )
    parser.add_argument(
        "--backend",
        "-b",
        choices=[
            "pipeline",
            "hybrid-auto-engine",
            "hybrid-http-client",
            "vlm-auto-engine",
            "vlm-http-client",
        ],
        default="pipeline",
        help="Parsing backend",
    )
    parser.add_argument(
        "--device",
        "-d",
        help="Inference device (e.g., cpu, cuda, cuda:0, npu, mps)",
    )
    parser.add_argument(
        "--source",
        choices=["huggingface", "modelscope", "local"],
        default="huggingface",
        help="Model source",
    )
    parser.add_argument(
        "--no-formula",
        action="store_true",
        help="Disable formula parsing",
    )
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="Disable table parsing",
    )
    parser.add_argument(
        "--stats", action="store_true", help="Display content statistics"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check parser installation",
    )
    parser.add_argument(
        "--parser",
        choices=["mineru", "mineru_cloud", "docling", "kreuzberg", "marker"],
        default="mineru",
        help=(
            "Parser selection. Built-ins: mineru, docling, paddleocr. "
            "Custom parsers registered via register_parser() in the same "
            "Python process are also accepted when you integrate RAGAnything "
            "as a library. The standalone CLI itself only sees parsers that "
            "have already been registered in this process."
        ),
    )
    parser.add_argument(
        "--vlm_url",
        help="When the backend is `vlm-http-client`, you need to specify the server_url, for example:`http://127.0.0.1:30000`",
    )

    args = parser.parse_args()

    # Check installation if requested
    if args.check:
        if args.parser == "docling":
            doc_parser = DoclingParser()
        elif args.parser == "mineru_cloud":
            from raganything.mineru_cloud import MineruCloudParser

            doc_parser = MineruCloudParser()
        elif args.parser == "kreuzberg":
            doc_parser = KreuzbergParser()
        elif args.parser == "marker":
            doc_parser = MarkerParser()
        else:
            doc_parser = MineruParser()
        if doc_parser.check_installation():
            print(f"✅ {args.parser.title()} is properly installed")
            return 0
        else:
            print(f"❌ {args.parser.title()} installation check failed")
            return 1

    try:
        # Parse the document
        if args.parser == "docling":
            doc_parser = DoclingParser()
        elif args.parser == "mineru_cloud":
            from raganything.mineru_cloud import MineruCloudParser

            doc_parser = MineruCloudParser()
        elif args.parser == "kreuzberg":
            doc_parser = KreuzbergParser()
        elif args.parser == "marker":
            doc_parser = MarkerParser()
        else:
            doc_parser = MineruParser()
        content_list = doc_parser.parse_document(
            file_path=args.file_path,
            method=args.method,
            output_dir=args.output,
            lang=args.lang,
            backend=args.backend,
            device=args.device,
            source=args.source,
            formula=not args.no_formula,
            table=not args.no_table,
            vlm_url=args.vlm_url,
        )

        print(f"✅ Successfully parsed: {args.file_path}")
        print(f"📊 Extracted {len(content_list)} content blocks")

        # Display statistics if requested
        if args.stats:
            print("\n📈 Document Statistics:")
            print(f"Total content blocks: {len(content_list)}")

            # Count different types of content
            content_types = {}
            for item in content_list:
                if isinstance(item, dict):
                    content_type = item.get("type", "unknown")
                    content_types[content_type] = content_types.get(content_type, 0) + 1

            if content_types:
                print("\n📋 Content Type Distribution:")
                for content_type, count in sorted(content_types.items()):
                    print(f"  • {content_type}: {count}")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
