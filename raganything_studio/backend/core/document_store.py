from __future__ import annotations

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
    """In-memory document catalog with filesystem-backed uploads."""

    def __init__(self, settings: StudioSettings):
        self._settings = settings
        self._documents: dict[str, DocumentRecord] = {}
        self._lock = RLock()

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
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
            return updated


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _copy_model(document: DocumentRecord, update: dict) -> DocumentRecord:
    if hasattr(document, "model_copy"):
        return document.model_copy(update=update)
    return document.copy(update=update)
