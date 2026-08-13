from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import UploadFile, status

from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.document import (
    DocumentRecord,
    DocumentStatus,
)


class DocumentStore:
    """Document catalog persisted to {data_dir}/documents.json."""

    def __init__(self, settings: StudioSettings):
        self._settings = settings
        self._db_path = Path(settings.data_dir) / "documents.json"
        self._documents: dict[str, DocumentRecord] = {}
        self._lock = RLock()
        self._load()

    # ── public API ────────────────────────────────────────────────

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            if self._reconcile_existing_documents():
                self._save()
            return sorted(
                self._documents.values(),
                key=lambda document: document.created_at,
                reverse=True,
            )

    def get_document(self, document_id: str) -> DocumentRecord:
        with self._lock:
            document = self._documents.get(document_id)
            if document is None:
                raise api_error(
                    "DOCUMENT_NOT_FOUND",
                    f"Document {document_id} was not found",
                    status.HTTP_404_NOT_FOUND,
                )
            return document

    def save_upload(self, upload_file: UploadFile) -> DocumentRecord:
        if not upload_file.filename:
            raise api_error("UPLOAD_FAILED", "Upload filename is empty")

        document_id = f"doc_{uuid4().hex}"
        safe_name = Path(upload_file.filename).name
        document_dir = self._settings.upload_dir / document_id
        document_dir.mkdir(parents=True, exist_ok=True)
        destination = document_dir / safe_name

        try:
            with destination.open("wb") as output:
                shutil.copyfileobj(upload_file.file, output)
        except Exception as exc:
            raise api_error("UPLOAD_FAILED", f"Failed to save upload: {exc}") from exc

        now = _utc_now()
        output_dir = self._settings.output_dir / document_id
        working_dir = self._settings.working_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        working_dir.mkdir(parents=True, exist_ok=True)

        document = DocumentRecord(
            id=document_id,
            filename=safe_name,
            original_path=str(destination),
            working_dir=str(working_dir),
            output_dir=str(output_dir),
            status=DocumentStatus.UPLOADED,
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._documents[document_id] = document
            self._save()

        return document

    def set_status(
        self,
        document_id: str,
        status_value: DocumentStatus,
        error: str | None = None,
    ) -> DocumentRecord:
        with self._lock:
            document = self.get_document(document_id)
            updated = _copy_model(
                document,
                update={
                    "status": status_value,
                    "error": error,
                    "updated_at": _utc_now(),
                }
            )
            self._documents[document_id] = updated
            self._save()
            return updated

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        changed = False
        if not self._db_path.exists():
            changed = True
        else:
            try:
                raw: list[dict] = json.loads(self._db_path.read_text(encoding="utf-8"))
                for item in raw:
                    doc = (
                        DocumentRecord.model_validate(item)
                        if hasattr(DocumentRecord, "model_validate")
                        else DocumentRecord.parse_obj(item)
                    )
                    # Documents stuck in PROCESSING at shutdown can never finish.
                    if doc.status == DocumentStatus.PROCESSING:
                        doc = _copy_model(
                            doc,
                            {
                                "status": DocumentStatus.FAILED,
                                "error": "Interrupted by server restart",
                                "updated_at": _utc_now(),
                            },
                        )
                        changed = True
                    self._documents[doc.id] = doc
            except Exception:
                self._documents = {}
                changed = True

        if self._recover_missing_documents():
            changed = True
        if self._reconcile_existing_documents():
            changed = True
        if changed:
            self._save()

    def _reconcile_existing_documents(self) -> bool:
        changed = False
        doc_statuses = _read_doc_statuses(self._settings.working_dir)

        for document_id, document in list(self._documents.items()):
            output_dir = Path(document.output_dir)
            rag_status = doc_statuses.get(document_id, {})
            result_available = _has_result_artifact(output_dir)
            chunks_count = _safe_int(rag_status.get("chunks_count"))
            content_items_count = _count_content_items(output_dir)
            next_status = document.status
            status_detail = _status_detail(document, rag_status, result_available)

            if _is_processed_doc_status(rag_status):
                next_status = DocumentStatus.INDEXED
                result_available = True
            elif document.status == DocumentStatus.UPLOADED and _has_content_list(output_dir):
                next_status = DocumentStatus.INDEXED
            elif document.status == DocumentStatus.INDEXED and not result_available:
                status_detail = "Indexed in LightRAG; parser preview not found"

            updated = _copy_model(
                document,
                {
                    "status": next_status,
                    "status_detail": status_detail,
                    "result_available": result_available,
                    "content_items_count": content_items_count,
                    "chunks_count": chunks_count,
                },
            )
            if updated != document:
                self._documents[document_id] = updated
                changed = True

        return changed

    def _recover_missing_documents(self) -> bool:
        changed = False
        seen_ids = set(self._documents)

        for upload_dir in sorted(self._settings.upload_dir.glob("doc_*")):
            if not upload_dir.is_dir() or upload_dir.name in seen_ids:
                continue
            document = self._document_from_upload_dir(upload_dir)
            if document is None:
                continue
            self._documents[document.id] = document
            seen_ids.add(document.id)
            changed = True

        for output_dir in sorted(self._settings.output_dir.glob("doc_*")):
            if not output_dir.is_dir() or output_dir.name in seen_ids:
                continue
            if not _has_content_list(output_dir):
                continue
            document = self._document_from_output_dir(output_dir)
            self._documents[document.id] = document
            seen_ids.add(document.id)
            changed = True

        return changed

    def _document_from_upload_dir(self, upload_dir: Path) -> DocumentRecord | None:
        files = sorted(path for path in upload_dir.iterdir() if path.is_file())
        if not files:
            return None

        original_path = files[0]
        output_dir = self._settings.output_dir / upload_dir.name
        created_at = _datetime_from_mtime(upload_dir)
        updated_at = _latest_mtime_datetime([upload_dir, original_path, output_dir])
        return DocumentRecord(
            id=upload_dir.name,
            filename=original_path.name,
            original_path=str(original_path),
            working_dir=str(self._settings.working_dir),
            output_dir=str(output_dir),
            status=DocumentStatus.UPLOADED,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _document_from_output_dir(self, output_dir: Path) -> DocumentRecord:
        created_at = _datetime_from_mtime(output_dir)
        return DocumentRecord(
            id=output_dir.name,
            filename=output_dir.name,
            original_path=str(output_dir),
            working_dir=str(self._settings.working_dir),
            output_dir=str(output_dir),
            status=DocumentStatus.INDEXED,
            created_at=created_at,
            updated_at=_latest_mtime_datetime([output_dir]),
        )

    def _save(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            doc.model_dump(mode="json") if hasattr(doc, "model_dump")
            else json.loads(doc.json())
            for doc in self._documents.values()
        ]
        tmp = self._db_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        tmp.replace(self._db_path)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime_from_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _latest_mtime_datetime(paths: list[Path]) -> datetime:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return _utc_now()
    return max(_datetime_from_mtime(path) for path in existing)


def _has_content_list(output_dir: Path) -> bool:
    return output_dir.exists() and any(output_dir.rglob("*_content_list.json"))


def _has_result_artifact(output_dir: Path) -> bool:
    if not output_dir.exists():
        return False
    patterns = ("*_content_list.json", "*.md", "*.json")
    return any(any(output_dir.rglob(pattern)) for pattern in patterns)


def _count_content_items(output_dir: Path) -> int | None:
    content_lists = sorted(output_dir.rglob("*_content_list.json"))
    if content_lists:
        try:
            payload = json.loads(content_lists[0].read_text(encoding="utf-8"))
        except Exception:
            return None
        return len(payload) if isinstance(payload, list) else None

    docling_jsons = [
        path for path in sorted(output_dir.rglob("*.json"))
        if not path.name.endswith("_content_list.json")
    ]
    if not docling_jsons:
        return None
    try:
        payload = json.loads(docling_jsons[0].read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return sum(
        len(payload.get(key) or [])
        for key in ("texts", "pictures", "tables")
        if isinstance(payload.get(key), list)
    )


def _read_doc_statuses(working_dir: Path) -> dict[str, dict]:
    path = working_dir / "kv_store_doc_status.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(doc_id): status
        for doc_id, status in payload.items()
        if isinstance(status, dict)
    }


def _is_processed_doc_status(status: dict) -> bool:
    chunks_count = _safe_int(status.get("chunks_count"))
    return (
        status.get("status") == "processed"
        or bool(status.get("text_processed"))
        or (chunks_count is not None and chunks_count > 0)
    )


def _safe_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _status_detail(
    document: DocumentRecord,
    rag_status: dict,
    result_available: bool,
) -> str:
    if document.status == DocumentStatus.PROCESSING:
        return "Processing job is running"
    if document.status == DocumentStatus.FAILED:
        return document.error or "Processing failed"
    if _is_processed_doc_status(rag_status):
        chunks = _safe_int(rag_status.get("chunks_count"))
        return f"Indexed in LightRAG ({chunks} chunks)" if chunks is not None else "Indexed in LightRAG"
    if result_available:
        return "Parser output found; index status not confirmed"
    return "Uploaded; no processing result yet"


def _copy_model(document: DocumentRecord, update: dict) -> DocumentRecord:
    if hasattr(document, "model_copy"):
        return document.model_copy(update=update)
    return document.copy(update=update)
