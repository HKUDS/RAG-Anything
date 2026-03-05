# type: ignore
"""
Generic Document Parser Utility

This module provides functionality for parsing PDF and image documents using MinerU 2.0 library,
and converts the parsing results into markdown and JSON formats

Note: MinerU 2.0 no longer includes LibreOffice document conversion module.
For Office documents (.doc, .docx, .ppt, .pptx), please convert them to PDF format first.
"""

from __future__ import annotations


import json
import argparse
import base64
import hashlib
import subprocess
import tempfile
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
    TypeVar,
)

T = TypeVar("T")


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

    def __init__(self) -> None:
        """Initialize the base parser."""
        pass

    @staticmethod
    def convert_office_to_pdf(
        doc_path: Union[str, Path], output_dir: Optional[str] = None
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
                logging.info(f"Converting {doc_path.name} to PDF using LibreOffice...")

                # Prepare subprocess parameters to hide console window on Windows
                import platform

                # Try LibreOffice commands in order of preference
                commands_to_try = ["libreoffice", "soffice"]

                conversion_successful = False
                for cmd in commands_to_try:
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
                        if platform.system() == "Windows":
                            convert_subprocess_kwargs["creationflags"] = (
                                subprocess.CREATE_NO_WINDOW
                            )

                        result = subprocess.run(
                            convert_cmd, **convert_subprocess_kwargs
                        )

                        if result.returncode == 0:
                            conversion_successful = True
                            logging.info(
                                f"Successfully converted {doc_path.name} to PDF using {cmd}"
                            )
                            break
                        else:
                            logging.warning(
                                f"LibreOffice command '{cmd}' failed: {result.stderr}"
                            )
                    except FileNotFoundError:
                        logging.warning(f"LibreOffice command '{cmd}' not found")
                    except subprocess.TimeoutExpired:
                        logging.warning(f"LibreOffice command '{cmd}' timed out")
                    except Exception as e:
                        logging.error(
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
                logging.info(
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
            logging.error(f"Error in convert_office_to_pdf: {str(e)}")
            raise

    @staticmethod
    def convert_text_to_pdf(
        text_path: Union[str, Path], output_dir: Optional[str] = None
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
                        logging.info(f"Successfully read file with {encoding} encoding")
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
            logging.info(f"Converting {text_path.name} to PDF...")

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
                            logging.warning(
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
                    logging.warning(
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
                try:
                    # Try to use system fonts that support Chinese
                    import platform

                    system = platform.system()
                    if system == "Windows":
                        # Try common Windows fonts
                        for font_name in ["SimSun", "SimHei", "Microsoft YaHei"]:
                            try:
                                from reportlab.pdfbase.cidfonts import (
                                    UnicodeCIDFont,
                                )

                                pdfmetrics.registerFont(UnicodeCIDFont(font_name))
                                normal_style.fontName = font_name
                                heading_style.fontName = font_name
                                break
                            except Exception:
                                continue
                    elif system == "Darwin":  # macOS
                        for font_name in ["STSong-Light", "STHeiti"]:
                            try:
                                from reportlab.pdfbase.cidfonts import (
                                    UnicodeCIDFont,
                                )

                                pdfmetrics.registerFont(UnicodeCIDFont(font_name))
                                normal_style.fontName = font_name
                                heading_style.fontName = font_name
                                break
                            except Exception:
                                continue
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
                    logging.info(
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

                    logging.info(f"Added {line_count} lines to PDF")

                    # If no content was added, add a placeholder
                    if not story:
                        story.append(Paragraph("(Empty text file)", normal_style))

                # Build PDF
                doc.build(story)
                logging.info(
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
            logging.error(f"Error in convert_text_to_pdf: {str(e)}")
            raise

    @staticmethod
    def _process_inline_markdown(text: str) -> str:
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

    @staticmethod
    def _run_mineru_command(
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
            vlm_url: When the backend is `vlm-sglang-client`, you need to specify the server_url
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

        try:
            # Prepare subprocess parameters to hide console window on Windows
            import platform
            import threading
            from queue import Queue, Empty

            # Log the command being executed
            logging.info(f"Executing mineru command: {' '.join(cmd)}")

            subprocess_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "ignore",
                "bufsize": 1,  # Line buffered
            }

            # Hide console window on Windows
            if platform.system() == "Windows":
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
            while process.poll() is None:
                # Check stdout queue
                try:
                    while True:
                        prefix, line = stdout_queue.get_nowait()
                        output_lines.append(line)
                        # Log mineru output with INFO level, prefixed with [MinerU]
                        logging.info(f"[MinerU] {line}")
                except Empty:
                    pass

                # Check stderr queue
                try:
                    while True:
                        prefix, line = stderr_queue.get_nowait()
                        # Log mineru errors with WARNING level
                        if "warning" in line.lower():
                            logging.warning(f"[MinerU] {line}")
                        elif "error" in line.lower():
                            logging.error(f"[MinerU] {line}")
                            error_message = line.split("\n")[0]
                            error_lines.append(error_message)
                        else:
                            logging.info(f"[MinerU] {line}")
                except Empty:
                    pass

                # Small delay to prevent busy waiting
                import time

                time.sleep(0.1)

            # Process any remaining output after process completion
            try:
                while True:
                    prefix, line = stdout_queue.get_nowait()
                    output_lines.append(line)
                    logging.info(f"[MinerU] {line}")
            except Empty:
                pass

            try:
                while True:
                    prefix, line = stderr_queue.get_nowait()
                    if "warning" in line.lower():
                        logging.warning(f"[MinerU] {line}")
                    elif "error" in line.lower():
                        logging.error(f"[MinerU] {line}")
                        error_message = line.split("\n")[0]
                        error_lines.append(error_message)
                    else:
                        logging.info(f"[MinerU] {line}")
            except Empty:
                pass

            # Wait for process to complete and get return code
            return_code = process.wait()

            # Wait for threads to finish
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)

            if return_code != 0 or error_lines:
                logging.info("[MinerU] Command executed failed")
                raise MineruExecutionError(return_code, error_lines)
            else:
                logging.info("[MinerU] Command executed successfully")

        except MineruExecutionError:
            raise
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running mineru subprocess command: {e}")
            logging.error(f"Command: {' '.join(cmd)}")
            logging.error(f"Return code: {e.returncode}")
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "mineru command not found. Please ensure MinerU 2.0 is properly installed:\n"
                "pip install -U 'mineru[core]' or uv pip install -U 'mineru[core]'"
            )
        except Exception as e:
            error_message = f"Unexpected error running mineru command: {e}"
            logging.error(error_message)
            raise RuntimeError(error_message) from e

    @staticmethod
    def _read_output_files(
        output_dir: Path, file_stem: str, method: str = "auto"
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Read the output files generated by mineru

        Args:
            output_dir: Output directory
            file_stem: File name without extension

        Returns:
            Tuple containing (content list JSON, Markdown text)
        """
        # Look for the generated files
        md_file = output_dir / f"{file_stem}.md"
        json_file = output_dir / f"{file_stem}_content_list.json"
        images_base_dir = output_dir  # Base directory for images

        file_stem_subdir = output_dir / file_stem
        if file_stem_subdir.exists():
            md_file = file_stem_subdir / method / f"{file_stem}.md"
            json_file = file_stem_subdir / method / f"{file_stem}_content_list.json"
            images_base_dir = file_stem_subdir / method

        # Read markdown content
        md_content = ""
        if md_file.exists():
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception as e:
                logging.warning(f"Could not read markdown file {md_file}: {e}")

        # Read JSON content list
        content_list = []
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    content_list = json.load(f)

                # Always fix relative paths in content_list to absolute paths
                logging.info(
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
                                item[field_name] = str(absolute_img_path)
                                logging.debug(
                                    f"Updated {field_name}: {img_path} -> {item[field_name]}"
                                )

            except Exception as e:
                logging.warning(f"Could not read JSON file {json_file}: {e}")

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

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
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
            backend = kwargs.get("backend", "")
            if backend.startswith("vlm-"):
                method = "vlm"

            content_list, _ = self._read_output_files(
                base_output_dir, name_without_suff, method=method
            )
            return content_list

        except MineruExecutionError:
            raise
        except Exception as e:
            logging.error(f"Error in parse_pdf: {str(e)}")
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
                logging.info(
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
                        logging.info(
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

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
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
            logging.error(f"Error in parse_image: {str(e)}")
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
            logging.error(f"Error in parse_office_doc: {str(e)}")
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
            logging.error(f"Error in parse_text_file: {str(e)}")
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
            logging.warning(
                f"Warning: Office document detected ({ext}). "
                f"MinerU 2.0 requires conversion to PDF first."
            )
            return self.parse_office_doc(file_path, output_dir, lang, **kwargs)
        elif ext in self.TEXT_FORMATS:
            return self.parse_text_file(file_path, output_dir, lang, **kwargs)
        else:
            # For unsupported file types, try as PDF
            logging.warning(
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
            import platform

            subprocess_kwargs = {
                "capture_output": True,
                "text": True,
                "check": True,
                "encoding": "utf-8",
                "errors": "ignore",
            }

            # Hide console window on Windows
            if platform.system() == "Windows":
                subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(["mineru", "--version"], **subprocess_kwargs)
            logging.debug(f"MinerU version: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logging.debug(
                "MinerU 2.0 is not properly installed. "
                "Please install it using: pip install -U 'mineru[core]'"
            )
            return False


class DoclingParser(Parser):
    """
    Docling document parsing utility class.

    Specialized in parsing Office documents and HTML files, converting the content
    into structured data and generating markdown and JSON output.
    """

    # Define Docling-specific formats
    HTML_FORMATS = {".html", ".htm", ".xhtml"}

    def __init__(self) -> None:
        """Initialize DoclingParser"""
        super().__init__()

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

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
            else:
                base_output_dir = pdf_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            # Run docling command
            self._run_docling_command(
                input_path=pdf_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
            )

            # Read the generated output files
            content_list, _ = self._read_output_files(
                base_output_dir, name_without_suff
            )
            return content_list

        except Exception as e:
            logging.error(f"Error in parse_pdf: {str(e)}")
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
            file_path: Path to the file to be parsed
            method: Parsing method
            output_dir: Output directory path
            lang: Document language for optimization
            **kwargs: Additional parameters for docling command

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

    def _run_docling_command(
        self,
        input_path: Union[str, Path],
        output_dir: Union[str, Path],
        file_stem: str,
        **kwargs,
    ) -> None:
        """
        Run docling command line tool

        Args:
            input_path: Path to input file or directory
            output_dir: Output directory path
            file_stem: File stem for creating subdirectory
            **kwargs: Additional parameters for docling command
        """
        # Create subdirectory structure similar to MinerU
        file_output_dir = Path(output_dir) / file_stem / "docling"
        file_output_dir.mkdir(parents=True, exist_ok=True)

        cmd_json = [
            "docling",
            "--output",
            str(file_output_dir),
            "--to",
            "json",
            str(input_path),
        ]
        cmd_md = [
            "docling",
            "--output",
            str(file_output_dir),
            "--to",
            "md",
            str(input_path),
        ]

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

            result_json = subprocess.run(cmd_json, **docling_subprocess_kwargs)
            result_md = subprocess.run(cmd_md, **docling_subprocess_kwargs)
            logging.info("Docling command executed successfully")
            if result_json.stdout:
                logging.debug(f"JSON cmd output: {result_json.stdout}")
            if result_md.stdout:
                logging.debug(f"Markdown cmd output: {result_md.stdout}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running docling command: {e}")
            if e.stderr:
                logging.error(f"Error details: {e.stderr}")
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "docling command not found. Please ensure Docling is properly installed."
            )

    def _read_output_files(
        self,
        output_dir: Path,
        file_stem: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Read the output files generated by docling and convert to MinerU format

        Args:
            output_dir: Output directory
            file_stem: File name without extension

        Returns:
            Tuple containing (content list JSON, Markdown text)
        """
        # Use subdirectory structure similar to MinerU
        file_subdir = output_dir / file_stem / "docling"
        md_file = file_subdir / f"{file_stem}.md"
        json_file = file_subdir / f"{file_stem}.json"

        # Read markdown content
        md_content = ""
        if md_file.exists():
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception as e:
                logging.warning(f"Could not read markdown file {md_file}: {e}")

        # Read JSON content and convert format
        content_list = []
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    docling_content = json.load(f)
                    # Convert docling format to minerU format
                    content_list = self.read_from_block_recursive(
                        docling_content["body"],
                        "body",
                        file_subdir,
                        0,
                        "0",
                        docling_content,
                    )
            except Exception as e:
                logging.warning(f"Could not read or convert JSON file {json_file}: {e}")
        return content_list, md_content

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
                member_type = member_tag.split("/")[1]
                member_num = member_tag.split("/")[2]
                member_block = docling_content[member_type][int(member_num)]
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
                base64_str = base64_uri.split(",")[1]
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
                logging.warning(f"Failed to process image {num}: {e}")
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
                logging.warning(f"Failed to process table {num}: {e}")
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

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
            else:
                base_output_dir = doc_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            # Run docling command
            self._run_docling_command(
                input_path=doc_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
            )

            # Read the generated output files
            content_list, _ = self._read_output_files(
                base_output_dir, name_without_suff
            )
            return content_list

        except Exception as e:
            logging.error(f"Error in parse_office_doc: {str(e)}")
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

            # Prepare output directory
            if output_dir:
                base_output_dir = Path(output_dir)
            else:
                base_output_dir = html_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            # Run docling command
            self._run_docling_command(
                input_path=html_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
            )

            # Read the generated output files
            content_list, _ = self._read_output_files(
                base_output_dir, name_without_suff
            )
            return content_list

        except Exception as e:
            logging.error(f"Error in parse_html: {str(e)}")
            raise

    def check_installation(self) -> bool:
        """
        Check if Docling is properly installed

        Returns:
            bool: True if installation is valid, False otherwise
        """
        try:
            # Prepare subprocess parameters to hide console window on Windows
            import platform

            subprocess_kwargs = {
                "capture_output": True,
                "text": True,
                "check": True,
                "encoding": "utf-8",
                "errors": "ignore",
            }

            # Hide console window on Windows
            if platform.system() == "Windows":
                subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(["docling", "--version"], **subprocess_kwargs)
            logging.debug(f"Docling version: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logging.debug(
                "Docling is not properly installed. "
                "Please ensure it is installed correctly."
            )
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
        return self._result_to_content_list(result, base_output_dir)

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
        description="Parse documents using MinerU 2.0 or Docling"
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
            "vlm-transformers",
            "vlm-sglang-engine",
            "vlm-sglang-client",
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
        choices=["mineru", "docling", "kreuzberg", "marker"],
        default="mineru",
        help="Parser selection",
    )
    parser.add_argument(
        "--vlm_url",
        help="When the backend is `vlm-sglang-client`, you need to specify the server_url, for example:`http://127.0.0.1:30000`",
    )

    args = parser.parse_args()

    # Check installation if requested
    if args.check:
        if args.parser == "docling":
            doc_parser = DoclingParser()
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
