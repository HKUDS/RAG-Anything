from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi import UploadFile

from raganything.query import QueryMixin
from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.document_store import DocumentStore
from raganything_studio.backend.core.job_manager import JobManager
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.schemas.document import DocumentStatus
from raganything_studio.backend.schemas.job import JobStage, JobStatus
from raganything_studio.backend.schemas.job import ProcessOptions
from raganything_studio.backend.schemas.settings import StudioSettingsUpdate
from raganything_studio.backend.api.settings import (
    _merge_storage_env_for_test,
    _settings_response,
)
from raganything_studio.backend.services.content_list_service import ContentListService
from raganything_studio.backend.services.raganything_service import (
    _build_query_artifacts,
    _config_updates,
    _effective_options,
)


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
    manager.update_metrics(
        job.id,
        stage_durations={"parse": 1.25},
        api_call_counts={"embedding": 3},
        cache_hits={"parse": 1},
        cache_misses={"modal": 2},
    )
    manager.mark_succeeded(job.id)

    updated = manager.get_job(job.id)
    assert updated.status == JobStatus.SUCCEEDED
    assert updated.stage == JobStage.DONE
    assert updated.progress == 1.0
    assert any("Parsing document" in line for line in updated.logs)
    assert updated.stage_durations["parse"] == 1.25
    assert updated.api_call_counts["embedding"] == 3
    assert updated.cache_hits["parse"] == 1
    assert updated.cache_misses["modal"] == 2


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
            default_processing_preset="deep",
            default_enable_parse_cache=False,
            default_enable_modal_cache=True,
            default_preview_mode=True,
            embedding_batch_size=24,
            llm_max_concurrency=2,
            vlm_max_concurrency=1,
            embedding_max_concurrency=5,
            retry_max_attempts=4,
            retry_base_delay=0.5,
            retry_max_delay=6.0,
            write_lock_enabled=False,
            kv_storage="JsonKVStorage",
            vector_storage="QdrantVectorDBStorage",
            graph_storage="NetworkXStorage",
            doc_status_storage="JsonDocStatusStorage",
            vector_db_storage_cls_kwargs={"cosine_better_than_threshold": 0.25},
            storage_env={"QDRANT_URL": "http://localhost:6333"},
        )
    )

    assert updated.llm_model == "gpt-4.1-mini"
    assert updated.llm_api_key == "secret"
    assert updated.vector_storage == "QdrantVectorDBStorage"
    assert updated.storage_env["QDRANT_URL"] == "http://localhost:6333"
    assert settings.settings_file.exists()

    reloaded = SettingsStore(make_settings(tmp_path)).get()
    assert reloaded.embedding_dim == 1536
    assert reloaded.default_parser == "docling"
    assert reloaded.default_enable_vlm_enhancement is True
    assert reloaded.max_concurrent_files == 3
    assert reloaded.default_processing_preset == "deep"
    assert reloaded.default_enable_parse_cache is False
    assert reloaded.default_preview_mode is True
    assert reloaded.embedding_batch_size == 24
    assert reloaded.embedding_max_concurrency == 5
    assert reloaded.retry_max_attempts == 4
    assert reloaded.write_lock_enabled is False
    assert reloaded.vector_storage == "QdrantVectorDBStorage"
    assert reloaded.vector_db_storage_cls_kwargs["cosine_better_than_threshold"] == 0.25
    assert reloaded.storage_env["QDRANT_URL"] == "http://localhost:6333"


def test_storage_env_secrets_are_redacted_and_preserved(tmp_path):
    settings = make_settings(tmp_path)
    store = SettingsStore(settings)

    updated = store.update(
        StudioSettingsUpdate(
            llm_provider="openai-compatible",
            llm_model="gpt-4.1-mini",
            llm_base_url=None,
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
            vision_api_key=None,
            default_parser="mineru",
            default_parse_method="auto",
            default_language="ch",
            default_device="cpu",
            kv_storage="JsonKVStorage",
            vector_storage="QdrantVectorDBStorage",
            graph_storage="NetworkXStorage",
            doc_status_storage="JsonDocStatusStorage",
            vector_db_storage_cls_kwargs={},
            storage_env={
                "QDRANT_URL": "http://localhost:6333",
                "QDRANT_API_KEY": "qdrant-secret",
            },
        )
    )

    response = _settings_response(updated)
    assert response.storage_env["QDRANT_URL"] == "http://localhost:6333"
    assert response.storage_env["QDRANT_API_KEY"] == ""
    assert response.storage_env_configured["QDRANT_API_KEY"] is True

    preserved = store.update(
        StudioSettingsUpdate(
            llm_provider="openai-compatible",
            llm_model="gpt-4.1-mini",
            llm_base_url=None,
            llm_api_key=None,
            embedding_provider="openai-compatible",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            embedding_max_token_size=4096,
            embedding_base_url=None,
            embedding_api_key=None,
            vision_provider="openai-compatible",
            vision_model="gpt-4.1",
            vision_base_url=None,
            vision_api_key=None,
            default_parser="mineru",
            default_parse_method="auto",
            default_language="ch",
            default_device="cpu",
            kv_storage="JsonKVStorage",
            vector_storage="QdrantVectorDBStorage",
            graph_storage="NetworkXStorage",
            doc_status_storage="JsonDocStatusStorage",
            vector_db_storage_cls_kwargs={},
            storage_env={
                "QDRANT_URL": "http://localhost:6334",
                "QDRANT_API_KEY": "",
            },
        )
    )

    assert preserved.storage_env["QDRANT_URL"] == "http://localhost:6334"
    assert preserved.storage_env["QDRANT_API_KEY"] == "qdrant-secret"


