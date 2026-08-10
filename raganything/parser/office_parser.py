import json
import importlib.util
import importlib.metadata
import contextlib
import ctypes
import gc
import logging
import math
import os
import re
import shutil
import sys
import time
import base64
import hashlib
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union


from .base import Parser
from ..utils.process_lock import FileLock


_DOCLING_ASCII_RUNTIME_LOCK = threading.Lock()
_DOCLING_ASCII_RUNTIME_READY = False
_RAPIDOCR_RUNTIME_LOCK = threading.RLock()


class PageTrackedContent(list):
    """A content list that carries the immutable source-page manifest."""

    def __init__(
        self,
        values: List[Dict[str, Any]],
        page_coverage: Dict[str, Any],
        provenance_ref: Dict[str, Any] | None = None,
    ):
        super().__init__(values)
        self.page_coverage = page_coverage
        self.provenance_ref = provenance_ref


class PdfPageCoverageError(RuntimeError):
    """Raised before durable writes when a PDF conversion is incomplete."""

    failure_stage = "parsing"
    failure_code = "pdf_page_coverage_incomplete"

    def __init__(self, page_coverage: Dict[str, Any], cause: BaseException | None = None):
        self.page_coverage = page_coverage
        self.cause = cause
        failed_pages = page_coverage.get("failed_pages") or []
        super().__init__(
            "PDF page coverage is incomplete; failed pages: "
            + ", ".join(str(page) for page in failed_pages)
        )


class OcrOutOfMemoryError(PdfPageCoverageError):
    """A terminal OCR failure after the one permitted per-page downgrade."""

    failure_stage = "ocr"
    failure_code = "ocr_oom"


