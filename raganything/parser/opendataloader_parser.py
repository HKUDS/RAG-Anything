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
import math
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
from raganything.services.odl_media_manifest import build_media_entry, write_pending_manifest
from raganything.utils.process_lock import FileLock, get_lock_dir

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
_DEFAULT_MAX_OUTPUT_BYTES = int(
    os.getenv("ODL_MAX_OUTPUT_BYTES", str(1024 * 1024 * 1024))
)  # 1 GiB
_DEFAULT_CONCURRENCY = max(1, int(os.getenv("ODL_CONCURRENCY", "1")))
_TINY_FRAGMENT_MAX_SHORT_EDGE = 22
_FRAGMENT_DENSE_MIN_IMAGES = 8
_FRAGMENT_DENSE_TINY_FRACTION = 0.80
_PAGE_RENDER_SCALE = 2
_JAVA_HEAP_RE = re.compile(r"-Xmx[1-9][0-9]*[mMgG]")
_RUNNER_RESULT_SCHEMA = "opendataloader-runner-result-v1"
_RUNNER_FAILURE_CATEGORIES = frozenset(
    {
        "upstream_process_failed",
        "upstream_timeout",
        "runtime_not_found",
        "artifact_validation_failed",
        "runner_io_failed",
        "runner_exception",
    }
)
_CONVERSION_SEMAPHORE = threading.BoundedSemaphore(_DEFAULT_CONCURRENCY)

# The runner executes a third-party Python package and its JVM.  Do not pass
# the worker's complete environment (which commonly contains model/API
# credentials) into that process.
_RUNNER_ENV_ALLOWLIST = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)

# ── structured error helpers ────────────────────────────────────────────


def _trim_path_for_log(path: str | Path, working_dir: str = "") -> str:
    """Return a safe, non-absolute identifier for parser telemetry."""
    try:
        rp = Path(path).resolve()
        if working_dir:
            wd = Path(working_dir).resolve()
            try:
                return str(rp.relative_to(wd))
            except ValueError:
                pass
        return rp.name or "<external-file>"
    except Exception:
        return "<unavailable-file>"


