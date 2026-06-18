# type: ignore
"""
Generic Document Parser Utility

This module provides functionality for parsing documents using the built-in
MinerU, Docling, Marker, and PaddleOCR parsers, and exposes a small registry for
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
import subprocess
import tempfile
import threading
import logging
import time
import urllib.parse
import urllib.request
import shutil
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
                # Windows: LibreOffice is NOT added to PATH by default, add explicit paths
                if _IS_WINDOWS:
                    # Insert explicit paths at the front so they are tried first.
                    # Iterate in reverse so that the 64-bit entry ends up before the
                    # 32-bit entry after repeated insert(0, …).
                    for lo_path in reversed([
                        r"C:\Program Files\LibreOffice\program\soffice.exe",
                        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                    ]):
                        if os.path.exists(lo_path):
                            commands_to_try.insert(0, lo_path)

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

                final_pdf_path = base_output_dir / f"{name_without_suff}.pdf"

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

    # _process_inline_markdown removed — unused dead code (33 lines, zero callers)

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
