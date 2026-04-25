from __future__ import annotations

import json
from pathlib import Path

from fastapi import UploadFile

from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.document_store import DocumentStore
from raganything_studio.backend.core.job_manager import JobManager
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.schemas.document import DocumentStatus
from raganything_studio.backend.schemas.job import JobStage, JobStatus
from raganything_studio.backend.schemas.job import ProcessOptions
from raganything_studio.backend.schemas.settings import StudioSettingsUpdate
from raganything_studio.backend.services.content_list_service import ContentListService
from raganything_studio.backend.services.raganything_service import _config_updates


def make_settings(tmp_path: Path) -> StudioSettings:
    return StudioSettings(
        data_dir=tmp_path,
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "output",
        working_dir=tmp_path / "rag_storage",
        static_dir=tmp_path / "static",
        settings_file=tmp_path / "settings.json",
        llm_provider="openai-compatible",
        llm_model="gpt-4o-mini",
        llm_base_url=None,
        llm_api_key=None,
        embedding_provider="openai-compatible",
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
        embedding_max_token_size=8192,
        embedding_base_url=None,
        embedding_api_key=None,
        vision_provider="openai-compatible",
        vision_model="gpt-4o",
        vision_base_url=None,
        vision_api_key=None,
        default_parser="mineru",
        default_parse_method="auto",
        default_language="ch",
        default_device="cpu",
    )


def test_document_store_saves_upload_with_safe_filename(tmp_path):
    settings = make_settings(tmp_path)
    store = DocumentStore(settings)
    source = tmp_path / "input.pdf"
    source.write_bytes(b"pdf")

    with source.open("rb") as file_obj:
        upload = UploadFile(file=file_obj, filename="../paper.pdf")
        document = store.save_upload(upload)

    assert document.filename == "paper.pdf"
    assert document.status == DocumentStatus.UPLOADED
    assert Path(document.original_path).read_bytes() == b"pdf"
    assert store.get_document(document.id).id == document.id


def test_document_store_recovers_upload_when_catalog_missing(tmp_path):
    settings = make_settings(tmp_path)
    upload_dir = settings.upload_dir / "doc_recovered"
    upload_dir.mkdir(parents=True)
    (upload_dir / "paper.pdf").write_bytes(b"pdf")
    output_dir = settings.output_dir / "doc_recovered" / "paper" / "auto"
    output_dir.mkdir(parents=True)
    (output_dir / "paper_content_list.json").write_text("[]", encoding="utf-8")

    store = DocumentStore(settings)
    document = store.get_document("doc_recovered")

    assert document.filename == "paper.pdf"
    assert document.status == DocumentStatus.INDEXED


def test_document_store_marks_existing_upload_indexed_from_lightrag_status(tmp_path):
    settings = make_settings(tmp_path)
    store = DocumentStore(settings)
    source = tmp_path / "input.pdf"
    source.write_bytes(b"pdf")

    with source.open("rb") as file_obj:
        document = store.save_upload(UploadFile(file=file_obj, filename="paper.pdf"))

    status_file = settings.working_dir / "kv_store_doc_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(
        json.dumps({
            document.id: {
                "status": "processed",
                "chunks_count": 12,
                "multimodal_processed": True,
            }
        }),
        encoding="utf-8",
    )

    [updated] = store.list_documents()

    assert updated.status == DocumentStatus.INDEXED
    assert updated.chunks_count == 12
    assert updated.status_detail == "Indexed in LightRAG (12 chunks)"


def test_job_manager_tracks_status_and_logs():
    manager = JobManager()
    job = manager.create_job(document_id="doc_1")

    manager.update_progress(job.id, JobStage.PARSING, 0.25, "Parsing document")
    manager.mark_succeeded(job.id)

    updated = manager.get_job(job.id)
    assert updated.status == JobStatus.SUCCEEDED
    assert updated.stage == JobStage.DONE
    assert updated.progress == 1.0
    assert any("Parsing document" in line for line in updated.logs)


