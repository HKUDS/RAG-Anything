"""Focused tests for fail-closed multimodal ingestion."""

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


class FakeDocStatus:
    """Status store that returns an uninitialized document."""

    async def get_by_id(self, doc_id):
        del doc_id
        return None


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
