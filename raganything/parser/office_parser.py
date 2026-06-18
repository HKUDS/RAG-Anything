import json
import logging
import os
import re
import time
import base64
import hashlib
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union


from .base import Parser
import logging
import os
import json
import base64
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional



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

            # Parse via the Docling Python API and convert directly from the
            # in-memory dict, bypassing the JSON disk round-trip.
            doc_dict = self._run_docling_python(
                input_path=pdf_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
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

        # The legacy CLI path accepted an `env` mapping. Validate it for type
        # compatibility but otherwise drop it: the Python API does not need
        # subprocess environment overrides.
        custom_env = kwargs.pop("env", None)
        if custom_env is not None:
            if not isinstance(custom_env, dict):
                raise TypeError(
                    f"env must be a dictionary, got {type(custom_env).__name__}"
                )
            for k, v in custom_env.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise TypeError("env keys and values must be strings")
            self.logger.debug(
                "DoclingParser: 'env' kwarg accepted for backward compatibility "
                "but ignored by the Python API path."
            )

        try:
            converter = self._get_converter(**kwargs)
        except ImportError as e:
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

            # .doc (old binary format) not supported by Docling natively,
            # use LibreOffice to convert to PDF first
            if doc_path.suffix.lower() == ".doc":
                self.logger.info("Legacy .doc format detected, converting via LibreOffice")
                pdf_path = self.convert_office_to_pdf(doc_path, output_dir)
                return self.parse_pdf(
                    pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
                )

            name_without_suff = doc_path.stem

            # Prepare output directory — use unique subdirectory to prevent
            # same-name file collisions when output_dir is shared (#51)
            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, doc_path)
            else:
                base_output_dir = doc_path.parent / "docling_output"

            base_output_dir.mkdir(parents=True, exist_ok=True)

            doc_dict = self._run_docling_python(
                input_path=doc_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
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

            doc_dict = self._run_docling_python(
                input_path=html_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
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