def test_job_manager_persists_jobs(tmp_path):
    jobs_file = tmp_path / "jobs.json"
    manager = JobManager(jobs_file)
    job = manager.create_job(document_id="doc_1")
    manager.mark_failed(job.id, "boom")

    reloaded = JobManager(jobs_file)
    restored = reloaded.get_job(job.id)

    assert restored.status == JobStatus.FAILED
    assert restored.document_id == "doc_1"
    assert reloaded.latest_job_id_for_document("doc_1") == job.id


def test_content_list_service_reads_parser_output(tmp_path):
    settings = make_settings(tmp_path)
    store = DocumentStore(settings)
    source = tmp_path / "input.pdf"
    source.write_bytes(b"pdf")

    with source.open("rb") as file_obj:
        document = store.save_upload(UploadFile(file=file_obj, filename="paper.pdf"))

    output_dir = Path(document.output_dir)
    nested_dir = output_dir / "paper" / "auto"
    nested_dir.mkdir(parents=True)
    content_items = [{"type": "text", "text": "hello", "page_idx": 0}]
    (nested_dir / "paper_content_list.json").write_text(
        json.dumps(content_items),
        encoding="utf-8",
    )

    assert ContentListService().get_content_list(document) == content_items


def test_content_list_service_reads_docling_output(tmp_path):
    settings = make_settings(tmp_path)
    store = DocumentStore(settings)
    source = tmp_path / "input.pdf"
    source.write_bytes(b"pdf")

    with source.open("rb") as file_obj:
        document = store.save_upload(UploadFile(file=file_obj, filename="paper.pdf"))

    output_dir = Path(document.output_dir) / "paper" / "docling"
    output_dir.mkdir(parents=True)
    (output_dir / "paper.json").write_text(
        json.dumps({
            "texts": [
                {
                    "label": "section_header",
                    "text": "Hello",
                    "prov": [{"page_no": 2}],
                }
            ],
            "pictures": [{"label": "picture", "prov": [{"page_no": 3}]}],
        }),
        encoding="utf-8",
    )

    items = ContentListService().get_content_list(document)

    assert items[0]["type"] == "text"
    assert items[0]["text"] == "Hello"
    assert items[0]["page_idx"] == 1
    assert items[1]["type"] == "image"


def test_settings_store_persists_model_configuration(tmp_path):
    settings = make_settings(tmp_path)
    store = SettingsStore(settings)

    updated = store.update(
        StudioSettingsUpdate(
            llm_provider="openai-compatible",
            llm_model="gpt-4.1-mini",
            llm_base_url="https://api.example.com/v1",
            llm_api_key="secret",
            embedding_provider="openai-compatible",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_max_token_size=4096,
            embedding_base_url=None,
            embedding_api_key="embed-secret",
            vision_provider="openai-compatible",
            vision_model="gpt-4.1",
            vision_base_url=None,
            vision_api_key="vision-secret",
            default_parser="docling",
            default_parse_method="auto",
            default_language="en",
            default_device="cpu",
            default_enable_vlm_enhancement=True,
            max_concurrent_files=3,
        )
    )

    assert updated.llm_model == "gpt-4.1-mini"
    assert updated.llm_api_key == "secret"
    assert settings.settings_file.exists()

    reloaded = SettingsStore(make_settings(tmp_path)).get()
    assert reloaded.embedding_dim == 1536
    assert reloaded.default_parser == "docling"
    assert reloaded.default_enable_vlm_enhancement is True
    assert reloaded.max_concurrent_files == 3


def test_rag_config_disables_vlm_processing_by_default(tmp_path):
    settings = make_settings(tmp_path)

    updates = _config_updates(settings, ProcessOptions())

    assert updates["enable_image_processing"] is False
    assert updates["enable_table_processing"] is False
    assert updates["enable_equation_processing"] is False
    assert updates["max_concurrent_files"] == 1


def test_rag_config_enables_selected_vlm_processors(tmp_path):
    settings = make_settings(tmp_path)
    options = ProcessOptions(
        enable_vlm_enhancement=True,
        enable_image_processing=True,
        enable_table_processing=False,
        enable_equation_processing=True,
        max_concurrent_files=4,
    )

    updates = _config_updates(settings, options)

    assert updates["enable_image_processing"] is True
    assert updates["enable_table_processing"] is False
    assert updates["enable_equation_processing"] is True
    assert updates["max_concurrent_files"] == 4
