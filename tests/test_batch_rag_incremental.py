"""Parse reuse must not imply successful indexing in the current RAG workspace."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

import raganything.batch_parser as batch_parser
from raganything.base import DocStatus
from raganything.batch import BatchMixin
from raganything.parser import Parser
from raganything.processor import ProcessorMixin


class MemoryStorage:
    def __init__(self):
        self.entries = {}
        self.read_error = None
        self.writes = 0

    async def get_by_id(self, key):
        if self.read_error:
            raise self.read_error
        return self.entries.get(key)

    async def upsert(self, entries):
        self.writes += 1
        self.entries.update(entries)

    async def index_done_callback(self):
        pass


@pytest.fixture
def harness(monkeypatch, tmp_path):
    class TextParser(Parser):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.extra_blocks = []

        def parse_document(self, file_path, **kwargs):
            self.calls.append(kwargs)
            return self.parse_text_file(file_path) + self.extra_blocks

    doc_parser = TextParser()
    monkeypatch.setattr(batch_parser, "get_parser", lambda name: doc_parser)

    class Harness(ProcessorMixin, BatchMixin):
        def __init__(self):
            self.config = SimpleNamespace(
                parser="test",
                parser_output_dir=str(tmp_path / "out"),
                parse_method="auto",
                max_concurrent_files=1,
                recursive_folder_processing=True,
                display_content_stats=False,
                use_full_path=False,
            )
            self.logger = logging.getLogger(__name__)
            self.doc_parser = doc_parser
            self.parse_cache = MemoryStorage()
            self.lightrag = SimpleNamespace(
                doc_status=MemoryStorage(),
                full_docs=MemoryStorage(),
                ainsert=self._insert_text,
            )
            self.insert_calls = []
            self.multimodal_calls = []
            self.insert_error = None
            self.init_error = False
            self.events = []
            self.callback_manager = SimpleNamespace(
                dispatch=lambda event, **kwargs: self.events.append((event, kwargs))
            )

        async def _ensure_lightrag_initialized(self):
            return {"success": not self.init_error, "error": "init failure"}

        async def _insert_text(self, input, ids, **kwargs):
            # Only the external indexing backend is replaced. Public complete,
            # text waiting/status updates, and multimodal short-circuit are real.
            self.insert_calls.append((ids, kwargs))
            current = await self.lightrag.doc_status.get_by_id(ids) or {}
            await self.lightrag.full_docs.upsert({ids: {"content": input}})
            if self.insert_error:
                await self.lightrag.doc_status.upsert(
                    {ids: {**current, "status": DocStatus.FAILED}}
                )
                raise self.insert_error
            await self.lightrag.doc_status.upsert(
                {ids: {**current, "status": DocStatus.PROCESSED}}
            )

        async def _lightrag_pipeline_status(self):
            return {}

        async def _process_multimodal_content_batch_type_aware(self, **kwargs):
            self.multimodal_calls.append(kwargs)

        def run(self, paths=None, **kwargs):
            return asyncio.run(
                self.process_documents_with_rag_batch(
                    paths or [str(document)],
                    show_progress=False,
                    incremental=True,
                    **kwargs,
                )
            )

    document = tmp_path / "doc.txt"
    document.write_text("Knowledge that must reach RAG", encoding="utf-8")
    h = Harness()
    h.document = document
    return h


def test_failed_rag_insert_is_retried_without_reparsing(harness):
    h = harness
    h.insert_error = RuntimeError("temporary LLM failure")
    first = h.run()
    assert first["failed_rag_files"] == 1
    parser_calls = len(h.doc_parser.calls)
    h.insert_error = None
    second = h.run()
    assert second["parse_result"].successful_files == []
    assert second["parse_result"].skipped_files == [str(h.document)]
    assert second["successful_rag_files"] == 1
    assert len(h.insert_calls) == 2
    assert len(h.doc_parser.calls) == parser_calls  # real persisted parse cache


@pytest.mark.parametrize(
    "previous_run", ["parse_only", "other_workspace", "init_failure"]
)
def test_parse_manifest_does_not_skip_missing_workspace_document(harness, previous_run):
    h = harness
    if previous_run == "parse_only":
        h.process_documents_batch(
            [str(h.document)], incremental=True, show_progress=False
        )
    elif previous_run == "other_workspace":
        h.run()
        h.lightrag.doc_status = MemoryStorage()
        h.parse_cache = MemoryStorage()
        h.insert_calls.clear()
    else:
        h.init_error = True
        with pytest.raises(RuntimeError, match="init failure"):
            h.run()
        h.init_error = False
    result = h.run()
    assert result["parse_result"].skipped_files == [str(h.document)]
    assert result["successful_rag_files"] == 1
    assert len(h.insert_calls) == 1


@pytest.mark.parametrize(
    "status,multimodal",
    [
        ("failed", True),
        ("pending", False),
        ("processing", False),
        ("handling", False),
        ("processed", False),
    ],
)
def test_incomplete_workspace_status_is_retried(harness, status, multimodal):
    h = harness
    h.run()
    doc_id = next(iter(h.lightrag.doc_status.entries))
    h.lightrag.doc_status.entries[doc_id] = {
        "status": status,
        "multimodal_processed": multimodal,
    }
    assert h.run()["successful_rag_files"] == 1
    assert len(h.insert_calls) == 2


def test_fully_processed_document_is_not_reinserted_or_counted_as_failure(harness):
    h = harness
    h.run()
    before = dict(h.lightrag.doc_status.entries)
    writes = h.lightrag.doc_status.writes
    result = h.run(paths=[str(h.document.parent)])
    assert result["rag_results"][str(h.document)] == {
        "status": "skipped",
        "processed": False,
    }
    assert result["successful_rag_files"] == result["failed_rag_files"] == 0
    assert result["skipped_rag_files"] == 1
    assert len(h.insert_calls) == 1
    assert h.lightrag.doc_status.entries == before
    assert h.lightrag.doc_status.writes == writes
    event = h.events[-1]
    assert event[0] == "on_batch_complete"
    assert (
        event[1]["total_files"],
        event[1]["successful"],
        event[1]["failed"],
        event[1]["skipped"],
    ) == (1, 0, 0, 1)


@pytest.mark.parametrize("explicit_id", ["my-id", ""])
def test_explicit_document_id_and_ingestion_options_are_not_parser_options(
    harness, explicit_id
):
    h = harness
    options = dict(
        doc_id=explicit_id,
        file_name="reference.txt",
        split_by_character="|",
        split_by_character_only=True,
        display_stats=False,
        force_multimodal_reprocess=False,
        custom_option="accepted",
    )
    h.run(**options)
    assert set(h.lightrag.doc_status.entries) == {explicit_id}
    assert h.run(**options)["skipped_rag_files"] == 1
    assert len(h.insert_calls) == 1
    for call in h.doc_parser.calls:
        assert call["custom_option"] == "accepted"
        assert not (set(options) - {"custom_option"}) & set(call)


def test_force_multimodal_reprocess_bypasses_completed_status(harness):
    h = harness
    h.run(force_multimodal_reprocess=True)
    result = h.run(force_multimodal_reprocess=True)
    assert result["parse_result"].skipped_files == [str(h.document)]
    assert result["successful_rag_files"] == 1
    assert len(h.insert_calls) == 2


def test_status_read_failure_is_reported_without_attempting_insert(harness):
    h = harness
    h.run()
    h.lightrag.doc_status.read_error = RuntimeError("storage unavailable")
    result = h.run()
    assert result["failed_rag_files"] == 1
    assert "storage unavailable" in result["rag_results"][str(h.document)]["error"]
    assert len(h.insert_calls) == 1


def test_legacy_multimodal_completion_cache_is_used(harness):
    h = harness
    h.run()
    doc_id = next(iter(h.lightrag.doc_status.entries))
    del h.lightrag.doc_status.entries[doc_id]["multimodal_processed"]
    h.multimodal_status_cache = MemoryStorage()
    h.multimodal_status_cache.entries[doc_id] = {"multimodal_processed": True}
    assert h.run()["skipped_rag_files"] == 1
    assert len(h.insert_calls) == 1


def test_same_basename_files_keep_independent_rag_status(harness):
    h = harness
    other = h.document.parent / "subdir" / h.document.name
    other.parent.mkdir()
    other.write_text("Different knowledge", encoding="utf-8")
    paths = [str(h.document), str(other)]
    h.run(paths=paths)
    cache_key = h._generate_cache_key(other, "auto")
    other_doc_id = h.parse_cache.entries[cache_key]["doc_id"]
    h.lightrag.doc_status.entries[other_doc_id]["status"] = DocStatus.FAILED
    result = h.run(paths=paths)
    assert result["parse_result"].skipped_files == paths
    assert result["rag_results"][str(h.document)]["status"] == "skipped"
    assert result["rag_results"][str(other)]["status"] == "success"
    assert result["successful_rag_files"] == result["skipped_rag_files"] == 1
    assert result["failed_rag_files"] == 0
    assert len(h.insert_calls) == 3
    event = h.events[-1][1]
    assert (event["successful"], event["failed"], event["skipped"]) == (1, 0, 1)


@pytest.mark.parametrize(
    "status", [DocStatus.FAILED, DocStatus.PENDING, DocStatus.HANDLING]
)
@pytest.mark.parametrize("compatibility_cache", [False, True])
def test_real_complete_restores_retry_with_previously_completed_multimodal(
    harness,
    status,
    compatibility_cache,
):
    h = harness
    h.doc_parser.extra_blocks = [
        {"type": "image", "img_path": "previously-indexed.png", "page_idx": 0}
    ]
    h.run()
    doc_id = next(iter(h.lightrag.doc_status.entries))
    h.lightrag.doc_status.entries[doc_id]["status"] = status
    if compatibility_cache:
        del h.lightrag.doc_status.entries[doc_id]["multimodal_processed"]
        h.multimodal_status_cache = MemoryStorage()
        h.multimodal_status_cache.entries[doc_id] = {"multimodal_processed": True}
    h.multimodal_calls.clear()
    result = h.run()
    assert result["successful_rag_files"] == 1
    assert h.lightrag.doc_status.entries[doc_id]["status"] == DocStatus.PROCESSED
    assert len(h.insert_calls) == 2
    assert h.multimodal_calls == []  # Already paid work is not repeated.
    assert h.run()["skipped_rag_files"] == 1
    assert len(h.insert_calls) == 2


def test_retry_text_failure_keeps_completed_multimodal_and_failed_status(harness):
    h = harness
    h.doc_parser.extra_blocks = [
        {"type": "image", "img_path": "indexed.png", "page_idx": 0}
    ]
    h.run()
    doc_id = next(iter(h.lightrag.doc_status.entries))
    h.lightrag.doc_status.entries[doc_id]["status"] = DocStatus.FAILED
    h.multimodal_calls.clear()
    h.insert_error = RuntimeError("text retry failed")
    result = h.run()
    assert result["failed_rag_files"] == 1
    assert h.lightrag.doc_status.entries[doc_id]["status"] == DocStatus.FAILED
    assert h.lightrag.doc_status.entries[doc_id]["multimodal_processed"] is True
    assert h.multimodal_calls == []


def test_retry_completion_write_failure_is_not_reported_as_success(
    harness, monkeypatch
):
    h = harness
    h.doc_parser.extra_blocks = [
        {"type": "image", "img_path": "indexed.png", "page_idx": 0}
    ]
    h.run()
    doc_id = next(iter(h.lightrag.doc_status.entries))
    h.lightrag.doc_status.entries[doc_id]["status"] = DocStatus.FAILED
    h.multimodal_calls.clear()
    storage = h.lightrag.doc_status
    original_upsert = storage.upsert

    async def fail_completion_write(entries):
        if (
            storage.entries[doc_id]["status"] == DocStatus.HANDLING
            and entries[doc_id]["status"] == DocStatus.PROCESSED
        ):
            raise RuntimeError("completion write unavailable")
        await original_upsert(entries)

    monkeypatch.setattr(storage, "upsert", fail_completion_write)
    result = h.run()
    assert result["successful_rag_files"] == 0
    assert result["failed_rag_files"] == 1
    assert storage.entries[doc_id]["status"] == DocStatus.HANDLING
    assert h.multimodal_calls == []


def test_forced_retry_uses_real_multimodal_completion_without_extra_restore(
    harness, monkeypatch
):
    h = harness
    h.doc_parser.extra_blocks = [
        {"type": "image", "img_path": "indexed.png", "page_idx": 0}
    ]
    h.run(force_multimodal_reprocess=True)
    doc_id = next(iter(h.lightrag.doc_status.entries))
    h.lightrag.doc_status.entries[doc_id]["status"] = DocStatus.FAILED
    marks = []
    original_mark = h._mark_multimodal_processing_complete

    async def mark(doc_id):
        marks.append(doc_id)
        await original_mark(doc_id)

    monkeypatch.setattr(h, "_mark_multimodal_processing_complete", mark)
    result = h.run(force_multimodal_reprocess=True)
    assert result["successful_rag_files"] == 1
    assert len(h.multimodal_calls) == 2
    assert marks == [doc_id]
