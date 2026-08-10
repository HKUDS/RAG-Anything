from .base import Parser, _IS_WINDOWS, MineruExecutionError

import logging
import os
import subprocess
import threading
import time
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union

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
        # Look for the generated files
        md_file = output_dir / f"{file_stem}.md"
        json_file = output_dir / f"{file_stem}_content_list.json"
        images_base_dir = output_dir  # Base directory for images

        file_stem_subdir = output_dir / file_stem
        if file_stem_subdir.is_dir():
            # Scan for actual output subdirectory instead of assuming method name
            found = False
            for subdir in file_stem_subdir.iterdir():
                if not subdir.is_dir():
                    continue
                # Check if this subdirectory contains the expected JSON output file
                candidate_json = subdir / f"{file_stem}_content_list.json"
                if candidate_json.exists():
                    # Found the actual output directory
                    md_file = subdir / f"{file_stem}.md"
                    json_file = candidate_json
                    images_base_dir = subdir
                    found = True
                    cls.logger.info(
                        f"Found MinerU output in subdirectory: {subdir.name}"
                    )
                    break

            # Fallback to method-based path if scanning didn't find output
            if not found:
                cls.logger.debug(
                    f"No output found by scanning, falling back to method-based path: {method}"
                )
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
                "timeout": 10,
            }

            # Hide console window on Windows
            if _IS_WINDOWS:
                subprocess_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(["mineru", "--version"], **subprocess_kwargs)
            self.logger.debug(f"MinerU version: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            self.logger.debug(
                "MinerU 2.0 is not properly installed. "
                "Please install it using: pip install -U 'mineru[core]'"
            )
            return False