def test_storage_connection_test_payload_reuses_saved_secret():
    merged = _merge_storage_env_for_test(
        {"QDRANT_API_KEY": "saved-secret"},
        {"QDRANT_URL": "http://localhost:6333", "QDRANT_API_KEY": ""},
    )

    assert merged["QDRANT_URL"] == "http://localhost:6333"
    assert merged["QDRANT_API_KEY"] == "saved-secret"


def test_settings_store_rejects_unsupported_storage_combination(tmp_path):
    settings = make_settings(tmp_path)
    store = SettingsStore(settings)

    with pytest.raises(HTTPException) as exc_info:
        store.update(
            StudioSettingsUpdate(
                llm_provider="openai-compatible",
                llm_model="gpt-4.1-mini",
                llm_base_url=None,
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
                vision_api_key=None,
                default_parser="mineru",
                default_parse_method="auto",
                default_language="ch",
                default_device="cpu",
                kv_storage="PGKVStorage",
                vector_storage="QdrantVectorDBStorage",
                graph_storage="NetworkXStorage",
                doc_status_storage="JsonDocStatusStorage",
                vector_db_storage_cls_kwargs={},
                storage_env={"QDRANT_URL": "http://localhost:6333"},
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "UNSUPPORTED_STORAGE_COMBINATION"


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


def test_processing_preset_does_not_override_explicit_manual_toggles(tmp_path):
    settings = make_settings(tmp_path)

    options = _effective_options(
        settings,
        ProcessOptions(processing_preset="deep", enable_modal_cache=False),
    )

    assert options.enable_vlm_enhancement is True
    assert options.enable_modal_cache is False


def test_text_query_initializes_lightrag_before_querying():
    class Logger:
        def info(self, *_):
            pass

        def warning(self, *_):
            pass

    class LightRAGStub:
        def __init__(self):
            self.calls = []

        async def aquery(self, query, param, system_prompt=None):
            self.calls.append((query, param.mode, system_prompt))
            return "answer"

    class RAGStub(QueryMixin):
        def __init__(self):
            self.lightrag = None
            self.logger = Logger()
            self.initialized = 0

        async def _ensure_lightrag_initialized(self):
            self.initialized += 1
            self.lightrag = LightRAGStub()
            return {"success": True}

    async def run_query():
        rag = RAGStub()
        result = await rag.aquery("What is indexed?", mode="global")
        return rag, result

    rag, result = asyncio.run(run_query())

    assert result == "answer"
    assert rag.initialized == 1
    assert rag.lightrag.calls == [("What is indexed?", "global", None)]


def test_query_artifacts_extract_multimodal_evidence(tmp_path):
    settings = make_settings(tmp_path)
    image_path = settings.output_dir / "doc_1" / "page.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    retrieval_data = {
        "status": "success",
        "data": {
            "chunks": [
                {
                    "chunk_id": "chunk_1",
                    "file_path": str(settings.output_dir / "doc_1" / "paper.pdf"),
                    "content": f"Image Path: {image_path}\nA transistor diagram.",
                }
            ],
            "entities": [
                {
                    "entity_name": "TRANSISTOR",
                    "description": "A semiconductor device.",
                    "source_id": "chunk_1",
                }
            ],
            "relationships": [
                {
                    "src_id": "TRANSISTOR",
                    "tgt_id": "BJT",
                    "description": "BJT is a transistor type.",
                    "source_id": "chunk_1",
                }
            ],
        },
    }

    artifacts = _build_query_artifacts(
        answer="BJT and FET are two transistor types.",
        retrieval_data=retrieval_data,
        settings=settings,
    )

    assert artifacts.sources[0].type == "image"
    assert artifacts.media[0].url is not None
    assert artifacts.relation_trace[0].label == "TRANSISTOR"
    assert artifacts.trace["retrieved_images"][0]["title"] == "page.png"


def test_query_artifacts_downgrade_uncertain_equations(tmp_path):
    settings = make_settings(tmp_path)
    retrieval_data = {
        "status": "success",
        "data": {
            "chunks": [
                {
                    "chunk_id": "chunk_eq",
                    "file_path": str(settings.output_dir / "doc_1" / "paper.pdf"),
                    "content": (
                        "Mathematical Equation Analysis: Equation: I_B I_C = \ufffd \ufffd "
                        "Format: unknown Mathematical Analysis: The equation appears "
                        "to be a typo or transcription error."
                    ),
                }
            ],
            "entities": [],
            "relationships": [],
        },
    }

    artifacts = _build_query_artifacts(
        answer="The equation transcription is unreliable.",
        retrieval_data=retrieval_data,
        settings=settings,
    )
    equation = artifacts.sources[0].raw["equation"]

    assert artifacts.sources[0].type == "equation"
    assert equation["formula"] == ""
    assert equation["format"] is None
    assert equation["uncertain"] is True
    assert "\ufffd" not in artifacts.sources[0].preview
