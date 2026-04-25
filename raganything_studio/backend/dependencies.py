from __future__ import annotations

from raganything_studio.backend.config import get_settings
from raganything_studio.backend.core.document_store import DocumentStore
from raganything_studio.backend.core.job_manager import JobManager
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.services.content_list_service import ContentListService
from raganything_studio.backend.services.raganything_service import RAGAnythingService

settings = get_settings()
settings_store = SettingsStore(settings)
document_store = DocumentStore(settings)
job_manager = JobManager(settings.data_dir / "jobs.json")
rag_service = RAGAnythingService(settings)
content_list_service = ContentListService()


def get_document_store() -> DocumentStore:
    return document_store


def get_job_manager() -> JobManager:
    return job_manager


def get_rag_service() -> RAGAnythingService:
    return rag_service


def get_content_list_service() -> ContentListService:
    return content_list_service


def get_settings_store() -> SettingsStore:
    return settings_store