def _resolve_output_base(output_dir: str | Path | None, pdf_path: Path) -> Path:
    """Return one absolute root for all retained parser artifacts."""
    base = Path(output_dir) if output_dir else pdf_path.parent / "odl_output"
    return base.resolve()


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
        "_odl_max_output_bytes",
        "_odl_concurrency",
    )

    logger = logging.getLogger(__name__)

    def __init__(
        self,
        timeout: int | None = None,
        java_heap: str | None = None,
        threads: int | None = None,
        max_pages: int | None = None,
        max_bytes: int | None = None,
        max_output_bytes: int | None = None,
        concurrency: int | None = None,
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
        self._odl_max_output_bytes = (
            max_output_bytes
            if max_output_bytes is not None
            else _DEFAULT_MAX_OUTPUT_BYTES
        )
        self._odl_concurrency = max(1, concurrency or _DEFAULT_CONCURRENCY)

    def _log_parse_outcome(
        self,
        outcome_category: str,
        operation_start: float,
        *,
        page_count: int = 0,
        block_count: int = 0,
        success: bool = False,
    ) -> None:
        """Emit the bounded OpenDataLoader telemetry contract."""
        fields = {
            "backend": "opendataloader",
            "sdk_version": _PINNED_VERSION,
            "page_count": max(0, int(page_count)),
            "block_count": max(0, int(block_count)),
            "elapsed_ms": int(max(0.0, time.monotonic() - operation_start) * 1000),
            "outcome_category": outcome_category,
        }
        log_method = self.logger.info if success else self.logger.warning
        log_method(
            "OpenDataLoader parse outcome: category=%s",
            outcome_category,
            extra={"odl_parse_outcome": fields},
        )

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
            "java_heap": _DEFAULT_HEAP,
            "timeout_seconds": _DEFAULT_TIMEOUT,
            "page_timeout_seconds": _DEFAULT_PAGE_TIMEOUT,
            "max_pages": _DEFAULT_MAX_PAGES,
            "max_bytes": _DEFAULT_MAX_BYTES,
            "max_output_bytes": _DEFAULT_MAX_OUTPUT_BYTES,
            "concurrency": _DEFAULT_CONCURRENCY,
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
            raise ODLPreflightError("Failed to invoke Java runtime") from exc

        import re

        # Match lines like: openjdk version "17.0.19" 2026-04-21
        m = re.search(r'version\s+"(\d+)\.(\d+)\.(\d+)"', output)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Alternate: openjdk version "1.8.0_402"
        m = re.search(r'version\s+"1\.(\d+)\.(\d+)[_\d]*"', output)
        if m:
            return int(m.group(1)), int(m.group(2)), 0
        raise ODLPreflightError("Cannot determine Java version")

    def check_installation(self) -> bool:
        """Verify the Python package and a compatible Java runtime.

        Never makes a network call.  Returns ``True`` when both prereqs
        are available; returns ``False`` rather than raising when the
        optional dependency is absent.
        """
        return self.installation_error() is None

    def installation_error(self) -> str | None:
        """Return an actionable, non-network runtime prerequisite error."""
        # 1. Python package
        try:
            import opendataloader_pdf  # noqa: F401
        except ImportError:
            return (
                "OpenDataLoader Python package is not installed; install "
                f"opendataloader-pdf=={_PINNED_VERSION} with the opendataloader extra"
            )
        try:
            from importlib.metadata import version

            if version(_PACKAGE_NAME) != _PINNED_VERSION:
                return (
                    f"OpenDataLoader Python package must be version {_PINNED_VERSION}; "
                    "reinstall the opendataloader extra"
                )
        except Exception:
            return "OpenDataLoader Python package version cannot be determined"

        # 2. Java runtime
        java = self._find_java()
        if java is None:
            return (
                f"Java {_JAVA_MIN_MAJOR}+ runtime not found; set JAVA_HOME "
                "or add java to PATH"
            )

        try:
            major, _, _ = self._java_version(java)
            if major < _JAVA_MIN_MAJOR:
                return (
                    f"Java {major} is unsupported; install Java {_JAVA_MIN_MAJOR}+ "
                    "and update JAVA_HOME"
                )
        except ODLPreflightError:
            return "Java version cannot be determined; install a supported Java runtime"

        return None

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
            raise ODLPreflightError("Cannot read PDF page count") from exc

        if page_count > self._odl_max_pages:
            raise ODLPreflightError(
                f"PDF page count {page_count} exceeds limit of {self._odl_max_pages}"
            )
        if page_count == 0:
            raise ODLPreflightError("PDF has zero pages")

    # ── conversion ──────────────────────────────────────────────────

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
        """Terminate a runner and every JVM child it owns, or fail closed."""
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ODLConversionError(
                    "Unable to terminate OpenDataLoader process tree"
                ) from exc
            if completed.returncode != 0:
                raise ODLConversionError(
                    "OpenDataLoader process-tree termination failed"
                )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                    return
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError as exc:
                raise ODLConversionError(
                    "Unable to terminate OpenDataLoader process group"
                ) from exc
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise ODLConversionError(
                "OpenDataLoader process tree did not exit after termination"
            ) from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with OpenDataLoaderParser._open_verified_file(path) as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _open_verified_file(path: Path):
        """Open a regular artifact without accepting a symlink replacement."""
        before = path.lstat()
        if not path.is_file() or path.is_symlink():
            raise ODLContainerError("Parser artifact is not a regular file")
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(path), flags)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                raise ODLContainerError("Parser artifact changed during open")
            return os.fdopen(fd, "rb")
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _contained_path(path: Path, root: Path) -> Path:
        try:
            if path.is_symlink():
                raise ODLContainerError("Parser artifact must not be a symbolic link")
        except OSError as exc:
            raise ODLContainerError("Cannot inspect parser artifact") from exc
        resolved = path.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ODLContainerError(
                "Parser artifact escapes the output directory"
            ) from exc
        return resolved

    @staticmethod
    def _output_size(root: Path) -> int:
        """Return output bytes without following links outside *root*."""
        total = 0
        for candidate in root.rglob("*"):
            try:
                stat_result = candidate.lstat()
            except OSError as exc:
                raise ODLContainerError("Cannot inspect parser artifact") from exc
            if candidate.is_symlink():
                raise ODLContainerError("Parser artifact contains a symbolic link")
            if candidate.is_file():
                total += stat_result.st_size
        return total

    @staticmethod
    def _acquire_cross_process_slot(
        working_dir: str, capacity: int, deadline: float
    ) -> FileLock:
        """Reserve one shared OpenDataLoader slot across document workers."""
        lock_dir = get_lock_dir(working_dir) / "opendataloader"
        while time.monotonic() < deadline:
            for slot in range(capacity):
                lock = FileLock(str(lock_dir / f"slot-{slot}.lock"))
                if lock.acquire():
                    return lock
            time.sleep(0.1)
        raise ODLConversionError("OpenDataLoader concurrency limit timed out")

    def _run_single_page_runner(
        self,
        pdf_path: Path,
        page_dir: Path,
        source_pages: int,
        page: int,
        timeout: float,
        java_bin: Path,
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
                "max_output_bytes": self._odl_max_output_bytes,
            },
        )
        runner_env = {
            key: value
            for key in _RUNNER_ENV_ALLOWLIST
            if (value := os.environ.get(key))
        }
        runner_env["JAVA_HOME"] = str(java_bin.parent.parent)
        runner_env["PATH"] = (
            str(java_bin.parent)
            + os.pathsep
            + str(Path(sys.executable).resolve().parent)
            + os.pathsep
            + str(Path(os.environ.get("SYSTEMROOT", "")).resolve() / "System32")
        )
        popen_kwargs: Dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": runner_env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "raganything.parser.opendataloader_runner",
                "--request",
                str(request_path),
            ],
            **popen_kwargs,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process_tree(process)
            raise ODLConversionError(f"OpenDataLoader page {page} timed out") from exc
        result_path = self._contained_path(page_dir / "runner-result.json", page_dir)
        if return_code != 0 and not result_path.is_file():
            raise ODLConversionError(f"OpenDataLoader page {page} conversion failed")
        try:
            with self._open_verified_file(result_path) as result_file:
                result = json.loads(result_file.read().decode("utf-8"))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ODLContainerError,
        ) as exc:
            raise ODLValidationError(
                "OpenDataLoader runner did not produce valid result metadata"
            ) from exc
        if result.get("schema_version") != _RUNNER_RESULT_SCHEMA:
            raise ODLValidationError("OpenDataLoader runner result schema is invalid")
        entries = result.get("pages")
        if not isinstance(entries, list) or len(entries) != 1:
            raise ODLPageCoverageError(
                "OpenDataLoader runner did not prove exactly one page"
            )
        entry = entries[0]
        if not isinstance(entry, dict) or entry.get("page") != page:
            raise ODLPageCoverageError("OpenDataLoader runner returned the wrong page")
        if return_code != 0:
            category = entry.get("failure_category")
            if category not in _RUNNER_FAILURE_CATEGORIES:
                category = "invalid_runner_diagnostic"
            upstream_exit_code = entry.get("upstream_exit_code")
            if not isinstance(upstream_exit_code, int) or isinstance(
                upstream_exit_code, bool
            ):
                upstream_exit_code = None
            diagnostic = f"category={category}"
            if upstream_exit_code is not None:
                diagnostic += f", upstream_exit_code={upstream_exit_code}"
            raise ODLPageCoverageError(
                f"OpenDataLoader runner failed to prove page {page} ({diagnostic})",
                coverage={
                    "source_total_pages": source_pages,
                    "successful_pages": [],
                    "failed_pages": [page],
                    "skipped_pages": [
                        p for p in range(1, source_pages + 1) if p != page
                    ],
                },
            )
        if entry.get("state") not in {"success", "blank"}:
            raise ODLPageCoverageError(
                "OpenDataLoader runner did not prove page success"
            )
        for artifact_key, hash_key in (
            ("json_relpath", "json_sha256"),
            ("markdown_relpath", "markdown_sha256"),
        ):
            relpath = entry.get(artifact_key)
            expected_hash = entry.get(hash_key)
            if not isinstance(relpath, str) or not isinstance(expected_hash, str):
                raise ODLValidationError(
                    "OpenDataLoader runner artifact metadata is invalid"
                )
            artifact = self._contained_path(page_dir / relpath, page_dir)
            if not artifact.is_file() or self._sha256(artifact) != expected_hash:
                raise ODLValidationError(
                    "OpenDataLoader runner artifact identity check failed"
                )
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
            raise ODLValidationError("Expected JSON artifact was not produced")
        if len(candidates) > 1:
            raise ODLValidationError("Multiple JSON artifacts were produced")
        return candidates[0]

    @staticmethod
    def _read_and_validate_json(json_path: Path) -> Dict[str, Any]:
        """Parse and validate the upstream JSON.

        Returns the parsed dict with required keys.
        Raises ``ODLValidationError`` on schema violations.
        """
        try:
            with OpenDataLoaderParser._open_verified_file(json_path) as f:
                data = json.loads(f.read().decode("utf-8"))
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
            ODLContainerError,
        ) as exc:
            raise ODLValidationError("Failed to read JSON artifact") from exc

        if not isinstance(data, dict):
            raise ODLValidationError(f"Expected JSON object, got {type(data).__name__}")

        # Required top-level keys
        required = ("file name", "number of pages", "kids")
        missing = [k for k in required if k not in data]
        if missing:
            raise ODLValidationError(f"JSON missing required top-level keys: {missing}")

        kids = data.get("kids")
        if not isinstance(kids, list):
            raise ODLValidationError(
                f"Expected 'kids' to be a list, got {type(kids).__name__}"
            )

        pages = data.get("number of pages")
        if not isinstance(pages, int) or pages <= 0:
            raise ODLValidationError("'number of pages' must be a positive integer")

        return data

    @staticmethod
    def _resolve_media_path(image_ref: str, output_root: Path) -> Optional[Path]:
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
    def _image_semantic_identity(el: Dict[str, Any], block: Dict[str, Any]) -> str:
        """Build a stable identity for a logical upstream image element.

        Per-page SDK runs can re-export one source element into distinct page
        directories, so filesystem paths and byte digests are not stable for
        that case. Prefer the upstream element identity plus its semantic
        payload; only fall back to location/media identity when no upstream ID
        exists.
        """
        element_id = el.get("id") or el.get("element_id")
        semantic_payload = {
            "type": str(el.get("type") or "image"),
            "caption": str(el.get("caption") or ""),
            "alt": str(el.get("alt") or ""),
            "content": str(el.get("content") or ""),
        }
        if element_id is not None and str(element_id):
            identity: Dict[str, Any] = {
                "element_id": str(element_id),
                "semantic_payload": semantic_payload,
            }
        else:
            media = block.get("_odl_media")
            identity = {
                "semantic_payload": semantic_payload,
                "source_page": el.get("page number"),
                "bbox": el.get("bounding box"),
                "media_sha256": media.get("sha256") if isinstance(media, dict) else None,
            }
        return hashlib.sha256(
            json.dumps(identity, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _image_dimensions(path: Path) -> Optional[Tuple[int, int]]:
        """Return decoded image dimensions without treating decode failure as tiny."""
        try:
            from PIL import Image

            with Image.open(path) as image:
                return image.size
        except (ImportError, OSError, ValueError):
            return None

    @staticmethod
    def _render_fragment_dense_page(
        pdf_path: Path, page_number: int, output_root: Path
    ) -> Path:
        """Render one source page under its already controlled output root."""
        output_path = output_root / "odl_page_render.png"
        if output_path.exists() or output_path.is_symlink():
            raise ODLValidationError("ODL page-render output already exists")
        try:
            import pypdfium2

            document = pypdfium2.PdfDocument(str(pdf_path))
            page = document[page_number - 1]
            bitmap = page.render(scale=_PAGE_RENDER_SCALE)
            image = bitmap.to_pil()
            image.save(output_path, format="PNG")
            image.close()
            bitmap.close()
            page.close()
            document.close()
        except Exception as exc:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ODLValidationError("ODL page-render fallback failed") from exc
        if output_path.is_symlink() or not output_path.is_file():
            raise ODLValidationError("ODL page-render output is invalid")
        return output_path

    @classmethod
    def _replace_fragment_dense_images(
        cls,
        content: List[Dict[str, Any]],
        provenance: List[Dict[str, Any]],
        pdf_path: Path,
        page_number: int,
        output_root: Path,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """Replace tiny-fragment clusters with one controlled source-page render."""
        image_blocks = [
            block
            for block in content
            if block.get("type") == "image"
            and isinstance(block.get("_odl_media"), dict)
            and isinstance(block.get("img_path"), str)
        ]
        tiny_blocks = []
        for block in image_blocks:
            dimensions = cls._image_dimensions(Path(block["img_path"]))
            if dimensions and min(dimensions) <= _TINY_FRAGMENT_MAX_SHORT_EDGE:
                tiny_blocks.append(block)
        if (
            len(image_blocks) < _FRAGMENT_DENSE_MIN_IMAGES
            or len(tiny_blocks) / len(image_blocks) < _FRAGMENT_DENSE_TINY_FRACTION
        ):
            return content, 0, 0

        filtered_ids = {id(block) for block in tiny_blocks}
        for block in tiny_blocks:
            index = block.get("_odl_provenance_index")
            if isinstance(index, int) and 0 <= index < len(provenance):
                provenance[index]["media_filtered"] = "tiny_fragment"

        render_path = cls._render_fragment_dense_page(pdf_path, page_number, output_root)
        page_idx = page_number - 1
        try:
            media = build_media_entry(
                path=render_path,
                output_root=output_root,
                page=page_number,
                element_id=f"page-render-{page_number}",
                caption="",
                provenance="odl-page-render-fallback",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ODLValidationError("ODL page-render media validation failed") from exc
        render_block = {
            "type": "image",
            "img_path": str(render_path),
            "page_idx": page_idx,
            "_odl_media": media,
            "_odl_media_output_root": str(output_root),
            "_odl_provenance_index": len(provenance),
        }
        provenance.append(
            {
                "odl_id": f"page-render-{page_number}",
                "odl_type": "page_render",
                "source_page": page_number,
                "page_idx": page_idx,
                "media_generated": "fragment_dense_page",
                "media_sha256": media["sha256"],
            }
        )
        retained = [block for block in content if id(block) not in filtered_ids]
        retained.append(render_block)
        return retained, len(tiny_blocks), 1

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
                heading_depth = _extract_heading_depth(
                    el_type, pdfua_tag, text_level, content
                )

                # Build provenance entry
                prov_entry = {
                    "odl_id": el_id,
                    "odl_type": el_type,
                    "odl_pdfua_tag": pdfua_tag,
                    "source_page": (
                        int(src_page) if isinstance(src_page, (int, float)) else None
                    ),
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
                if (
                    el_type == "heading"
                    or el_type.startswith("heading_")
                    or pdfua_tag
                    and pdfua_tag.startswith("H")
                ):
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
                    table_block = _build_table_block(
                        el, output_root, page_idx, working_dir
                    )
                    if table_block:
                        media_rejected = table_block.pop("_odl_media_rejected", None)
                        if media_rejected:
                            prov_entry["media_rejected"] = media_rejected
                        content_list.append(table_block)
                        if media_rejected:
                            content_list.append(
                                {
                                    "type": "text",
                                    "text": "[Table image unavailable]",
                                    "page_idx": page_idx,
                                }
                            )

                elif el_type in ("figure", "image"):
                    # Image block
                    image_block = _build_image_block(
                        el, output_root, page_idx, working_dir
                    )
                    if image_block:
                        if image_block.get("type") == "image":
                            image_block["_odl_provenance_index"] = len(provenance)
                            media = image_block.get("_odl_media")
                            if isinstance(media, dict) and isinstance(
                                media.get("sha256"), str
                            ):
                                prov_entry["media_sha256"] = media["sha256"]
                            image_block["_odl_dedupe_key"] = (
                                OpenDataLoaderParser._image_semantic_identity(
                                    el, image_block
                                )
                            )
                        content_list.append(image_block)
                    else:
                        # Safe text fallback
                        content_list.append(
                            {
                                "type": "text",
                                "text": f"[Image: {el.get('alt', '') or el.get('caption', '') or 'unnamed'}]",
                                "page_idx": page_idx,
                            }
                        )

                elif el_type in ("formula", "equation"):
                    # Equation → text representation or existing contract
                    formula_text = str(content or "")
                    content_list.append(
                        {
                            "type": "text",
                            "text": formula_text if formula_text else "[Formula]",
                            "page_idx": page_idx,
                        }
                    )

                else:
                    # Unknown type – safe text fallback if there's content
                    if content:
                        content_list.append(
                            {
                                "type": "text",
                                "text": str(content),
                                "page_idx": page_idx,
                            }
                        )
                    else:
                        content_list.append(
                            {
                                "type": "text",
                                "text": f"[Unsupported OpenDataLoader element: {el_type or 'unknown'}]",
                                "page_idx": page_idx,
                            }
                        )

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
        operation_start = time.monotonic()
        pdf_path = Path(pdf_path).resolve()
        # Guard: PDF only
        if pdf_path.suffix.lower() != ".pdf":
            self._log_parse_outcome("odl_validation", operation_start)
            raise ODLValidationError(
                f"OpenDataLoader is PDF-only; cannot parse: {pdf_path.suffix}"
            )
        if not pdf_path.is_file():
            self._log_parse_outcome("odl_preflight", operation_start)
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        working_dir = os.getenv("WORKING_DIR", ".")

        # 1. Preflight
        try:
            self._preflight_pdf(pdf_path)
            installation_error = self.installation_error()
            if installation_error is not None:
                raise ODLPreflightError(installation_error)
            java_bin = self._find_java()
            if java_bin is None:
                raise ODLPreflightError(
                    "OpenDataLoader Java runtime disappeared after preflight"
                )
        except ODLPreflightError:
            self._log_parse_outcome("odl_preflight", operation_start)
            raise

        # 2. Output directory (unique per file path)
        base_dir = _resolve_output_base(output_dir, pdf_path)
        unique_out = self._unique_output_dir(base_dir, pdf_path)
        unique_out.mkdir(parents=True, exist_ok=True)
        run_root = unique_out / f"run-{time.time_ns()}"
        run_root.mkdir(parents=True, exist_ok=False)
        deadline = time.monotonic() + self._odl_timeout
        if not _CONVERSION_SEMAPHORE.acquire(
            timeout=max(0, deadline - time.monotonic())
        ):
            self._log_parse_outcome("odl_conversion", operation_start)
            raise ODLConversionError("OpenDataLoader concurrency limit timed out")
        cross_process_lock: FileLock | None = None
        source_pages = 0

        try:
            cross_process_lock = self._acquire_cross_process_slot(
                working_dir,
                self._odl_concurrency,
                deadline,
            )
            # 3. Source page count (pypdf)
            import pypdf

            source_pages = len(pypdf.PdfReader(str(pdf_path)).pages)

            # 4. Convert each page in an independently supervised process.
            conv_start = time.monotonic()
            content_list: List[Dict[str, Any]] = []
            provenance: List[Dict[str, Any]] = []
            image_input_count = 0
            page_local_image_deduplicated_count = 0
            exact_media_deduplicated_count = 0
            image_filtered_fragment_count = 0
            generated_page_render_count = 0
            seen_media_digests: set[str] = set()
            duplicate_identity_hashes: List[str] = []
            duplicate_media_hashes: List[str] = []
            successful_pages: List[int] = []
            blank_pages: List[int] = []
            raw_artifacts: List[Dict[str, Any]] = []
            for page in range(1, source_pages + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ODLConversionError(
                        "OpenDataLoader conversion exceeded total timeout"
                    )
                page_dir = run_root / "pages" / f"page-{page:04d}"
                entry = self._run_single_page_runner(
                    pdf_path,
                    page_dir,
                    source_pages,
                    page,
                    min(self._odl_page_timeout, remaining),
                    java_bin,
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
                seen_page_image_identities: set[str] = set()
                deduplicated_page_content: List[Dict[str, Any]] = []
                for block in page_content:
                    if block.get("type") != "image":
                        deduplicated_page_content.append(block)
                        continue
                    image_input_count += 1
                    identity = block.pop("_odl_dedupe_key", None)
                    if identity and identity in seen_page_image_identities:
                        page_local_image_deduplicated_count += 1
                        if len(duplicate_identity_hashes) < 32:
                            duplicate_identity_hashes.append(identity)
                        continue
                    if identity:
                        seen_page_image_identities.add(identity)
                    deduplicated_page_content.append(block)
                (
                    page_content,
                    filtered_fragments,
                    generated_page_renders,
                ) = self._replace_fragment_dense_images(
                    deduplicated_page_content,
                    page_provenance,
                    pdf_path,
                    page,
                    page_dir,
                )
                image_filtered_fragment_count += filtered_fragments
                generated_page_render_count += generated_page_renders
                unique_page_content: List[Dict[str, Any]] = []
                for block in page_content:
                    if block.get("type") != "image":
                        unique_page_content.append(block)
                        continue
                    media = block.get("_odl_media")
                    digest = media.get("sha256") if isinstance(media, dict) else None
                    if isinstance(digest, str) and digest in seen_media_digests:
                        exact_media_deduplicated_count += 1
                        if len(duplicate_media_hashes) < 32:
                            duplicate_media_hashes.append(digest)
                        index = block.get("_odl_provenance_index")
                        if isinstance(index, int) and 0 <= index < len(page_provenance):
                            page_provenance[index]["media_filtered"] = (
                                "exact_media_duplicate"
                            )
                        continue
                    if isinstance(digest, str):
                        seen_media_digests.add(digest)
                    unique_page_content.append(block)
                content_list.extend(unique_page_content)
                provenance.extend(page_provenance)
                raw_artifacts.append(
                    {
                        "page": page,
                        "json": json_path.relative_to(run_root).as_posix(),
                        "json_sha256": entry["json_sha256"],
                        "markdown": (page_dir / entry["markdown_relpath"])
                        .relative_to(run_root)
                        .as_posix(),
                        "markdown_sha256": entry["markdown_sha256"],
                    }
                )
                if self._output_size(run_root) > self._odl_max_output_bytes:
                    raise ODLValidationError(
                        "OpenDataLoader output exceeds configured byte limit"
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
            media_entries = [
                dict(block["_odl_media"])
                for block in content_list
                if block.get("type") == "image" and isinstance(block.get("_odl_media"), dict)
            ]
            for block, entry in zip(
                (
                    item for item in content_list
                    if item.get("type") == "image" and isinstance(item.get("_odl_media"), dict)
                ),
                media_entries,
            ):
                output_root = block.get("_odl_media_output_root")
                try:
                    root_path = Path(output_root).resolve(strict=True)
                    entry["media_root_relative_path"] = root_path.relative_to(run_root).as_posix()
                except (OSError, RuntimeError, TypeError, ValueError):
                    raise ODLValidationError("ODL media root is outside the parser run root")
            media_manifest_ref = None
            if media_entries:
                media_manifest_path = run_root / f"{pdf_path.stem}_media_manifest.json"
                media_manifest_sha256 = write_pending_manifest(media_manifest_path, media_entries)
                media_manifest_ref = {
                    "schema": "odl-media-manifest-v1",
                    "relative_path": media_manifest_path.relative_to(base_dir.resolve()).as_posix(),
                    "sha256": media_manifest_sha256,
                    "entries": len(media_entries),
                }
                # This temporary internal pointer is consumed by multimodal
                # persistence to bind chunk IDs.  It is not emitted by SSE.
                for block in content_list:
                    if isinstance(block.get("_odl_media"), dict):
                        block["_odl_media_manifest_path"] = str(media_manifest_path)
            for block in content_list:
                block.pop("_odl_provenance_index", None)
            sidecar_path = run_root / f"{pdf_path.stem}_provenance.json"
            normalized_identity = hashlib.sha256(
                json.dumps(content_list, ensure_ascii=True, sort_keys=True).encode(
                    "utf-8"
                )
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
                "media_manifest": media_manifest_ref,
                "normalization": {
                    "input_image_elements": image_input_count,
                    "emitted_image_elements": len(media_entries),
                    "deduplicated_image_elements": (
                        page_local_image_deduplicated_count
                        + exact_media_deduplicated_count
                    ),
                    "page_local_deduplicated_image_elements": (
                        page_local_image_deduplicated_count
                    ),
                    "exact_media_deduplicated_image_elements": (
                        exact_media_deduplicated_count
                    ),
                    "filtered_tiny_fragment_elements": image_filtered_fragment_count,
                    "generated_page_render_assets": generated_page_render_count,
                    "eligible_image_elements": len(media_entries),
                    "dedupe_scope": "semantic_per_page_then_exact_media_per_document",
                    "duplicate_identity_hashes": duplicate_identity_hashes,
                    "duplicate_media_hashes": duplicate_media_hashes,
                },
            }
            _write_atomic_json(sidecar_path, sidecar)
            if self._output_size(run_root) > self._odl_max_output_bytes:
                raise ODLValidationError(
                    "OpenDataLoader output exceeds configured byte limit"
                )

            # 6. Attach public media URLs to image blocks
            for block in content_list:
                if block.get("type") == "image" and block.get("img_path"):
                    attach_public_media_urls(block)

            # 7. Return PageTrackedContent
            from raganything.parser.office_parser import PageTrackedContent

            result = PageTrackedContent(
                content_list,
                coverage,
                provenance_ref={
                    "schema": "odl-provenance-ref-v1",
                    "relative_path": sidecar_path.relative_to(
                        base_dir.resolve()
                    ).as_posix(),
                    "sha256": self._sha256(sidecar_path),
                    "normalized_content_sha256": normalized_identity,
                    "adapter_schema": _ADAPTER_SCHEMA_VERSION,
                },
            )
            self._log_parse_outcome(
                "success",
                operation_start,
                page_count=source_pages,
                block_count=len(content_list),
                success=True,
            )
            return result

        except (
            ODLPreflightError,
            ODLConversionError,
            ODLValidationError,
            ODLPageCoverageError,
            ODLContainerError,
        ):
            self._log_parse_outcome(
                getattr(sys.exc_info()[1], "failure_code", "odl_error"),
                operation_start,
                page_count=source_pages,
            )
            raise
        except FileNotFoundError:
            self._log_parse_outcome("odl_validation", operation_start)
            raise
        except Exception as exc:
            self.logger.error(
                "Unexpected error in OpenDataLoader parse_pdf: type=%s",
                type(exc).__name__,
            )
            self._log_parse_outcome("odl_conversion", operation_start)
            raise ODLConversionError("Unexpected parser error") from exc
        finally:
            if cross_process_lock is not None:
                cross_process_lock.release()
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
                "OpenDataLoader is PDF-only; use the global parser for non-PDF documents."
            )
        raise ODLValidationError("OpenDataLoader only supports PDF inputs")


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

        m = re.match(r"^(\d+(?:\.\d+)*)\s", stripped)
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
        raise ODLValidationError("Expected a 4-element bounding box")
    try:
        bbox = [float(value) for value in raw_bbox]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ODLValidationError(
            "Bounding box coordinates must be finite numeric values"
        ) from exc
    if not all(math.isfinite(value) for value in bbox):
        raise ODLValidationError(
            "Bounding box coordinates must be finite numeric values"
        )
    return bbox


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
        rows.append(
            [
                str(c.get("content", "")) if isinstance(c, dict) else str(c)
                for c in row_cells
            ]
        )

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
        resolved = OpenDataLoaderParser._resolve_media_path(str(table_img), output_root)
        if resolved:
            block["img_path"] = str(resolved)
            attach_public_media_urls(block)
        else:
            block["_odl_media_rejected"] = "missing_or_outside_output_root"

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
    # OpenDataLoader 2.5.0 writes exported figure paths in ``source``.
    # Keep all candidate paths behind the same containment check below.
    image_ref = (
        el.get("image")
        or el.get("img_path")
        or el.get("src")
        or el.get("source")
        or ""
    )
    if not image_ref:
        # Check for embedded Base64 data URI
        content = el.get("content") or ""
        if content and content.startswith("data:image/"):
            # Base64 embedded — we cannot use it directly on disk
            return {
                "type": "text",
                "text": f"[Embedded Image: {el.get('alt', '') or el.get('caption', '') or 'unnamed'}]",
                "page_idx": page_idx,
            }
        return None

    resolved = OpenDataLoaderParser._resolve_media_path(str(image_ref), output_root)
    if resolved is None:
        # Path escape or missing — safe text fallback
        return {
            "type": "text",
            "text": f"[Image: {el.get('alt', '') or el.get('caption', '') or Path(image_ref).name}]",
            "page_idx": page_idx,
        }

    block: Dict[str, Any] = {
        "type": "image",
        "img_path": str(resolved),
        "page_idx": page_idx,
    }
    caption = el.get("caption") or el.get("alt") or ""
    try:
        block["_odl_media"] = build_media_entry(
            path=resolved,
            output_root=output_root,
            page=page_idx + 1,
            element_id=str(el.get("id") or el.get("element_id") or f"image-{page_idx}"),
            caption=str(caption),
        )
        block["_odl_media_output_root"] = str(output_root)
    except (OSError, RuntimeError, ValueError):
        return {
            "type": "text",
            "text": f"[Image: {caption or Path(image_ref).name}]",
            "page_idx": page_idx,
        }
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
