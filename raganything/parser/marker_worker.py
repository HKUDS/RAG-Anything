"""Internal Marker parser service for the Pillow-isolated Docker runtime.

The application and this worker exchange only paths inside explicitly shared
Docker volumes.  The worker never accepts file bytes or arbitrary host paths.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


LOG = logging.getLogger("raganything.marker_worker")
_CONVERTER_LOCK = threading.Lock()
_CONVERTER: Any = None


def _roots_from_env(name: str, default: str) -> tuple[Path, ...]:
    values = os.environ.get(name, default).split(",")
    roots = tuple(Path(value.strip()).resolve() for value in values if value.strip())
    if not roots:
        raise RuntimeError(f"{name} must contain at least one directory")
    return roots


INPUT_ROOTS = _roots_from_env(
    "MARKER_INPUT_ROOTS", "/app/uploads,/app/rag_storage,/app/output"
)
OUTPUT_ROOT = Path(os.environ.get("MARKER_OUTPUT_ROOT", "/app/output")).resolve()
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".html", ".htm", ".xhtml"}
IMAGE_EXTENSIONS = {".png", ".jpeg", ".jpg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}


class MarkerWorkerError(RuntimeError):
    """Expected request or conversion failure exposed as a 4xx/5xx response."""


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _resolve_input(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise MarkerWorkerError("input_path is required")
    path = Path(value).resolve()
    if not _is_within(path, INPUT_ROOTS):
        raise MarkerWorkerError("input_path is outside the shared input volumes")
    if not path.is_file():
        raise MarkerWorkerError("input_path does not exist or is not a file")
    return path


def _resolve_output(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise MarkerWorkerError("output_dir is required")
    path = Path(value).resolve()
    if not path.is_relative_to(OUTPUT_ROOT):
        raise MarkerWorkerError("output_dir is outside the shared output volume")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _converter() -> Any:
    global _CONVERTER
    if _CONVERTER is None:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        LOG.info("loading Marker models")
        _CONVERTER = PdfConverter(
            artifact_dict=create_model_dict(),
            config={"output_format": "markdown"},
        )
    return _CONVERTER


def _convert_office_to_pdf(source: Path, output_dir: Path) -> Path:
    staging_dir = output_dir / ".marker-office"
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(staging_dir),
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("MARKER_OFFICE_TIMEOUT_SECONDS", "300")),
        )
    except FileNotFoundError as exc:
        raise MarkerWorkerError("LibreOffice is not available in the Marker runtime") from exc
    except subprocess.TimeoutExpired as exc:
        raise MarkerWorkerError("LibreOffice conversion timed out") from exc
    if completed.returncode:
        raise MarkerWorkerError("LibreOffice conversion failed")
    result = staging_dir / f"{source.stem}.pdf"
    if not result.is_file() or result.stat().st_size == 0:
        raise MarkerWorkerError("LibreOffice conversion produced no PDF")
    return result


def parse_request(payload: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_input(payload.get("input_path"))
    output_dir = _resolve_output(payload.get("output_dir"))
    suffix = source.suffix.lower()
    if suffix not in {".pdf", *IMAGE_EXTENSIONS, *OFFICE_EXTENSIONS}:
        raise MarkerWorkerError(f"unsupported Marker input type: {suffix or 'none'}")

    parse_source = _convert_office_to_pdf(source, output_dir) if suffix in OFFICE_EXTENSIONS else source
    artifact_dir = output_dir / source.stem / "marker"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with _CONVERTER_LOCK:
        rendered = _converter()(str(parse_source))

    markdown = str(getattr(rendered, "markdown", "")).strip()
    markdown_path = artifact_dir / f"{source.stem}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    content_list = [{"type": "text", "text": markdown, "page_idx": 0}] if markdown else []
    result = {"content_list": content_list, "artifact_dir": str(artifact_dir)}
    (artifact_dir / "marker-service-result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    return result


class MarkerRequestHandler(BaseHTTPRequestHandler):
    server_version = "RAGAnythingMarker/1.0"

    def log_message(self, format: str, *args: object) -> None:
        LOG.info("%s - %s", self.client_address[0], format % args)

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            from marker.converters.pdf import PdfConverter  # noqa: F401
        except Exception:
            LOG.exception("Marker import failed during health check")
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "unavailable"})
            return
        self._json(HTTPStatus.OK, {"status": "ok", "parser": "marker"})

    def do_POST(self) -> None:
        if self.path != "/v1/parse":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 64 * 1024:
                raise MarkerWorkerError("invalid request body size")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise MarkerWorkerError("request body must be an object")
            self._json(HTTPStatus.OK, parse_request(payload))
        except MarkerWorkerError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            LOG.exception("Marker conversion failed")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Marker conversion failed"})


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    port = int(os.environ.get("MARKER_PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), MarkerRequestHandler)
    LOG.info("Marker worker listening on port %s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
