"""Focused tests for fail-closed multimodal ingestion."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from raganything.modalprocessors import (
    EquationModalProcessor,
    GenericModalProcessor,
    ImageModalProcessor,
    TableModalProcessor,
)
from raganything.processor import ProcessorMixin


class RecordingLogger:
    """Minimal logger used by processor tests."""

    def debug(self, *args, **kwargs):
        del args, kwargs

    def error(self, *args, **kwargs):
        del args, kwargs

    def info(self, *args, **kwargs):
        del args, kwargs

    def warning(self, *args, **kwargs):
        del args, kwargs


class DescriptionFailure(Exception):
    """Sentinel description failure."""


class StageFailure(Exception):
    """Sentinel downstream stage failure."""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processor_class", "content_type"),
    [
        (ImageModalProcessor, "image"),
        (TableModalProcessor, "table"),
        (EquationModalProcessor, "equation"),
        (GenericModalProcessor, "chart"),
    ],
)
async def test_description_generation_reraises_without_fabricated_fallback(
    processor_class,
    content_type,
    tmp_path,
):
    expected = DescriptionFailure(content_type)

    async def fail_description(*args, **kwargs):
        del args, kwargs
        raise expected

    processor = processor_class.__new__(processor_class)
    processor.context_extractor = None
    processor.modal_caption_func = fail_description

    if content_type == "image":
        image_path = tmp_path / "image.png"
        image_path.write_bytes(b"not-a-real-image-but-readable")
        modal_content = {"img_path": str(image_path)}
    elif content_type == "table":
        modal_content = {"table_body": "| a | b |"}
    elif content_type == "equation":
        modal_content = {"text": "x + y = 1", "text_format": "latex"}
    else:
        modal_content = {"content": "chart data"}

    with pytest.raises(DescriptionFailure) as exc_info:
        await processor.generate_description_only(modal_content, content_type)

    assert exc_info.value is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processor_class", "content_type", "modal_content"),
    [
        (ImageModalProcessor, "image", {"img_path": "image.png"}),
        (TableModalProcessor, "table", {"table_body": "| a | b |"}),
        (
            EquationModalProcessor,
            "equation",
            {"text": "x + y = 1", "text_format": "latex"},
        ),
        (GenericModalProcessor, "chart", {"content": "chart data"}),
    ],
)
async def test_public_processor_reraises_description_failure(
    processor_class,
    content_type,
    modal_content,
):
    expected = DescriptionFailure(content_type)

    async def fail_description(*args, **kwargs):
        del args, kwargs
        raise expected

    processor = processor_class.__new__(processor_class)
    processor.generate_description_only = fail_description
    processor._create_entity_and_chunk = AsyncMock()

    with pytest.raises(DescriptionFailure) as exc_info:
        await processor.process_multimodal_content(modal_content, content_type)

    assert exc_info.value is expected
    processor._create_entity_and_chunk.assert_not_awaited()


class FakeDocStatus:
    """Status store with an initialized text-processing record."""

    async def get_by_id(self, doc_id):
        del doc_id
        return {
            "status": "processed",
            "chunks_count": 0,
            "chunks_list": [],
        }


class FakeDescriptionProcessor:
    """Description processor controlled by each input item."""

    async def generate_description_only(self, modal_content, **kwargs):
        del kwargs
        if modal_content.get("fail"):
            raise DescriptionFailure(str(modal_content["index"]))
        index = modal_content["index"]
        return f"description-{index}", {
            "entity_name": f"entity-{index}",
            "entity_type": "image",
            "summary": f"summary-{index}",
        }


class DummyProcessor(ProcessorMixin):
    """Processor with fake storage and deterministic stages."""

    def __init__(self):
        self.callback_manager = None
        self.config = SimpleNamespace(use_full_path=False)
        self.lightrag = SimpleNamespace(
            doc_status=FakeDocStatus(),
            max_parallel_insert=2,
        )
        self.logger = RecordingLogger()
        self.modal_processors = {"image": FakeDescriptionProcessor()}


def configure_pipeline(processor, *, failure_stage=None):
    """Install deterministic downstream stages on a dummy processor."""
    processor._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    processor._convert_to_lightrag_chunks_type_aware = Mock(
        return_value={"chunk-0": {}, "chunk-1": {}}
    )
    processor._store_chunks_to_lightrag_storage_type_aware = AsyncMock()
    processor._store_multimodal_main_entities = AsyncMock()
    processor._batch_extract_entities_lightrag_style_type_aware = AsyncMock(
        return_value=[({}, {}), ({}, {})]
    )
    processor._batch_add_belongs_to_relations_type_aware = AsyncMock(
        return_value=[({}, {}), ({}, {})]
    )
    processor._batch_merge_lightrag_style_type_aware = AsyncMock()
    processor._update_doc_status_with_chunks_type_aware = AsyncMock()
    processor._mark_multimodal_processing_complete = AsyncMock()
    processor._process_multimodal_content_individual = AsyncMock()

    stage_methods = {
        "storage": processor._store_chunks_to_lightrag_storage_type_aware,
        "merge": processor._batch_merge_lightrag_style_type_aware,
        "status": processor._update_doc_status_with_chunks_type_aware,
    }
    if failure_stage:
        stage_methods[failure_stage].side_effect = StageFailure(failure_stage)


def multimodal_items(*failure_flags):
    """Build input with selected description failures."""
    return [
        {"type": "image", "index": index, "fail": should_fail}
        for index, should_fail in enumerate(failure_flags)
    ]


@pytest.mark.asyncio
async def test_complete_n_of_n_batch_runs_every_stage_and_marks_complete():
    processor = DummyProcessor()
    configure_pipeline(processor)

    await processor._process_multimodal_content(
        multimodal_items(False, False), "source.pdf", "doc-1"
    )

    processor._store_chunks_to_lightrag_storage_type_aware.assert_awaited_once()
    processor._store_multimodal_main_entities.assert_awaited_once()
    processor._batch_extract_entities_lightrag_style_type_aware.assert_awaited_once()
    processor._batch_add_belongs_to_relations_type_aware.assert_awaited_once()
    processor._batch_merge_lightrag_style_type_aware.assert_awaited_once()
    processor._update_doc_status_with_chunks_type_aware.assert_awaited_once()
    processor._mark_multimodal_processing_complete.assert_awaited_once_with("doc-1")
    processor._process_multimodal_content_individual.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_flags", [(True, True), (False, True)])
async def test_incomplete_description_batch_stops_before_storage(failure_flags):
    processor = DummyProcessor()
    configure_pipeline(processor)

    with pytest.raises(RuntimeError, match=r"[01]/2 succeeded"):
        await processor._process_multimodal_content(
            multimodal_items(*failure_flags), "source.pdf", "doc-1"
        )

    processor._store_chunks_to_lightrag_storage_type_aware.assert_not_awaited()
    processor._batch_merge_lightrag_style_type_aware.assert_not_awaited()
    processor._update_doc_status_with_chunks_type_aware.assert_not_awaited()
    processor._mark_multimodal_processing_complete.assert_not_awaited()
    processor._process_multimodal_content_individual.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_initial_doc_status_stops_before_description_and_storage():
    class MissingDocStatus:
        async def get_by_id(self, doc_id):
            del doc_id
            return None

    processor = DummyProcessor()
    configure_pipeline(processor)
    processor.lightrag.doc_status = MissingDocStatus()
    generate_description = AsyncMock()
    processor.modal_processors = {
        "image": SimpleNamespace(generate_description_only=generate_description)
    }

    with pytest.raises(RuntimeError, match=r"doc_status record doc-1 not found"):
        await processor._process_multimodal_content_batch_type_aware(
            multimodal_items(False), "source.pdf", "doc-1"
        )

    generate_description.assert_not_awaited()
    processor._store_chunks_to_lightrag_storage_type_aware.assert_not_awaited()
    processor._batch_extract_entities_lightrag_style_type_aware.assert_not_awaited()
    processor._batch_merge_lightrag_style_type_aware.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_description_failure_cancels_queued_remote_calls():
    expected = DescriptionFailure("first")
    started_indexes = []

    class FirstFailureProcessor:
        async def generate_description_only(self, modal_content, **kwargs):
            del kwargs
            started_indexes.append(modal_content["index"])
            if modal_content["index"] == 0:
                raise expected
            await asyncio.Event().wait()

    processor = DummyProcessor()
    configure_pipeline(processor)
    processor.lightrag.max_parallel_insert = 1
    processor.modal_processors = {"image": FirstFailureProcessor()}

    with pytest.raises(RuntimeError, match=r"0/3 succeeded") as exc_info:
        await processor._process_multimodal_content_batch_type_aware(
            multimodal_items(True, False, False), "source.pdf", "doc-1"
        )

    assert exc_info.value.__cause__ is expected
    assert started_indexes == [0]
    processor._store_chunks_to_lightrag_storage_type_aware.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["storage", "merge", "status"])
async def test_downstream_failure_blocks_completion_and_individual_fallback(
    failure_stage,
):
    processor = DummyProcessor()
    configure_pipeline(processor, failure_stage=failure_stage)

    with pytest.raises(StageFailure, match=failure_stage):
        await processor._process_multimodal_content(
            multimodal_items(False, False), "source.pdf", "doc-1"
        )

    processor._mark_multimodal_processing_complete.assert_not_awaited()
    processor._process_multimodal_content_individual.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_status_backend_failure_propagates():
    expected = StageFailure("status backend")

    class FailingDocStatus:
        async def get_by_id(self, doc_id):
            del doc_id
            return {"status": "processed", "chunks_list": []}

        async def upsert(self, payload):
            del payload
            raise expected

    processor = DummyProcessor()
    processor.lightrag.doc_status = FailingDocStatus()

    with pytest.raises(StageFailure) as exc_info:
        await processor._mark_multimodal_processing_complete("doc-1")

    assert exc_info.value is expected


@pytest.mark.asyncio
async def test_completion_callback_failure_rolls_back_flag_for_immediate_retry():
    expected = StageFailure("completion callback")

    class MutatingDocStatus:
        def __init__(self):
            self.records = {
                "doc-1": {
                    "status": "processed",
                    "chunks_count": 0,
                    "chunks_list": [],
                }
            }
            self.callback_calls = 0

        async def get_by_id(self, doc_id):
            return self.records.get(doc_id)

        async def upsert(self, payload):
            for doc_id, record in payload.items():
                if doc_id in self.records:
                    self.records[doc_id].clear()
                    self.records[doc_id].update(record)
                else:
                    self.records[doc_id] = record

        async def index_done_callback(self):
            self.callback_calls += 1
            if self.callback_calls == 1:
                raise expected

    processor = DummyProcessor()
    processor.lightrag.doc_status = MutatingDocStatus()

    with pytest.raises(StageFailure) as exc_info:
        await processor._mark_multimodal_processing_complete("doc-1")

    assert exc_info.value is expected
    assert not processor.lightrag.doc_status.records["doc-1"].get(
        "multimodal_processed", False
    )

    processor._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    processor._process_multimodal_content_batch_type_aware = AsyncMock()
    processor._mark_multimodal_processing_complete = AsyncMock()

    await processor._process_multimodal_content(
        multimodal_items(False), "source.pdf", "doc-1"
    )

    processor._process_multimodal_content_batch_type_aware.assert_awaited_once()
    processor._mark_multimodal_processing_complete.assert_awaited_once_with("doc-1")
