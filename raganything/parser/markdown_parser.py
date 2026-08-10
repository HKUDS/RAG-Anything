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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union


from .base import Parser
import logging
import os
import json
import base64
import re
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional



class MarkerParser(Parser):
    """Marker document parsing utility class.

    Uses the marker-pdf Python API (``PdfConverter`` + Surya vision models) to
    convert PDF, Office, Image, HTML, and EPUB documents into structured
    content blocks.

    The converter and vision model dict are built lazily on first use and
    cached so subsequent parses reuse already-loaded models.

    .. note::

        The ``marker-pdf`` package is an **optional** dependency. Install with::

            pip install marker-pdf

        For non-PDF format support (DOCX/PPTX/XLSX/HTML/EPUB)::

            pip install marker-pdf[full]

    Supported formats:
        - **PDF** (primary, via Surya layout/OCR models)
        - **Images** (.png, .jpg, .jpeg, .gif, .bmp, .tiff, .webp)
        - **Office** (.docx, .pptx, .xlsx via marker-pdf[full])
        - **HTML** (.html, .htm via marker-pdf[full])
        - **EPUB** (.epub via marker-pdf[full])

    Legacy binary ``.doc`` files fall back to LibreOffice conversion since
    marker-pdf does not natively support the binary OLE format.

    Concurrency:
        The internal model dict and converter cache are guarded by a lock so
        a single ``MarkerParser`` instance can be safely shared across threads.
    """

    EPUB_FORMATS = {".epub"}
    HTML_FORMATS = {".html", ".htm", ".xhtml"}

    def __init__(self) -> None:
        """Initialize MarkerParser.

        The Surya vision model dict is loaded lazily (on first parse call)
        rather than eagerly at construction time, so that ``get_parser("marker")``
        or ``auto_parser()`` returning ``"marker"`` does not immediately download
        multi-GB model weights.
        """
        super().__init__()
        self._model_dict: Any = None
        self._converter_cache: Dict[Tuple, Any] = {}
        self._converter_cache_lock = threading.Lock()

    @staticmethod
    def _remote_service_url() -> str:
        """Return the configured isolated Marker worker endpoint, if any."""
        return os.environ.get("MARKER_SERVICE_URL", "").rstrip("/")

    def _parse_via_service(
        self,
        input_path: Union[str, Path],
        output_dir: Optional[str],
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Call the Marker worker using paths from the shared Docker volumes."""
        source = Path(input_path)
        if not source.is_file():
            raise FileNotFoundError(f"File does not exist: {source}")
        # The Marker worker receives uploads as read-only volumes.  A caller
        # without an explicit output directory must therefore use the shared
        # output volume instead of writing beside the source file.
        configured_output_dir = output_dir or os.environ.get(
            "MARKER_SHARED_OUTPUT_DIR", "/app/output"
        )
        base_output_dir = self._unique_output_dir(configured_output_dir, source)
        base_output_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "input_path": str(source.resolve()),
                "output_dir": str(base_output_dir.resolve()),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._remote_service_url()}/v1/parse",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = float(os.environ.get("MARKER_SERVICE_TIMEOUT_SECONDS", "1800"))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"Marker worker rejected the parse request: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Marker worker is unavailable") from exc
        if not isinstance(body, dict) or not isinstance(body.get("content_list"), list):
            raise RuntimeError("Marker worker returned an invalid parse result")
        return body["content_list"]

    def _service_is_healthy(self) -> bool:
        service_url = self._remote_service_url()
        if not service_url:
            return False
        request = urllib.request.Request(f"{service_url}/healthz", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("status") == "ok")
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
            return False

    # ------------------------------------------------------------------
    # Installation guard
    # ------------------------------------------------------------------

    @staticmethod
    def _require_marker() -> tuple:
        """Import marker-pdf or raise helpful ImportError.

        Returns:
            Tuple of ``(PdfConverter, create_model_dict)``.

        Raises:
            ImportError: If marker-pdf is not installed, with a message that
                tells the user which pip command to run.
        """
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
        except ImportError as exc:
            raise ImportError(
                "Marker parser requires the optional `marker-pdf` package. "
                "Install with: pip install marker-pdf\n"
                "For non-PDF format support: pip install marker-pdf[full]"
            ) from exc
        return PdfConverter, create_model_dict

    # ------------------------------------------------------------------
    # Converter cache (lazy model loading)
    # ------------------------------------------------------------------

    def _get_converter(self, **kwargs) -> Any:
        """Lazily build and cache a ``PdfConverter`` with Surya vision models.

        Returns a configured ``PdfConverter`` instance that outputs JSON block
        tree.  Caches one converter per distinct configuration key so models
        are loaded only once per process.

        Recognized kwargs:
            output_format: ``"json"`` (default), ``"markdown"``, ``"html"``,
                           or ``"chunks"``.
            use_llm: Enable LLM hybrid mode for enhanced accuracy
                     (default: False).
            force_ocr: Force OCR on all pages (default: False).
            page_range: e.g. ``"0,5-10"``.
        """
        PdfConverter, create_model_dict = self._require_marker()

        output_format = kwargs.get("output_format", "json")
        use_llm = bool(kwargs.get("use_llm", False))
        force_ocr = bool(kwargs.get("force_ocr", False))
        page_range = kwargs.get("page_range")

        cache_key = (output_format, use_llm, force_ocr, page_range)

        # Fast path: check cache without lock
        cached = self._converter_cache.get(cache_key)
        if cached is not None:
            return cached

        # Slow path: serialize model loading
        with self._converter_cache_lock:
            cached = self._converter_cache.get(cache_key)
            if cached is not None:
                return cached

            if self._model_dict is None:
                self.logger.info("Loading Marker Surya vision models (first use)...")
                self._model_dict = create_model_dict()

            config_dict = {
                "output_format": output_format,
                "use_llm": use_llm,
                "force_ocr": force_ocr,
            }
            if page_range is not None:
                config_dict["page_range"] = page_range

            converter = PdfConverter(
                artifact_dict=self._model_dict,
                config=config_dict,
            )
            self._converter_cache[cache_key] = converter
            self.logger.info("Marker PdfConverter created and cached.")
            return converter

    # ------------------------------------------------------------------
    # Core conversion
    # ------------------------------------------------------------------

    def _run_marker_python(
        self,
        input_path: Union[str, Path],
        output_dir: Union[str, Path],
        file_stem: str,
        **kwargs,
    ) -> Any:
        """Parse *input_path* through Marker's ``PdfConverter`` and return
        the rendered document object.

        Markdown and (best-effort) JSON artifacts are persisted to
        ``<output_dir>/<file_stem>/marker/`` for backward compatibility with
        the output-layout convention used by ``DoclingParser``.
        """
        file_output_dir = Path(output_dir) / file_stem / "marker"
        file_output_dir.mkdir(parents=True, exist_ok=True)

        try:
            converter = self._get_converter(**kwargs)
        except ImportError as e:
            raise RuntimeError(
                "Marker Python API is not available. "
                "Install with: pip install marker-pdf"
            ) from e

        try:
            rendered = converter(str(input_path))
        except Exception as e:
            self.logger.error(
                "Error running Marker PdfConverter on %s: %s",
                Path(input_path).name,
                e,
            )
            raise

        # Persist Markdown artifact
        if hasattr(rendered, "markdown"):
            md_path = file_output_dir / f"{file_stem}.md"
            try:
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(rendered.markdown)
            except Exception as e:
                self.logger.warning(
                    "Could not write Marker Markdown to %s: %s", md_path, e
                )

        # Persist block-tree JSON (best-effort, for debugging)
        try:
            if hasattr(rendered, "children"):
                import json as _json

                serializable = [
                    {"block_type": getattr(c, "block_type", "unknown"),
                     "id": getattr(c, "id", "")}
                    for c in rendered.children
                ]
                json_path = file_output_dir / f"{file_stem}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    _json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(
                "Could not write Marker JSON to %s/%s.json: %s",
                file_output_dir,
                file_stem,
                e,
            )

        self.logger.info(
            "Marker PdfConverter parse completed for %s", Path(input_path).name
        )
        return rendered

    # ------------------------------------------------------------------
    # Block-tree → content_list conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _html_to_text(html_str: str) -> str:
        """Extract plain text from an HTML string.

        Uses BeautifulSoup when available; falls back to a simple regex
        tag-stripper otherwise.
        """
        if not html_str:
            return ""
        try:
            from bs4 import BeautifulSoup

            return BeautifulSoup(html_str, "html.parser").get_text(" ", strip=True)
        except ImportError:
            import re

            text = re.sub(r"<[^>]+>", " ", html_str)
            return " ".join(text.split())

    def _handle_marker_image(
        self,
        block: dict,
        block_id: str,
        output_dir: Path,
        page_idx: int,
    ) -> Dict[str, Any]:
        """Decode base64 image from *block* and persist to *output_dir*/images/."""
        images = block.get("images") or {}
        base64_str = images.get(block_id, "")
        caption_html = block.get("html", "")

        image_dir = output_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)

        # Generate a safe filename from block_id
        safe_id = block_id.lstrip("/").replace("/", "_").replace("\\", "_")
        if not safe_id:
            import uuid

            safe_id = uuid.uuid4().hex[:8]
        image_path = image_dir / f"{safe_id}.png"

        if base64_str:
            try:
                with open(image_path, "wb") as f:
                    f.write(base64.b64decode(base64_str))
                return {
                    "type": "image",
                    "img_path": str(image_path.resolve()),
                    "image_caption": self._html_to_text(caption_html),
                    "image_footnote": "",
                    "page_idx": page_idx,
                }
            except Exception as e:
                self.logger.warning(
                    "Failed to decode/extract Marker image %s: %s", block_id, e
                )

        # Fallback: represent as text placeholder
        return {
            "type": "text",
            "text": f"[Image: {self._html_to_text(caption_html)}]",
            "page_idx": page_idx,
        }

    def _handle_marker_table(
        self,
        block: dict,
        page_idx: int,
    ) -> Dict[str, Any]:
        """Parse HTML table from Marker output into ``table_body`` list-of-rows."""
        html_str = block.get("html", "")
        table_body = []

        if html_str:
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html_str, "html.parser")
                table = soup.find("table")
                if table:
                    for tr in table.find_all("tr"):
                        row = []
                        for cell in tr.find_all(["td", "th"]):
                            row.append(cell.get_text(" ", strip=True))
                        if row:
                            table_body.append(row)
            except Exception as e:
                self.logger.warning(
                    "Failed to parse Marker table HTML: %s", e
                )

        return {
            "type": "table",
            "img_path": "",
            "table_caption": "",
            "table_footnote": "",
            "table_body": table_body,
            "page_idx": page_idx,
        }

    def _convert_block_to_content(
        self,
        block,
        page_idx: int,
        output_dir: Path,
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert a Marker block-tree node into one or more content_list dicts.

        Marker's block tree is traversed recursively.  Container blocks
        (``FigureGroup``, ``TableGroup``, ``Page``, etc.) are recursed into;
        leaf blocks (``Text``, ``Table``, ``Figure``, ``Equation``, ``Code``,
        ``Form``) produce the standard RAGAnything content-list entries.

        Args:
            block: A block object from Marker's rendered output (Pydantic
                   model or plain dict depending on marker-pdf version).
            page_idx: 0-based page index.
            output_dir: Directory for saving extracted images.

        Returns:
            List of content dict(s), or ``None`` for no-op containers.
        """
        # Normalize block to plain dict
        if hasattr(block, "dict"):
            b = block.dict()
        elif isinstance(block, dict):
            b = block
        else:
            # Minimal duck-typing fallback for unknown object shapes
            b = {
                "block_type": getattr(block, "block_type", "Text"),
                "html": getattr(block, "html", ""),
                "images": getattr(block, "images", {}),
                "children": getattr(block, "children", None),
                "id": getattr(block, "id", ""),
            }

        block_type = b.get("block_type", "")

        # --- Container blocks: recurse into children ---
        if block_type in (
            "FigureGroup",
            "TableGroup",
            "ListGroup",
            "PictureGroup",
            "Page",
            "Document",
        ):
            results = []
            children = b.get("children") or []
            for child in children:
                child_result = self._convert_block_to_content(
                    child, page_idx, output_dir
                )
                if child_result:
                    results.extend(child_result)
            return results if results else None

        # --- Image blocks ---
        if block_type in ("Figure", "Picture"):
            return [
                self._handle_marker_image(
                    b, b.get("id", ""), output_dir, page_idx
                )
            ]

        # --- Table block ---
        if block_type == "Table":
            return [self._handle_marker_table(b, page_idx)]

        # --- Equation blocks ---
        if block_type == "Equation":
            text = self._html_to_text(b.get("html", ""))
            return [
                {
                    "type": "equation",
                    "img_path": "",
                    "text": text,
                    "text_format": "latex",
                    "page_idx": page_idx,
                }
            ]

        if block_type == "TextInlineMath":
            text = self._html_to_text(b.get("html", ""))
            return [
                {
                    "type": "equation",
                    "img_path": "",
                    "text": text,
                    "text_format": "latex_inline",
                    "page_idx": page_idx,
                }
            ]

        # --- Code block ---
        if block_type == "Code":
            text = self._html_to_text(b.get("html", ""))
            return [{"type": "code", "text": text, "page_idx": page_idx}]

        # --- Form block ---
        if block_type == "Form":
            text = self._html_to_text(b.get("html", ""))
            return [{"type": "text", "text": text, "page_idx": page_idx}]

        # --- Remaining text-like types ---
        # Text, SectionHeader, Caption, Footnote, PageHeader, PageFooter,
        # ListItem, Line, Span, Handwriting, TableOfContents
        text = self._html_to_text(b.get("html", ""))
        if text.strip():
            return [{"type": "text", "text": text, "page_idx": page_idx}]
        return None

    # ------------------------------------------------------------------
    # Public parse methods
    # ------------------------------------------------------------------

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Parse PDF using Marker's Surya-based pipeline.

        Args:
            pdf_path: Path to the PDF file.
            output_dir: Base output directory for artifacts.
                        Defaults to ``<pdf_dir>/marker_output``.
            method: Ignored (kept for interface compatibility).
            lang: Ignored (kept for interface compatibility).
            **kwargs: Passed through to ``_get_converter`` (e.g. ``use_llm``,
                      ``force_ocr``, ``page_range``, ``output_format``).

        Returns:
            List of content dicts in RAGAnything standard format.
        """
        if self._remote_service_url():
            return self._parse_via_service(pdf_path, output_dir, **kwargs)
        try:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                raise FileNotFoundError(
                    f"PDF file does not exist: {pdf_path}"
                )

            name_without_suff = pdf_path.stem

            if output_dir:
                base_output_dir = self._unique_output_dir(output_dir, pdf_path)
            else:
                base_output_dir = pdf_path.parent / "marker_output"
            base_output_dir.mkdir(parents=True, exist_ok=True)

            rendered = self._run_marker_python(
                input_path=pdf_path,
                output_dir=base_output_dir,
                file_stem=name_without_suff,
                **kwargs,
            )

            file_subdir = base_output_dir / name_without_suff / "marker"
            content_list = []
            children = getattr(rendered, "children", None) or []
            for page_idx, page_block in enumerate(children):
                page_items = self._convert_block_to_content(
                    page_block, page_idx, file_subdir
                )
                if page_items:
                    content_list.extend(page_items)

            self.logger.info(
                "Marker parsed %s → %d content blocks",
                pdf_path.name,
                len(content_list),
            )
            return content_list
        except Exception as e:
            self.logger.error(
                "Error in MarkerParser.parse_pdf for %s: %s", pdf_path, e
            )
            raise

    def parse_image(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Parse image using Marker's Surya OCR models.

        Marker's ``PdfConverter`` can accept image files directly and will
        apply the Surya OCR pipeline.
        """
        if self._remote_service_url():
            return self._parse_via_service(image_path, output_dir, **kwargs)
        try:
            image_path = Path(image_path)
            if not image_path.exists():
                raise FileNotFoundError(
                    f"Image file does not exist: {image_path}"
                )

            return self.parse_pdf(
                pdf_path=image_path,
                output_dir=output_dir,
                lang=lang,
                **kwargs,
            )
        except Exception as e:
            self.logger.error(
                "Error in MarkerParser.parse_image for %s: %s", image_path, e
            )
            raise

    def parse_office_doc(
        self,
        doc_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Parse Office or HTML document using Marker.

        Natively supported: ``.docx``, ``.pptx``, ``.xlsx``, ``.html``,
        ``.htm``, ``.xhtml`` (requires ``marker-pdf[full]``).

        Legacy ``.doc`` (binary OLE) falls back to LibreOffice → PDF
        conversion since marker-pdf cannot handle the binary format.
        """
        if self._remote_service_url():
            return self._parse_via_service(doc_path, output_dir, **kwargs)
        try:
            doc_path = Path(doc_path)
            if not doc_path.exists():
                raise FileNotFoundError(
                    f"Document does not exist: {doc_path}"
                )

            ext = doc_path.suffix.lower()

            # Legacy binary .doc — fall back to LibreOffice
            if ext == ".doc":
                self.logger.info(
                    "Legacy .doc detected, converting via LibreOffice for Marker"
                )
                pdf_path = self.convert_office_to_pdf(doc_path, output_dir)
                return self.parse_pdf(
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    lang=lang,
                    **kwargs,
                )

            # Native formats — PdfConverter handles them directly
            return self.parse_pdf(
                pdf_path=doc_path,
                output_dir=output_dir,
                lang=lang,
                **kwargs,
            )
        except Exception as e:
            self.logger.error(
                "Error in MarkerParser.parse_office_doc for %s: %s", doc_path, e
            )
            raise

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Parse any supported document using Marker based on file extension.

        Dispatches to the appropriate method by extension.  EPUB files are
        handled natively when ``marker-pdf[full]`` is installed.
        """
        if self._remote_service_url():
            return self._parse_via_service(file_path, output_dir, **kwargs)
        downloaded_temp_file = None
        try:
            if self._is_url(file_path):
                file_path = self._download_file(file_path)
                downloaded_temp_file = file_path

            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(
                    f"File does not exist: {file_path}"
                )

            ext = file_path.suffix.lower()

            if ext == ".pdf":
                return self.parse_pdf(
                    file_path, output_dir, method, lang, **kwargs
                )
            elif ext in self.IMAGE_FORMATS:
                return self.parse_image(
                    file_path, output_dir, lang, **kwargs
                )
            elif ext in self.OFFICE_FORMATS:
                return self.parse_office_doc(
                    file_path, output_dir, lang, **kwargs
                )
            elif ext in self.HTML_FORMATS:
                return self.parse_office_doc(
                    file_path, output_dir, lang, **kwargs
                )
            elif ext in self.EPUB_FORMATS:
                return self.parse_pdf(
                    file_path, output_dir, lang, **kwargs
                )
            else:
                raise ValueError(
                    f"Unsupported file format: {ext}. "
                    f"Marker supports PDF, images, Office formats, "
                    f"HTML, and EPUB files."
                )
        finally:
            if downloaded_temp_file and downloaded_temp_file.exists():
                try:
                    downloaded_temp_file.unlink()
                except Exception as e:
                    self.logger.warning(
                        "Failed to remove temp file %s: %s",
                        downloaded_temp_file,
                        e,
                    )

    def check_installation(self) -> bool:
        """Check whether the marker-pdf Python package is importable.

        Returns ``True`` if ``marker.converters.pdf.PdfConverter`` can be
        imported, ``False`` otherwise.  Does **not** trigger Surya model
        download.
        """
        if self._remote_service_url():
            return self._service_is_healthy()
        try:
            from marker.converters.pdf import PdfConverter  # noqa: F401
            return True
        except ImportError:
            self.logger.debug(
                "Marker Python package is not installed. "
                "Install with: pip install marker-pdf"
            )
            return False