def _safe_positive_int(value: str | None, default: int, *, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        return max(minimum, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _safe_positive_float(
    value: str | None, default: float, *, minimum: float = 0.25, maximum: float = 8.0,
) -> float:
    try:
        return max(minimum, min(float(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _exception_text(error: BaseException) -> str:
    """Flatten exception chaining without retaining traceback objects."""
    fragments: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        fragments.extend((type(current).__name__, str(current)))
        current = current.__cause__ or current.__context__
    return " ".join(fragments).casefold()


def _is_ocr_out_of_memory(error: BaseException) -> bool:
    text = _exception_text(error)
    allocation_markers = (
        "bad allocation",
        "std::bad_alloc",
        "memoryerror",
        "out of memory",
    )
    return any(marker in text for marker in allocation_markers) and any(
        marker in text for marker in ("onnx", "rapidocr", "ocr", "bad_alloc")
    )


def _worker_memory_snapshot() -> Dict[str, int]:
    """Capture lightweight RSS/private and Windows commit telemetry when available."""
    snapshot: Dict[str, int] = {"pid": os.getpid()}
    try:
        if os.name == "nt":
            size_t = ctypes.c_size_t

            class ProcessMemoryCountersEx(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", size_t),
                    ("WorkingSetSize", size_t),
                    ("QuotaPeakPagedPoolUsage", size_t),
                    ("QuotaPagedPoolUsage", size_t),
                    ("QuotaPeakNonPagedPoolUsage", size_t),
                    ("QuotaNonPagedPoolUsage", size_t),
                    ("PagefileUsage", size_t),
                    ("PeakPagefileUsage", size_t),
                    ("PrivateUsage", size_t),
                ]

            class PerformanceInformation(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("CommitTotal", size_t),
                    ("CommitLimit", size_t),
                    ("CommitPeak", size_t),
                    ("PhysicalTotal", size_t),
                    ("PhysicalAvailable", size_t),
                    ("SystemCache", size_t),
                    ("KernelTotal", size_t),
                    ("KernelPaged", size_t),
                    ("KernelNonpaged", size_t),
                    ("PageSize", size_t),
                    ("HandleCount", ctypes.c_ulong),
                    ("ProcessCount", ctypes.c_ulong),
                    ("ThreadCount", ctypes.c_ulong),
                ]

            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            ):
                snapshot["rss_bytes"] = int(counters.WorkingSetSize)
                snapshot["private_commit_bytes"] = int(counters.PrivateUsage)

            performance = PerformanceInformation()
            performance.cb = ctypes.sizeof(performance)
            if ctypes.windll.psapi.GetPerformanceInfo(
                ctypes.byref(performance), performance.cb
            ):
                page_size = int(performance.PageSize)
                snapshot["system_commit_bytes"] = int(performance.CommitTotal) * page_size
                snapshot["system_commit_limit_bytes"] = int(performance.CommitLimit) * page_size
    except Exception:
        # Telemetry cannot make document processing fail.
        pass
    return snapshot


@contextlib.contextmanager
def _rapidocr_render_scale(scale: float):
    """Configure Docling's in-memory RapidOCR adapter without patching site-packages."""
    with _RAPIDOCR_RUNTIME_LOCK:
        from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

        original_init = RapidOcrModel.__init__

        def init_with_scale(model, *args, **kwargs):
            original_init(model, *args, **kwargs)
            model.scale = scale

        RapidOcrModel.__init__ = init_with_scale
        try:
            yield
        finally:
            RapidOcrModel.__init__ = original_init


def _mirror_docling_package(source: Path, runtime_root: Path) -> None:
    """Create one atomic mirror while coordinating across worker processes.

    A previous interrupted attempt can leave an incomplete mirror behind.
    ``os.replace`` cannot overwrite an existing non-empty directory on
    Windows (or POSIX), so remove the stale tree under the lock before the
    atomic swap; otherwise startup keeps failing on the stale sentinel.
    """
    runtime_base = runtime_root.parent
    target_sentinel = (
        runtime_root / "docling_parse" / "pdf_resources" / "glyphs" / "standard" / "additional.dat"
    )
    runtime_base.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(runtime_base / ".docling-runtime.lock"))
    deadline = time.monotonic() + 120.0
    while not lock.acquire():
        if time.monotonic() >= deadline:
            raise RuntimeError("Timed out waiting for Docling ASCII runtime lock")
        time.sleep(0.1)
    try:
        if target_sentinel.is_file():
            return
        if runtime_root.exists():
            shutil.rmtree(runtime_root, ignore_errors=True)
        staging = runtime_base / (
            f".{runtime_root.name}-{os.getpid()}-{threading.get_ident()}"
        )
        try:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            shutil.copytree(source, staging / "docling_parse")
            os.replace(staging, runtime_root)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    finally:
        lock.release()


def _contains_non_ascii(value: object) -> bool:
    try:
        str(value).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _prepare_docling_ascii_runtime() -> Optional[Path]:
    """Load docling-parse from an ASCII path on Windows.

    The native ``pdf_parsers`` extension resolves ``pdf_resources`` relative
    to its own module path.  Some Windows builds report existing glyph files as
    missing when that path contains non-ASCII characters, and have also shown
    an interpreter-shutdown access violation.  A versioned, atomic mirror in
    the user temp directory keeps the native DLL and resources on an ASCII
    path without mutating the virtual environment.
    """
    global _DOCLING_ASCII_RUNTIME_READY

    if os.name != "nt" or _DOCLING_ASCII_RUNTIME_READY:
        return None
    if "docling_parse" in sys.modules:
        loaded_path = Path(str(getattr(sys.modules["docling_parse"], "__file__", "")))
        if _contains_non_ascii(loaded_path):
            raise RuntimeError(
                "docling_parse was imported from a non-ASCII path before the "
                "Windows compatibility runtime was prepared"
            )
        _DOCLING_ASCII_RUNTIME_READY = True
        return loaded_path.parent.parent

    with _DOCLING_ASCII_RUNTIME_LOCK:
        if _DOCLING_ASCII_RUNTIME_READY:
            return None
        spec = importlib.util.find_spec("docling_parse")
        locations = list(spec.submodule_search_locations or []) if spec else []
        if not locations:
            return None
        source = Path(locations[0]).resolve()
        sentinel = source / "pdf_resources" / "glyphs" / "standard" / "additional.dat"
        if not sentinel.is_file():
            return None
        if not _contains_non_ascii(source):
            _DOCLING_ASCII_RUNTIME_READY = True
            return source.parent

        override = os.getenv("DOCLING_ASCII_RUNTIME_DIR", "").strip()
        runtime_base = Path(override) if override else Path(tempfile.gettempdir()) / "raganything-docling"
        if _contains_non_ascii(runtime_base):
            raise RuntimeError(
                "DOCLING_ASCII_RUNTIME_DIR must contain ASCII characters only"
            )
        try:
            distribution_version = importlib.metadata.version("docling-parse")
        except importlib.metadata.PackageNotFoundError:
            distribution_version = "unknown"
        manifest_parts = [f"version={distribution_version}", f"source={source}"]
        native_files = list(source.glob("*.pyd")) + list(source.glob("*.dll"))
        resource_files = [
            item for item in (source / "pdf_resources").rglob("*") if item.is_file()
        ]
        for candidate in sorted(native_files + resource_files):
            stat = candidate.stat()
            manifest_parts.append(
                f"{candidate.relative_to(source).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}"
            )
        fingerprint = hashlib.sha256(
            "|".join(manifest_parts).encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        runtime_root = runtime_base / fingerprint
        target_package = runtime_root / "docling_parse"
        target_sentinel = (
            target_package / "pdf_resources" / "glyphs" / "standard" / "additional.dat"
        )
        if not target_sentinel.is_file():
            _mirror_docling_package(source, runtime_root)
        if not target_sentinel.is_file():
            raise RuntimeError(
                f"Docling ASCII runtime is incomplete: {target_sentinel}"
            )
        runtime_path = str(runtime_root)
        if runtime_path not in sys.path:
            sys.path.insert(0, runtime_path)
        importlib.invalidate_caches()
        module = __import__("docling_parse")
        loaded_file = Path(str(getattr(module, "__file__", ""))).resolve()
        if _contains_non_ascii(loaded_file) or runtime_root not in loaded_file.parents:
            raise RuntimeError(
                f"docling_parse loaded outside ASCII runtime: {loaded_file}"
            )
        loaded_sentinel = (
            loaded_file.parent / "pdf_resources" / "glyphs" / "standard" / "additional.dat"
        )
        if not loaded_sentinel.is_file():
            raise RuntimeError(f"Docling resource validation failed: {loaded_sentinel}")
        _DOCLING_ASCII_RUNTIME_READY = True
        return runtime_root



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
        self._last_page_coverage: Dict[str, Any] | None = None

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

            file_subdir = base_output_dir / name_without_suff / "docling"
            file_subdir.mkdir(parents=True, exist_ok=True)
            page_specs = self._read_pdf_page_specs(pdf_path)
            coverage: Dict[str, Any] = {
                "version": 1,
                "source_total_pages": len(page_specs),
                "successful_pages": [],
                "failed_pages": [],
                "skipped_pages": [],
                "retried_pages": [],
                "pages": [],
            }
            content_list: List[Dict[str, Any]] = []
            failures: list[BaseException] = []

            try:
                for page_spec in page_specs:
                    page_content, page_record, error = self._parse_pdf_page_bounded(
                        pdf_path,
                        file_subdir,
                        page_spec,
                        lang=lang,
                        **kwargs,
                    )
                    coverage["pages"].append(page_record)
                    page_no = page_spec["page_number"]
                    if error is None:
                        coverage["successful_pages"].append(page_no)
                        if len(page_record["attempts"]) > 1:
                            coverage["retried_pages"].append(page_no)
                        content_list.extend(page_content or [])
                    else:
                        coverage["failed_pages"].append(page_no)
                        failures.append(error)

                self._last_page_coverage = coverage
                self._write_page_coverage(file_subdir, coverage)
                if coverage["failed_pages"]:
                    oom_error = next(
                        (error for error in failures if _is_ocr_out_of_memory(error)),
                        None,
                    )
                    if oom_error is not None:
                        raise OcrOutOfMemoryError(coverage, oom_error) from oom_error
                    raise PdfPageCoverageError(coverage, failures[0]) from failures[0]

                return PageTrackedContent(content_list, coverage)
            finally:
                # A Worker handles one document and exits. Dropping these references
                # after each PDF prevents converter/image caches from becoming a
                # hidden cross-document memory reservoir in direct API use as well.
                self._release_docling_converters()

        except Exception as e:
            self.logger.error(f"Error in parse_pdf: {str(e)}")
            raise

    @staticmethod
    def _read_pdf_page_specs(pdf_path: Path) -> List[Dict[str, Any]]:
        """Read source page geometry without rendering or OCR."""
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - project dependency
            raise RuntimeError("pypdf is required for PDF page coverage checks") from exc

        reader = PdfReader(str(pdf_path))
        page_specs: List[Dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            box = page.mediabox
            width = abs(float(box.width))
            height = abs(float(box.height))
            if width <= 0 or height <= 0:
                raise RuntimeError(f"PDF page {page_number} has an invalid MediaBox")
            page_specs.append({
                "page_number": page_number,
                "width_points": width,
                "height_points": height,
            })
        if not page_specs:
            raise RuntimeError("PDF contains no pages")
        return page_specs

    @staticmethod
    def _bounded_ocr_profile(page_spec: Dict[str, Any], *, degraded: bool) -> Dict[str, Any]:
        """Keep one page's rendered OCR input and ONNX work buffers bounded."""
        width = float(page_spec["width_points"])
        height = float(page_spec["height_points"])
        if degraded:
            max_scale = _safe_positive_float(
                os.getenv("DOCLING_OCR_RETRY_RENDER_SCALE"), 1.5, maximum=3.0,
            )
            pixel_budget = _safe_positive_int(
                os.getenv("DOCLING_OCR_RETRY_MAX_PIXELS"), 2_000_000,
                minimum=250_000,
                maximum=16_000_000,
            )
            max_side = _safe_positive_int(
                os.getenv("DOCLING_OCR_RETRY_MAX_SIDE_LEN"), 1200,
                minimum=320,
                maximum=2000,
            )
            picture_scale = 0.75
        else:
            max_scale = _safe_positive_float(
                os.getenv("DOCLING_OCR_MAX_RENDER_SCALE"), 3.0, maximum=3.0,
            )
            pixel_budget = _safe_positive_int(
                os.getenv("DOCLING_OCR_MAX_PIXELS"), 8_000_000,
                minimum=500_000,
                maximum=32_000_000,
            )
            max_side = _safe_positive_int(
                os.getenv("DOCLING_OCR_MAX_SIDE_LEN"), 1600,
                minimum=320,
                maximum=2000,
            )
            picture_scale = 1.0

        render_scale = min(max_scale, math.sqrt(pixel_budget / (width * height)))
        render_scale = max(0.25, round(render_scale, 3))
        return {
            "ocr_render_scale": render_scale,
            "estimated_raster_width": max(1, round(width * render_scale)),
            "estimated_raster_height": max(1, round(height * render_scale)),
            "images_scale": min(picture_scale, render_scale),
            "rapidocr_max_side_len": max_side,
            "rapidocr_rec_batch_num": 1,
            "onnx_threads": 1,
            "docling_batch_size": 1,
            "queue_max_size": 2,
            "degraded": degraded,
        }

    def _parse_pdf_page_bounded(
        self,
        pdf_path: Path,
        file_subdir: Path,
        page_spec: Dict[str, Any],
        *,
        lang: Optional[str],
        **kwargs,
    ) -> tuple[List[Dict[str, Any]] | None, Dict[str, Any], BaseException | None]:
        """Convert one source page, retrying only an OCR allocation failure once."""
        page_no = int(page_spec["page_number"])
        page_record: Dict[str, Any] = {
            **page_spec,
            "status": "failed",
            "attempts": [],
        }
        last_error: BaseException | None = None

        for attempt in (1, 2):
            profile = self._bounded_ocr_profile(page_spec, degraded=attempt == 2)
            telemetry = {
                "page_number": page_no,
                "attempt": attempt,
                "profile": profile,
                "memory_before": _worker_memory_snapshot(),
            }
            result = None
            document = None
            converter = None
            try:
                converter = self._get_converter(
                    allow_ocr=kwargs.get("allow_ocr", True),
                    tables=kwargs.get("tables", True),
                    table_mode=kwargs.get("table_mode", "fast"),
                    artifacts_path=kwargs.get("artifacts_path"),
                    lang=lang,
                    _ocr_profile=profile,
                )
                with _rapidocr_render_scale(profile["ocr_render_scale"]):
                    result = converter.convert(
                        str(pdf_path), page_range=(page_no, page_no), raises_on_error=True,
                    )
                self._require_single_page_success(result, page_no)
                document = result.document
                doc_dict = document.export_to_dict()
                page_output_dir = file_subdir / f"page-{page_no:04d}"
                page_content = self.read_from_block_recursive(
                    doc_dict["body"], "body", page_output_dir, 0, "0", doc_dict
                )
                telemetry["status"] = "success"
                telemetry["memory_after"] = _worker_memory_snapshot()
                page_record["attempts"].append(telemetry)
                page_record["status"] = "success"
                self.logger.info("OCR_PAGE_METRICS %s", json.dumps(telemetry, ensure_ascii=False))
                return page_content, page_record, None
            except Exception as exc:
                last_error = exc
                telemetry["status"] = "oom" if _is_ocr_out_of_memory(exc) else "failed"
                telemetry["error_type"] = type(exc).__name__
                telemetry["error"] = str(exc)[:1000]
                telemetry["memory_after"] = _worker_memory_snapshot()
                page_record["attempts"].append(telemetry)
                self.logger.warning("OCR_PAGE_METRICS %s", json.dumps(telemetry, ensure_ascii=False))
                self._release_docling_converters()
                if not _is_ocr_out_of_memory(exc) or attempt == 2:
                    break
            finally:
                # `ConversionResult` retains page backends and image caches. The
                # bounded unit is one page, so release them before the next page.
                del converter
                del document
                del result
                gc.collect()

        page_record["error_type"] = type(last_error).__name__ if last_error else "RuntimeError"
        page_record["error"] = str(last_error)[:1000] if last_error else "page conversion failed"
        return None, page_record, last_error or RuntimeError("page conversion failed")

    @staticmethod
    def _require_single_page_success(result: Any, page_no: int) -> None:
        status = str(getattr(result, "status", "")).casefold()
        converted_pages = {
            int(getattr(page, "page_no"))
            for page in (getattr(result, "pages", None) or [])
            if getattr(page, "page_no", None) is not None
        }
        if "partial" not in status and "failure" not in status and page_no in converted_pages:
            return
        errors = [
            str(getattr(item, "error_message", item))
            for item in (getattr(result, "errors", None) or [])
        ]
        detail = "; ".join(errors) or f"Docling conversion status={status or 'unknown'}"
        raise RuntimeError(f"Docling did not complete PDF page {page_no}: {detail}")

    @staticmethod
    def _write_page_coverage(file_subdir: Path, coverage: Dict[str, Any]) -> None:
        try:
            with open(file_subdir / "page_coverage.json", "w", encoding="utf-8") as f:
                json.dump(coverage, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.getLogger(__name__).warning("Could not write PDF page coverage: %s", exc)

    def _release_docling_converters(self) -> None:
        with self._converter_cache_lock:
            self._converter_cache.clear()
        gc.collect()

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
        _prepare_docling_ascii_runtime()
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            RapidOcrOptions,
            TableFormerMode,
        )

        table_mode = str(kwargs.get("table_mode", "fast")).lower()
        do_tables = bool(kwargs.get("tables", True))
        do_ocr = bool(kwargs.get("allow_ocr", True))
        artifacts_path = kwargs.get("artifacts_path")
        lang = kwargs.get("lang")
        ocr_profile = dict(kwargs.get("_ocr_profile") or {
            "ocr_render_scale": 3.0,
            "images_scale": 1.0,
            "rapidocr_max_side_len": _safe_positive_int(
                os.getenv("DOCLING_OCR_MAX_SIDE_LEN"), 1600, minimum=320, maximum=2000,
            ),
            "rapidocr_rec_batch_num": 1,
            "onnx_threads": 1,
            "docling_batch_size": 1,
            "queue_max_size": 2,
            "degraded": False,
        })
        profile_key = tuple(sorted((str(key), str(value)) for key, value in ocr_profile.items()))

        cache_key = (table_mode, do_tables, do_ocr, artifacts_path, lang, profile_key)
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

        # Bound all Docling scheduling queues. RapidOCR itself works page by
        # page, but the standard PDF pipeline otherwise queues four OCR/layout/
        # table pages and up to 100 pending pages before releasing image buffers.
        batch_size = _safe_positive_int(
            str(ocr_profile.get("docling_batch_size", 1)), 1, maximum=4,
        )
        if hasattr(pipeline_options, "ocr_batch_size"):
            pipeline_options.ocr_batch_size = batch_size
        if hasattr(pipeline_options, "layout_batch_size"):
            pipeline_options.layout_batch_size = batch_size
        if hasattr(pipeline_options, "table_batch_size"):
            pipeline_options.table_batch_size = batch_size
        if hasattr(pipeline_options, "queue_max_size"):
            pipeline_options.queue_max_size = _safe_positive_int(
                str(ocr_profile.get("queue_max_size", 2)), 2, maximum=8,
            )
        if hasattr(pipeline_options, "accelerator_options"):
            pipeline_options.accelerator_options = AcceleratorOptions(
                num_threads=_safe_positive_int(
                    str(ocr_profile.get("onnx_threads", 1)), 1, maximum=4,
                ),
                device=AcceleratorDevice.CPU,
            )

        if do_ocr and hasattr(pipeline_options, "ocr_options"):
            onnx_threads = _safe_positive_int(
                str(ocr_profile.get("onnx_threads", 1)), 1, maximum=4,
            )
            pipeline_options.ocr_options = RapidOcrOptions(
                lang=[str(lang)] if lang else ["chinese"],
                rapidocr_params={
                    "Global.max_side_len": _safe_positive_int(
                        str(ocr_profile.get("rapidocr_max_side_len", 1600)),
                        1600,
                        minimum=320,
                        maximum=2000,
                    ),
                    "Det.limit_side_len": _safe_positive_int(
                        str(ocr_profile.get("rapidocr_max_side_len", 1600)),
                        1600,
                        minimum=320,
                        maximum=2000,
                    ),
                    "Cls.cls_batch_num": 1,
                    "Rec.rec_batch_num": _safe_positive_int(
                        str(ocr_profile.get("rapidocr_rec_batch_num", 1)),
                        1,
                        maximum=4,
                    ),
                    "EngineConfig.onnxruntime.intra_op_num_threads": onnx_threads,
                    "EngineConfig.onnxruntime.inter_op_num_threads": onnx_threads,
                    "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
                },
            )

        # Keep picture extraction for multimodal processing, but never retain a
        # second 2x page image alongside OCR's own raster. Per-page outputs use
        # a bounded, adaptive scale from the current OCR profile.
        if hasattr(pipeline_options, "generate_picture_images"):
            pipeline_options.generate_picture_images = bool(
                kwargs.get("generate_picture_images", True)
            )
        if hasattr(pipeline_options, "images_scale"):
            pipeline_options.images_scale = _safe_positive_float(
                str(ocr_profile.get("images_scale", 1.0)), 1.0, maximum=1.0,
            )

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
        page_idx = self._page_index_from_block(block, fallback=cnt // 10)
        if type == "texts":
            if block["label"] == "formula":
                return {
                    "type": "equation",
                    "img_path": "",
                    "text": block["orig"],
                    "text_format": "unknown",
                    "page_idx": page_idx,
                }
            else:
                return {
                    "type": "text",
                    "text": block["orig"],
                    "page_idx": page_idx,
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
                    "page_idx": page_idx,
                }
            except Exception as e:
                self.logger.warning(f"Failed to process image {num}: {e}")
                return {
                    "type": "text",
                    "text": f"[Image processing failed: {block.get('caption', '')}]",
                    "page_idx": page_idx,
                }
        else:
            try:
                return {
                    "type": "table",
                    "img_path": "",
                    "table_caption": block.get("caption", ""),
                    "table_footnote": block.get("footnote", ""),
                    "table_body": block.get("data", []),
                    "page_idx": page_idx,
                }
            except Exception as e:
                self.logger.warning(f"Failed to process table {num}: {e}")
                return {
                    "type": "text",
                    "text": f"[Table processing failed: {block.get('caption', '')}]",
                    "page_idx": page_idx,
                }

    @staticmethod
    def _page_index_from_block(block: Dict[str, Any], *, fallback: int) -> int:
        """Use Docling provenance, never traversal order, for source page IDs."""
        provenance = block.get("prov") if isinstance(block, dict) else None
        if isinstance(provenance, dict):
            provenance = [provenance]
        if isinstance(provenance, list):
            for entry in provenance:
                if not isinstance(entry, dict):
                    continue
                try:
                    page_no = int(entry.get("page_no"))
                except (TypeError, ValueError):
                    continue
                if page_no > 0:
                    return page_no - 1
        return max(0, fallback)

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

            # HTML formats belong to the HTML pipeline; delegate before the
            # OFFICE_FORMATS check rejects them.
            if doc_path.suffix.lower() in self.HTML_FORMATS:
                return self.parse_html(
                    html_path=doc_path,
                    output_dir=output_dir,
                    lang=lang,
                    **kwargs,
                )

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
            _prepare_docling_ascii_runtime()
            from docling.document_converter import DocumentConverter  # noqa: F401

            return True
        except ImportError:
            self.logger.debug(
                "Docling Python package is not installed. "
                "Install it with: pip install docling"
            )
            return False

