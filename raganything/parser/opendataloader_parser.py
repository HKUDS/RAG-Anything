"""
OpenDataLoader PDF Parser Adapter.

Provides ``OpenDataLoaderParser`` — an explicitly selected, PDF-only backend
that invokes the pinned ``opendataloader-pdf==2.5.0`` Python SDK inside the
existing background document worker.  The adapter normalises the upstream JSON
output into the project's content-list contract and retains parser provenance
in a durable sidecar manifest.

Features (design §2–§3):
- Local fast-mode conversion only (no hybrid, no remote, no fallback).
- Validates the Java runtime and Python package before accepting work.
- Requires a complete, non-overlapping page-coverage manifest before any
  parsed content may be cached or inserted.
- Retains upstream element ID, source page, bounding box, and semantic type
  in an atomic JSON sidecar manifest beneath the parser output directory.
- Enforces file-size / page-count / timeout / output-root containment limits.
- Normalises bounding boxes to ``[left, bottom, right, top]`` in PDF points
  with bottom-left origin.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from raganything.asset_urls import attach_public_media_urls
from raganything.parser.base import Parser

# ── constants ──────────────────────────────────────────────────────────
_PACKAGE_NAME = "opendataloader-pdf"
_PINNED_VERSION = "2.5.0"
_ADAPTER_SCHEMA_VERSION = "1"
_JAVA_MIN_MAJOR = 17
_DEFAULT_TIMEOUT = int(os.getenv("ODL_TIMEOUT", "600"))  # 10 min default
_DEFAULT_PAGE_TIMEOUT = int(os.getenv("ODL_PAGE_TIMEOUT", "120"))
_DEFAULT_HEAP = os.getenv("ODL_JAVA_HEAP", "-Xmx2g")
_DEFAULT_THREADS = "1"
_DEFAULT_MAX_PAGES = int(os.getenv("ODL_MAX_PAGES", "500"))
_DEFAULT_MAX_BYTES = int(os.getenv("ODL_MAX_BYTES", str(200 * 1024 * 1024)))  # 200 MiB
_DEFAULT_CONCURRENCY = max(1, int(os.getenv("ODL_CONCURRENCY", "1")))
_JAVA_HEAP_RE = re.compile(r"-Xmx[1-9][0-9]*[mMgG]")
_RUNNER_RESULT_SCHEMA = "opendataloader-runner-result-v1"
_CONVERSION_SEMAPHORE = threading.BoundedSemaphore(_DEFAULT_CONCURRENCY)

# ── structured error helpers ────────────────────────────────────────────

def _trim_path_for_log(path: str | Path, working_dir: str = "") -> str:
    """Return a relative path when *path* is inside *working_dir*."""
    try:
        rp = Path(path).resolve()
        if working_dir:
            wd = Path(working_dir).resolve()
            try:
                return str(rp.relative_to(wd))
            except ValueError:
                pass
        return str(rp)
    except Exception:
        return str(path)


class OpenDataLoaderError(RuntimeError):
    """Base for parser-stage failures emitted by the OpenDataLoader adapter."""

    def __init__(self, message: str, failure_code: str = "odl_error"):
        super().__init__(message)
        self.failure_code = failure_code


class ODLPreflightError(OpenDataLoaderError):
    """Pre-conversion check failed (missing Java, bad package, etc.)."""

    def __init__(self, message: str):
        super().__init__(message, failure_code="odl_preflight")


class ODLConversionError(OpenDataLoaderError):
    """Upstream conversion failed (non-zero exit, timeout)."""

    def __init__(self, message: str):
        super().__init__(message, failure_code="odl_conversion")


class ODLValidationError(OpenDataLoaderError):
    """Upstream artifacts are malformed or incomplete."""

    def __init__(self, message: str):
        super().__init__(message, failure_code="odl_validation")


class ODLPageCoverageError(OpenDataLoaderError):
    """Page-coverage proof is missing or incomplete."""

    def __init__(self, message: str, coverage: Dict[str, Any] | None = None):
        super().__init__(message, failure_code="pdf_page_coverage_incomplete")
        self.page_coverage = coverage


class ODLContainerError(OpenDataLoaderError):
    """Media path escapes the output directory."""

    def __init__(self, message: str):
        super().__init__(message, failure_code="odl_container")


# ── adapter ─────────────────────────────────────────────────────────────

class OpenDataLoaderParser(Parser):
    """PDF-only parser backed by OpenDataLoader PDF 2.5.0 (local fast mode).

    Instantiate per-conversion — a single instance handles one document.
    """

    __slots__ = (
        "_odl_timeout",
        "_odl_page_timeout",
        "_odl_heap",
        "_odl_threads",
        "_odl_max_pages",
        "_odl_max_bytes",
    )

    logger = logging.getLogger(__name__)

    def __init__(
        self,
        timeout: int | None = None,
        java_heap: str | None = None,
        threads: int | None = None,
        max_pages: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        super().__init__()
        self._odl_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
        self._odl_page_timeout = min(
            self._odl_timeout,
            int(os.getenv("ODL_PAGE_TIMEOUT", str(_DEFAULT_PAGE_TIMEOUT))),
        )
        self._odl_heap = java_heap or _DEFAULT_HEAP
        self._odl_threads = str(threads or _DEFAULT_THREADS)
        self._odl_max_pages = max_pages if max_pages is not None else _DEFAULT_MAX_PAGES
        self._odl_max_bytes = max_bytes if max_bytes is not None else _DEFAULT_MAX_BYTES

    # ── identity ────────────────────────────────────────────────────

    @staticmethod
    def cache_identity() -> Dict[str, Any]:
        """Stable identity for parse-cache key derivation.

        Changes when the backend, pinned version, adapter schema, or
        behaviour-affecting options change.
        """
        return {
            "backend": "opendataloader",
            "package": _PACKAGE_NAME,
            "pinned_version": _PINNED_VERSION,
            "adapter_schema": _ADAPTER_SCHEMA_VERSION,
            "mode": "fast_local",
            "java_min_major": _JAVA_MIN_MAJOR,
            "threads": _DEFAULT_THREADS,
            "timeout_seconds": _DEFAULT_TIMEOUT,
            "page_timeout_seconds": _DEFAULT_PAGE_TIMEOUT,
            "max_pages": _DEFAULT_MAX_PAGES,
            "max_bytes": _DEFAULT_MAX_BYTES,
        }

    # ── installation check ──────────────────────────────────────────

    @staticmethod
    def _find_java() -> Optional[Path]:
        """Locate a ``java`` executable.

        Checks ``JAVA_HOME``, then ``PATH``.
        Returns the resolved path or ``None``.
        """
        java_home = os.getenv("JAVA_HOME")
        if java_home:
            candidate = Path(java_home) / "bin" / "java"
            if os.name == "nt":
                candidate = candidate.with_suffix(".exe")
            if candidate.is_file():
                return candidate.resolve()

        # PATH scan
        for d in os.getenv("PATH", "").split(os.pathsep):
            d = d.strip()
            if not d:
                continue
            candidate = Path(d) / "java"
            if os.name == "nt":
                candidate = candidate.with_suffix(".exe")
            if candidate.is_file():
                return candidate.resolve()
        return None

    @staticmethod
    def _java_version(java_bin: Path) -> Tuple[int, int, int]:
        """Return ``(major, minor, patch)`` for *java_bin*.

        Raises ``ODLPreflightError`` if the version cannot be parsed.
        """
        try:
            proc = subprocess.run(
                [str(java_bin), "-version"],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            output = proc.stderr or proc.stdout  # Java prints version to stderr
        except Exception as exc:
            raise ODLPreflightError(
                f"Failed to invoke Java at {java_bin}: {exc}"
            ) from exc

        import re
        # Match lines like: openjdk version "17.0.19" 2026-04-21
        m = re.search(r'version\s+"(\d+)\.(\d+)\.(\d+)"', output)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Alternate: openjdk version "1.8.0_402"
        m = re.search(r'version\s+"1\.(\d+)\.(\d+)[_\d]*"', output)
        if m:
            return int(m.group(1)), int(m.group(2)), 0
        raise ODLPreflightError(
            f"Cannot determine Java version from: {output[:200]}"
        )

    def check_installation(self) -> bool:
        """Verify the Python package and a compatible Java runtime.

        Never makes a network call.  Returns ``True`` when both prereqs
        are available; returns ``False`` rather than raising when the
        optional dependency is absent.
        """
        # 1. Python package
        try:
            import opendataloader_pdf  # noqa: F401
        except ImportError:
            self.logger.debug(
                "OpenDataLoader PDF Python package is not installed. "
                "Install with: pip install opendataloader-pdf==%s",
                _PINNED_VERSION,
            )
            return False
        try:
            from importlib.metadata import version

            if version(_PACKAGE_NAME) != _PINNED_VERSION:
                self.logger.debug(
                    "OpenDataLoader PDF version must be %s.", _PINNED_VERSION
                )
                return False
        except Exception:
            return False

        # 2. Java runtime
        java = self._find_java()
        if java is None:
            self.logger.debug(
                "Java runtime not found. Please install JRE %d+ "
                "and set JAVA_HOME or add java to PATH.",
                _JAVA_MIN_MAJOR,
            )
            return False

        try:
            major, _, _ = self._java_version(java)
            if major < _JAVA_MIN_MAJOR:
                self.logger.debug(
                    "Java %d is below minimum required version %d.",
                    major,
                    _JAVA_MIN_MAJOR,
                )
                return False
        except ODLPreflightError:
            return False

        return True

    # ── preflight ───────────────────────────────────────────────────

    def _preflight_pdf(self, pdf_path: Path) -> None:
        """Reject PDFs that exceed configured limits."""
        file_size = pdf_path.stat().st_size
        if file_size > self._odl_max_bytes:
            raise ODLPreflightError(
                f"PDF size {file_size} bytes exceeds limit of "
                f"{self._odl_max_bytes} bytes"
            )
        if file_size == 0:
            raise ODLPreflightError("PDF file is empty")

        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            page_count = len(reader.pages)
        except ImportError:
            # pypdf is a required dependency of this project
            raise ODLPreflightError("pypdf is required for page counting")
        except Exception as exc:
            raise ODLPreflightError(f"Cannot read PDF page count: {exc}") from exc

        if page_count > self._odl_max_pages:
            raise ODLPreflightError(
                f"PDF page count {page_count} exceeds limit of "
                f"{self._odl_max_pages}"
            )
        if page_count == 0:
            raise ODLPreflightError("PDF has zero pages")

    # ── conversion ──────────────────────────────────────────────────

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
        """Terminate a runner and every JVM child it owns."""
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            process.kill()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _contained_path(path: Path, root: Path) -> Path:
        resolved = path.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ODLContainerError("Parser artifact escapes the output directory") from exc
        return resolved

    def _run_single_page_runner(
        self,
        pdf_path: Path,
        page_dir: Path,
        source_pages: int,
        page: int,
        timeout: float,
    ) -> Dict[str, Any]:
        """Run the official SDK in a supervised child process for one page."""
        if not _JAVA_HEAP_RE.fullmatch(self._odl_heap):
            raise ODLPreflightError("ODL_JAVA_HEAP must look like -Xmx2048m or -Xmx2g")
        page_dir.mkdir(parents=True, exist_ok=False)
        request_path = page_dir / "runner-request.json"
        _write_atomic_json(
            request_path,
            {
                "schema_version": "opendataloader-runner-request-v1",
                "source_pdf": str(pdf_path),
                "output_root": str(page_dir),
                "source_total_pages": source_pages,
                "page": page,
                "java_heap": self._odl_heap,
            },
        )
        popen_kwargs: Dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [sys.executable, "-m", "raganything.parser.opendataloader_runner", "--request", str(request_path)],
            **popen_kwargs,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process_tree(process)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            raise ODLConversionError(f"OpenDataLoader page {page} timed out") from exc
        result_path = self._contained_path(page_dir / "runner-result.json", page_dir)
        if return_code != 0 and not result_path.is_file():
            raise ODLConversionError(f"OpenDataLoader page {page} conversion failed")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ODLValidationError("OpenDataLoader runner did not produce valid result metadata") from exc
        if result.get("schema_version") != _RUNNER_RESULT_SCHEMA:
            raise ODLValidationError("OpenDataLoader runner result schema is invalid")
        entries = result.get("pages")
        if not isinstance(entries, list) or len(entries) != 1:
            raise ODLPageCoverageError("OpenDataLoader runner did not prove exactly one page")
        entry = entries[0]
        if not isinstance(entry, dict) or entry.get("page") != page:
            raise ODLPageCoverageError("OpenDataLoader runner returned the wrong page")
        if return_code != 0:
            raise ODLPageCoverageError(
                f"OpenDataLoader runner failed to prove page {page}", coverage={
                    "source_total_pages": source_pages,
                    "successful_pages": [],
                    "failed_pages": [page],
                    "skipped_pages": [p for p in range(1, source_pages + 1) if p != page],
                }
            )
        if entry.get("state") not in {"success", "blank"}:
            raise ODLPageCoverageError("OpenDataLoader runner did not prove page success")
        for artifact_key, hash_key in (("json_relpath", "json_sha256"), ("markdown_relpath", "markdown_sha256")):
            relpath = entry.get(artifact_key)
            expected_hash = entry.get(hash_key)
            if not isinstance(relpath, str) or not isinstance(expected_hash, str):
                raise ODLValidationError("OpenDataLoader runner artifact metadata is invalid")
            artifact = self._contained_path(page_dir / relpath, page_dir)
            if not artifact.is_file() or self._sha256(artifact) != expected_hash:
                raise ODLValidationError("OpenDataLoader runner artifact identity check failed")
        entry["output_root"] = page_dir
        return entry

    # ── artifact discovery & validation ─────────────────────────────

    @staticmethod
    def _find_json_artifact(output_dir: Path, file_stem: str) -> Path:
        """Find the expected JSON artifact deterministically.

        Raises ``ODLValidationError`` if missing or ambiguous.
        """
        # Primary: <file_stem>.json directly in output_dir
        primary = output_dir / f"{file_stem}.json"
        if primary.is_file():
            return primary

        # Secondary: scan one level deep
        candidates = list(output_dir.glob(f"**/{file_stem}.json"))
        if not candidates:
            raise ODLValidationError(
                f"No JSON artifact found for '{file_stem}' in {output_dir}"
            )
        if len(candidates) > 1:
            raise ODLValidationError(
                f"Ambiguous JSON artifacts for '{file_stem}': "
                f"{[str(c.relative_to(output_dir)) for c in candidates]}"
            )
        return candidates[0]

    @staticmethod
    def _read_and_validate_json(json_path: Path) -> Dict[str, Any]:
        """Parse and validate the upstream JSON.

        Returns the parsed dict with required keys.
        Raises ``ODLValidationError`` on schema violations.
        """
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise ODLValidationError(f"Failed to read JSON artifact: {exc}") from exc

        if not isinstance(data, dict):
            raise ODLValidationError(
                f"Expected JSON object, got {type(data).__name__}"
            )

        # Required top-level keys
        required = ("file name", "number of pages", "kids")
        missing = [k for k in required if k not in data]
        if missing:
            raise ODLValidationError(
                f"JSON missing required top-level keys: {missing}"
            )

        kids = data.get("kids")
        if not isinstance(kids, list):
            raise ODLValidationError(
                f"Expected 'kids' to be a list, got {type(kids).__name__}"
            )

        pages = data.get("number of pages")
        if not isinstance(pages, int) or pages <= 0:
            raise ODLValidationError(
                f"'number of pages' must be a positive integer, got {pages!r}"
            )

        return data

    @staticmethod
    def _resolve_media_path(
        image_ref: str, output_root: Path
    ) -> Optional[Path]:
        """Resolve a media reference safely within *output_root*.

        Returns the absolute resolved path, or ``None`` if the reference
        would escape *output_root* or the file does not exist.
        """
        if not image_ref:
            return None
        # Absolute paths: verify containment
        candidate = Path(image_ref)
        if not candidate.is_absolute():
            candidate = output_root / image_ref
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        try:
            resolved.relative_to(output_root.resolve())
        except ValueError:
            # Path escapes the output root
            return None
        if resolved.is_file():
            return resolved
        return None

    # ── element flattening & normalisation ──────────────────────────

    @staticmethod
    def _flatten_elements(
        kids: List[Dict[str, Any]],
        output_root: Path,
        working_dir: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], set]:
        """Recursively flatten the ``kids`` tree into normalised content blocks.

        Returns ``(content_list, provenance_entries, pages_seen)``.
        """
        content_list: List[Dict[str, Any]] = []
        provenance: List[Dict[str, Any]] = []
        pages_seen: set = set()

        def _walk(children: List[Dict[str, Any]]) -> None:
            for el in children:
                if not isinstance(el, dict):
                    continue

                el_type = el.get("type", "")
                el_id = el.get("id")
                src_page = el.get("page number")
                bbox = el.get("bounding box")
                content = el.get("content", "")
                text_level = el.get("text_level")
                pdfua_tag = el.get("pdfua_tag", "")

                # Track pages
                if isinstance(src_page, (int, float)):
                    pages_seen.add(int(src_page))
                    page_idx = int(src_page) - 1  # convert to 0-based
                else:
                    page_idx = 0

                # Determine heading depth from various sources
                heading_depth = _extract_heading_depth(el_type, pdfua_tag, text_level, content)

                # Build provenance entry
                prov_entry = {
                    "odl_id": el_id,
                    "odl_type": el_type,
                    "odl_pdfua_tag": pdfua_tag,
                    "source_page": int(src_page) if isinstance(src_page, (int, float)) else None,
                    "page_idx": page_idx,
                }
                if bbox is not None:
                    prov_entry["bbox"] = _normalize_bbox(bbox)
                    prov_entry["bbox_coordinate_system"] = {
                        "units": "PDF points",
                        "origin": "bottom-left",
                        "order": ["left", "bottom", "right", "top"],
                    }
                if heading_depth is not None:
                    prov_entry["heading_depth"] = heading_depth

                # Normalise by element type
                if el_type in ("heading",) or pdfua_tag and pdfua_tag.startswith("H"):
                    # heading → text block with text_level
                    block = {
                        "type": "text",
                        "text": str(content or ""),
                        "page_idx": page_idx,
                    }
                    if heading_depth is not None:
                        block["text_level"] = heading_depth
                    content_list.append(block)

                elif el_type in ("paragraph", "caption", "list_item", "list item"):
                    # text block
                    text = str(content or "") if content else ""
                    block = {"type": "text", "text": text, "page_idx": page_idx}
                    if heading_depth is not None:
                        block["text_level"] = heading_depth
                    content_list.append(block)

                elif el_type == "list":
                    # Container — elements already extracted from list_items
                    # above, so we only track provenance for this container.
                    pass

                elif el_type == "table":
                    # Table — generate normalized table block from cells/labels
                    table_block = _build_table_block(el, output_root, page_idx, working_dir)
                    if table_block:
                        content_list.append(table_block)

                elif el_type in ("figure", "image"):
                    # Image block
                    image_block = _build_image_block(el, output_root, page_idx, working_dir)
                    if image_block:
                        content_list.append(image_block)
                    else:
                        # Safe text fallback
                        content_list.append({
                            "type": "text",
                            "text": f"[Image: {el.get('alt','') or el.get('caption','') or 'unnamed'}]",
                            "page_idx": page_idx,
                        })

                elif el_type in ("formula", "equation"):
                    # Equation → text representation or existing contract
                    formula_text = str(content or "")
                    content_list.append({
                        "type": "text",
                        "text": formula_text if formula_text else "[Formula]",
                        "page_idx": page_idx,
                    })

                else:
                    # Unknown type – safe text fallback if there's content
                    if content:
                        content_list.append({
                            "type": "text",
                            "text": str(content),
                            "page_idx": page_idx,
                        })
                    else:
                        content_list.append({
                            "type": "text",
                            "text": f"[Unsupported OpenDataLoader element: {el_type or 'unknown'}]",
                            "page_idx": page_idx,
                        })

                provenance.append(prov_entry)

                # Recurse into nested kids (e.g. list items inside lists)
                for child_key in ("kids", "children", "list items"):
                    sub_kids = el.get(child_key)
                    if isinstance(sub_kids, list) and sub_kids:
                        _walk(sub_kids)

        _walk(kids)
        return content_list, provenance, pages_seen

    # ── main parse entry point ──────────────────────────────────────

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Parse a PDF file through OpenDataLoader.

        Returns a ``PageTrackedContent`` list carrying the coverage manifest.

        Raises:
            ODLPreflightError: Pre-conversion validation failed.
            ODLConversionError: Upstream conversion failed.
            ODLValidationError: Artifact validation failed.
            ODLPageCoverageError: Page coverage is incomplete.
        """
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        # Guard: PDF only
        if pdf_path.suffix.lower() != ".pdf":
            raise ODLValidationError(
                f"OpenDataLoader is PDF-only; cannot parse: {pdf_path.suffix}"
            )

        working_dir = os.getenv("WORKING_DIR", ".")

        # 1. Preflight
        self._preflight_pdf(pdf_path)
        if not self.check_installation():
            raise ODLPreflightError(
                "OpenDataLoader requires opendataloader-pdf==2.5.0 and Java 17+"
            )

        # 2. Output directory (unique per file path)
        if output_dir:
            base_dir = Path(output_dir)
        else:
            base_dir = pdf_path.parent / "odl_output"
        unique_out = self._unique_output_dir(base_dir, pdf_path)
        unique_out.mkdir(parents=True, exist_ok=True)
        run_root = unique_out / f"run-{time.time_ns()}"
        run_root.mkdir(parents=True, exist_ok=False)
        if not _CONVERSION_SEMAPHORE.acquire(timeout=self._odl_timeout):
            raise ODLConversionError("OpenDataLoader concurrency limit timed out")

        try:
            # 3. Source page count (pypdf)
            import pypdf
            source_pages = len(pypdf.PdfReader(str(pdf_path)).pages)

            # 4. Convert each page in an independently supervised process.
            conv_start = time.monotonic()
            content_list: List[Dict[str, Any]] = []
            provenance: List[Dict[str, Any]] = []
            successful_pages: List[int] = []
            blank_pages: List[int] = []
            raw_artifacts: List[Dict[str, Any]] = []
            deadline = conv_start + self._odl_timeout
            for page in range(1, source_pages + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ODLConversionError("OpenDataLoader conversion exceeded total timeout")
                page_dir = run_root / "pages" / f"page-{page:04d}"
                entry = self._run_single_page_runner(
                    pdf_path,
                    page_dir,
                    source_pages,
                    page,
                    min(self._odl_page_timeout, remaining),
                )
                json_path = self._contained_path(
                    page_dir / entry["json_relpath"], page_dir
                )
                data = self._read_and_validate_json(json_path)
                page_content, page_provenance, pages_seen = self._flatten_elements(
                    data["kids"], page_dir, working_dir
                )
                if pages_seen and pages_seen != {page}:
                    raise ODLPageCoverageError(
                        f"OpenDataLoader artifact for page {page} contains another page"
                    )
                if entry["state"] == "blank":
                    if pages_seen or page_content:
                        raise ODLPageCoverageError(
                            f"OpenDataLoader blank proof for page {page} is inconsistent"
                        )
                    blank_pages.append(page)
                else:
                    if not pages_seen or not page_content:
                        raise ODLPageCoverageError(
                            f"OpenDataLoader did not prove content for page {page}"
                        )
                    successful_pages.append(page)
                content_list.extend(page_content)
                provenance.extend(page_provenance)
                raw_artifacts.append(
                    {
                        "page": page,
                        "json": json_path.relative_to(run_root).as_posix(),
                        "json_sha256": entry["json_sha256"],
                        "markdown": (page_dir / entry["markdown_relpath"]).relative_to(run_root).as_posix(),
                        "markdown_sha256": entry["markdown_sha256"],
                    }
                )
            conv_elapsed = time.monotonic() - conv_start
            self.logger.info(
                "OpenDataLoader conversion completed in %.1fs for %s",
                conv_elapsed,
                _trim_path_for_log(pdf_path, working_dir),
            )

            all_pages = set(range(1, source_pages + 1))
            accounted_pages = set(successful_pages) | set(blank_pages)

            if accounted_pages != all_pages:
                missing = sorted(all_pages - accounted_pages)
                coverage = {
                    "source_total_pages": source_pages,
                    "successful_pages": successful_pages,
                    "failed_pages": [],
                    "skipped_pages": missing,
                }
                raise ODLPageCoverageError(
                    f"Page coverage incomplete: missing pages {missing}",
                    coverage=coverage,
                )

            coverage = {
                "source_total_pages": source_pages,
                "successful_pages": successful_pages,
                "failed_pages": [],
                "skipped_pages": [],
                # blank_pages are intentionally empty — they are covered
                # but contain zero elements.  Recorded explicitly so that
                # post-hoc analysis can distinguish "blank" from "lost".
                "blank_pages": blank_pages,
            }

            # 5. Retain content and raw-artifact identity only after coverage proof.
            sidecar_path = run_root / f"{pdf_path.stem}_provenance.json"
            normalized_identity = hashlib.sha256(
                json.dumps(content_list, ensure_ascii=True, sort_keys=True).encode("utf-8")
            ).hexdigest()
            sidecar = {
                "adapter_schema_version": _ADAPTER_SCHEMA_VERSION,
                "package": _PACKAGE_NAME,
                "pinned_version": _PINNED_VERSION,
                "source_pdf": {
                    "file": pdf_path.name,
                    "pages": source_pages,
                },
                "coverage": coverage,
                "raw_artifacts": raw_artifacts,
                "normalized_content_sha256": normalized_identity,
                "elements": provenance,
            }
            _write_atomic_json(sidecar_path, sidecar)

            # 6. Attach public media URLs to image blocks
            for block in content_list:
                if block.get("type") == "image" and block.get("img_path"):
                    attach_public_media_urls(block)

            # 7. Return PageTrackedContent
            from raganything.parser.office_parser import PageTrackedContent
            result = PageTrackedContent(content_list, coverage)
            self.logger.info(
                "OpenDataLoader parsed %s: %d pages, %d blocks, %d blank pages",
                _trim_path_for_log(pdf_path, working_dir),
                source_pages,
                len(content_list),
                len(blank_pages),
            )
            return result

        except (ODLPreflightError, ODLConversionError,
                ODLValidationError, ODLPageCoverageError, ODLContainerError):
            raise
        except FileNotFoundError:
            raise
        except Exception as exc:
            self.logger.error(
                "Unexpected error in OpenDataLoader parse_pdf: %s", exc
            )
            raise ODLConversionError(
                f"Unexpected parser error: {exc}"
            ) from exc
        finally:
            _CONVERSION_SEMAPHORE.release()

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Route to ``parse_pdf`` for PDF inputs only."""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return self.parse_pdf(file_path, output_dir, method, lang, **kwargs)
        if ext in self.OFFICE_FORMATS | self.IMAGE_FORMATS | self.TEXT_FORMATS:
            raise ODLValidationError(
                f"OpenDataLoader is PDF-only; file type '{ext}' is not supported. "
                f"Use the global parser for non-PDF documents."
            )
        raise ODLValidationError(
            f"Unsupported file type '{ext}' for OpenDataLoader."
        )


# ═══════════════════════════════════════════════════════════════════════
# internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _extract_heading_depth(
    el_type: str,
    pdfua_tag: str,
    text_level: Any,
    content: str,
) -> Optional[int]:
    """Determine the heading depth from element metadata.

    Priority: pdfua_tag ≥ el_type prefix ≥ text_level field ≥ content heuristic.
    """
    # From PDF/UA tag: H1 → 1, H2 → 2, ...
    if isinstance(pdfua_tag, str) and pdfua_tag.startswith("H"):
        try:
            return int(pdfua_tag[1:])
        except (ValueError, IndexError):
            pass

    # From element type: heading_1 → 1
    if isinstance(el_type, str):
        if el_type.startswith("heading"):
            if "_" in el_type:
                try:
                    return int(el_type.split("_")[-1])
                except (ValueError, IndexError):
                    pass
            return 1  # bare "heading" → level 1

    # From explicit text_level
    if isinstance(text_level, int):
        return max(1, text_level)

    # From content (heuristic: "1. ", "1.1" etc.)
    if isinstance(content, str) and content.strip():
        stripped = content.strip()
        import re
        m = re.match(r'^(\d+(?:\.\d+)*)\s', stripped)
        if m:
            return len(m.group(1).split("."))

    return None


def _normalize_bbox(raw_bbox: List[float]) -> List[float]:
    """Normalise a bounding box to ``[left, bottom, right, top]``.

    OpenDataLoader 2.5.0 emits bbox as ``[left, bottom, right, top]``
    in PDF points with bottom-left origin — this is already the target
    format, but we validate the shape.
    """
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        raise ODLValidationError(
            f"Expected 4-element bounding box, got {raw_bbox!r}"
        )
    return [float(v) for v in raw_bbox]


def _build_table_block(
    el: Dict[str, Any],
    output_root: Path,
    page_idx: int,
    working_dir: str,
) -> Optional[Dict[str, Any]]:
    """Build a normalised table block from an OpenDataLoader table element.

    The upstream table element may have ``labels`` (header) and ``cells``
    (data rows).  Normalises into a Markdown-style ``table_body`` string.
    """
    rows = []

    # Labels (header row)
    labels = el.get("labels") or []
    if labels:
        rows.append([str(c.get("content", "")) for c in labels])
        rows.append(["---" for _ in labels])

    # Cells
    cells = el.get("cells") or el.get("rows") or []
    for row in cells:
        if isinstance(row, dict):
            row_cells = row.get("cells") or row.get("content") or [row]
        elif isinstance(row, list):
            row_cells = row
        else:
            continue
        rows.append([
            str(c.get("content", "")) if isinstance(c, dict) else str(c)
            for c in row_cells
        ])

    if not rows:
        # Fallback: extract from content string
        content = str(el.get("content", ""))
        if content:
            return {"type": "text", "text": content, "page_idx": page_idx}
        return None

    # Build Markdown table body
    md_lines = []
    for i, row in enumerate(rows):
        md_lines.append("| " + " | ".join(row) + " |")
        if i == 0 and len(rows) > 1 and rows[1] != ["---" for _ in labels]:
            # Insert separator row after header if not present
            md_lines.append("| " + " | ".join(["---"] * len(row)) + " |")

    table_body = "\n".join(md_lines)
    caption = str(el.get("caption", ""))
    block: Dict[str, Any] = {
        "type": "table",
        "table_body": table_body,
        "page_idx": page_idx,
    }
    if caption:
        block["caption"] = caption

    # Attach table image if present
    table_img = el.get("image") or el.get("table_img_path")
    if table_img:
        resolved = OpenDataLoaderParser._resolve_media_path(
            str(table_img), output_root
        )
        if resolved:
            block["img_path"] = str(resolved)
            attach_public_media_urls(block)

    return block


def _build_image_block(
    el: Dict[str, Any],
    output_root: Path,
    page_idx: int,
    working_dir: str,
) -> Optional[Dict[str, Any]]:
    """Build a normalised image block from an OpenDataLoader figure/image element.

    Resolves the image path safely within the output root.  Returns ``None``
    on unsafe or missing references.
    """
    image_ref = el.get("image") or el.get("img_path") or el.get("src") or ""
    if not image_ref:
        # Check for embedded Base64 data URI
        content = el.get("content") or ""
        if content and content.startswith("data:image/"):
            # Base64 embedded — we cannot use it directly on disk
            return {
                "type": "text",
                "text": f"[Embedded Image: {el.get('alt','') or el.get('caption','') or 'unnamed'}]",
                "page_idx": page_idx,
            }
        return None

    resolved = OpenDataLoaderParser._resolve_media_path(str(image_ref), output_root)
    if resolved is None:
        # Path escape or missing — safe text fallback
        return {
            "type": "text",
            "text": f"[Image: {el.get('alt','') or el.get('caption','') or Path(image_ref).name}]",
            "page_idx": page_idx,
        }

    block: Dict[str, Any] = {
        "type": "image",
        "img_path": str(resolved),
        "page_idx": page_idx,
    }
    caption = el.get("caption") or el.get("alt") or ""
    if caption:
        block["image_caption"] = str(caption)
        block["img_caption"] = str(caption)  # legacy alias
    return block


def _write_atomic_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write *data* as JSON to *path* using a temp file + rename."""
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".json", prefix=path.stem + "_", dir=path.parent
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise
