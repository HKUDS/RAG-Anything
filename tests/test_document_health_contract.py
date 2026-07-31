from datetime import date

import pytest

from raganything.routers.knowledge import (
    _apply_enrichment_status_overlay,
    _document_health_contract,
    _document_tag_health_contract,
)


def test_partial_graph_failure_is_exposed_as_degraded_without_rewriting_raw_status():
    result = _document_health_contract({
        "status": "failed",
        "chunks_count": 44,
        "error_msg": "worker timeout",
        "metadata": {
            "content_ready": True,
            "graph_status": "pending",
            "failure_stage": "entity_extraction",
            "retryable": True,
            "last_error": "LLM timeout",
        },
    })

    assert result == {
        "status": "degraded",
        "raw_status": "failed",
        "health": "degraded",
        "content_ready": True,
        "graph_status": "pending",
        "failure_stage": "entity_extraction",
        "retryable": True,
        "error_message": "LLM timeout",
    }


def test_zero_chunk_failure_remains_a_hard_failure():
    result = _document_health_contract({
        "status": "failed",
        "chunks_count": 0,
        "error_msg": "parse failed",
        "metadata": {"content_ready": True, "graph_status": "failed"},
    })

    assert result["status"] == "failed"
    assert result["raw_status"] == "failed"
    assert result["health"] == "failed"
    assert result["content_ready"] is True
    assert result["error_message"] == "parse failed"


def test_processed_document_is_healthy_and_not_retryable():
    result = _document_health_contract({"status": "processed", "chunks_count": 4})

    assert result["status"] == "processed"
    assert result["raw_status"] == "processed"
    assert result["health"] == "healthy"
    assert result["retryable"] is False


def test_processed_raw_status_with_pending_multimodal_work_is_not_healthy():
    result = _document_health_contract({
        "status": "processed",
        "chunks_count": 4,
        "metadata": {"multimodal_processed": False},
    })

    assert result["status"] == "handling"
    assert result["raw_status"] == "processed"
    assert result["health"] == "processing"


def test_pending_or_failed_tags_override_public_completion():
    pending = _apply_enrichment_status_overlay({
        "status": "processed", "health": "healthy", "tag_status": "running",
    })
    failed = _apply_enrichment_status_overlay({
        "status": "processed", "health": "healthy", "tag_status": "failed",
        "tag_error_message": "tagger failed",
    })

    assert pending["status"] == "handling"
    assert pending["health"] == "processing"
    assert failed["status"] == "degraded"
    assert failed["health"] == "degraded"
    assert failed["error_message"] == "tagger failed"


@pytest.mark.asyncio
async def test_tag_health_query_failure_does_not_rewrite_completed_document(monkeypatch):
    from raganything.services import document_tagging

    async def unavailable(*_args, **_kwargs):
        raise ConnectionError("tag database unavailable")

    monkeypatch.setattr(document_tagging, "get_document_tag_health", unavailable)

    health = (await _document_tag_health_contract("demo", ["doc-1"]))["doc-1"]
    result = _apply_enrichment_status_overlay({
        "status": "processed", "health": "healthy", **health,
    })

    assert health["tag_status"] == "unavailable"
    assert result["status"] == "processed"
    assert result["health"] == "healthy"


@pytest.mark.asyncio
async def test_document_list_uses_summary_status_without_full_hydration(monkeypatch):
    from raganything.routers import knowledge

    async def cleanup():
        return None

    async def summaries(_kb):
        return {
            "doc-1": {
                "file_path": "manual.pdf",
                "status": "processed",
                "chunks_count": 20,
                "content_length": 500,
                "metadata": {},
                "created_at": "2026-07-22T00:00:00+00:00",
                "updated_at": "2026-07-22T00:00:00+00:00",
            }
        }

    async def full_status(_kb):
        raise AssertionError("document list must not hydrate chunks_list")

    async def tag_health(_kb, _doc_ids):
        return {"doc-1": {"tag_status": "unmanaged", "tag_raw_status": "missing"}}

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", cleanup)
    monkeypatch.setattr(knowledge, "_load_doc_status_summaries", summaries)
    monkeypatch.setattr(knowledge, "_load_doc_status_json", full_status)
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", tag_health)
    monkeypatch.setattr(knowledge, "processing_tasks", {})

    result = await knowledge.list_documents(kb="demo", current_user={"id": 7})

    assert result["documents"][0]["full_id"] == "doc-1"
    assert result["documents"][0]["status"] == "processed"
    assert result["documents"][0]["chunks"] == 20


@pytest.mark.asyncio
async def test_document_list_exposes_durable_upload_task_ids_without_filename_matching(monkeypatch):
    from raganything.routers import knowledge

    async def cleanup():
        return None

    async def summaries(_kb):
        return {
            "doc-track": {
                "file_path": "same-name.pdf",
                "status": "processing",
                "track_id": "task-owned-by-document",
                "task_id": "task-ignored-after-track-id",
                "metadata": {"task_id": "task-ignored-after-record-id"},
            },
            "doc-task": {
                "file_path": "task.pdf",
                "status": "queued",
                "task_id": "task-from-record",
            },
            "doc-metadata": {
                "file_path": "metadata.pdf",
                "status": "retry_wait",
                "metadata": {"task_id": "task-from-metadata"},
            },
        }

    async def uploads(**_kwargs):
        return ([
            {"task_id": "task-owned-by-document", "status": "processing"},
            {"task_id": "task-from-record", "status": "queued"},
            {"task_id": "task-from-metadata", "status": "retry_wait"},
            {"task_id": "runtime-task", "status": "processing"},
        ], 4)

    async def active_tasks():
        return [{
            "id": "other-task-with-same-name",
            "kb": "demo",
            "file": "same-name.pdf",
            "status": "processing",
        }, {
            "id": "runtime-task",
            "kb": "demo",
            "file": "runtime.pdf",
            "status": "processing",
        }]

    async def tag_health(_kb, doc_ids):
        return {
            doc_id: {"tag_status": "unmanaged", "tag_raw_status": "missing"}
            for doc_id in doc_ids
        }

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", cleanup)
    monkeypatch.setattr(knowledge, "_load_doc_status_summaries", summaries)
    monkeypatch.setattr(knowledge, "pg_list_uploads", uploads)
    monkeypatch.setattr(knowledge, "get_all_tasks", active_tasks)
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", tag_health)
    monkeypatch.setattr(knowledge, "processing_tasks", {
        "other-task-with-same-name": {
            "kb": "demo", "file": "same-name.pdf", "status": "processing",
        },
        "runtime-task": {
            "kb": "demo", "file": "runtime.pdf", "status": "processing",
        },
    })

    result = await knowledge.list_documents(kb="demo", current_user={"id": 7})
    documents_by_file = {doc["file"]: doc for doc in result["documents"]}

    assert documents_by_file["same-name.pdf"]["upload_task_id"] == "task-owned-by-document"
    assert documents_by_file["same-name.pdf"]["can_cancel_upload"] is True
    assert documents_by_file["task.pdf"]["upload_task_id"] == "task-from-record"
    assert documents_by_file["metadata.pdf"]["upload_task_id"] == "task-from-metadata"
    assert documents_by_file["runtime.pdf"]["upload_task_id"] == "runtime-task"


@pytest.mark.asyncio
async def test_document_list_normalizes_date_timestamps_before_deduping(monkeypatch):
    from raganything.routers import knowledge

    async def cleanup():
        return None

    async def summaries(_kb):
        return {
            "doc-old": {
                "file_path": "manual.pdf",
                "status": "processed",
                "updated_at": date(2026, 7, 29),
            },
            "doc-new": {
                "file_path": "manual.pdf",
                "status": "processed",
                "updated_at": "2026-07-30T08:00:00+00:00",
            },
        }

    async def tag_health(_kb, doc_ids):
        return {doc_id: {"tag_status": "unmanaged", "tag_raw_status": "missing"} for doc_id in doc_ids}

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", cleanup)
    monkeypatch.setattr(knowledge, "_load_doc_status_summaries", summaries)
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", tag_health)
    monkeypatch.setattr(knowledge, "processing_tasks", {})

    result = await knowledge.list_documents(kb="demo", current_user={"id": 7})

    assert result["total"] == 1
    assert result["documents"][0]["full_id"] == "doc-new"
    assert result["documents"][0]["updated"] == "2026-07-30T08:00:00+00:00"


@pytest.mark.asyncio
async def test_document_list_does_not_merge_rows_with_missing_file_paths(monkeypatch):
    from raganything.routers import knowledge

    async def cleanup():
        return None

    async def summaries(_kb):
        return {
            "doc-a": {"file_path": "", "status": "processed", "chunks_count": 2},
            "doc-b": {"file_path": None, "status": "processed", "chunks_count": 3},
        }

    async def tag_health(_kb, doc_ids):
        return {
            doc_id: {"tag_status": "unmanaged", "tag_raw_status": "missing"}
            for doc_id in doc_ids
        }

    monkeypatch.setattr(knowledge, "cleanup_completed_tasks", cleanup)
    monkeypatch.setattr(knowledge, "_load_doc_status_summaries", summaries)
    monkeypatch.setattr(knowledge, "_document_tag_health_contract", tag_health)
    monkeypatch.setattr(knowledge, "processing_tasks", {})

    result = await knowledge.list_documents(kb="demo", current_user={"id": 7})

    assert result["total"] == 2
    assert {doc["full_id"] for doc in result["documents"]} == {"doc-a", "doc-b"}
