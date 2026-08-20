"""Regression tests for the individual multimodal fallback pipeline."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from raganything.processor import ProcessorMixin


class RecordingLogger:
    """Minimal logger for processor tests."""

    def debug(self, *args, **kwargs):
        del args, kwargs

    def error(self, *args, **kwargs):
        del args, kwargs

    def info(self, *args, **kwargs):
        del args, kwargs

    def warning(self, *args, **kwargs):
        del args, kwargs


class FakeDocStatus:
    """Return the text-processing status used by the fallback pipeline."""

    async def get_by_id(self, doc_id):
        del doc_id
        return {"chunks_count": 0}


class FallbackModalProcessor:
    """Model the public three-value fallback contract."""

    async def process_multimodal_content(self, **kwargs):
        del kwargs
        return "fallback", {"entity_type": "image"}, None


class DummyProcessor(ProcessorMixin):
    """Processor with only the dependencies needed by the regression test."""

    def __init__(self):
        self.config = SimpleNamespace(use_full_path=False)
        self.lightrag = SimpleNamespace(doc_status=FakeDocStatus())
        self.logger = RecordingLogger()
        self.modal_processors = {"image": FallbackModalProcessor()}


@pytest.mark.asyncio
async def test_individual_fallback_rejects_missing_chunk_results_before_completion():
    processor = DummyProcessor()
    processor._update_doc_status_with_chunks_type_aware = AsyncMock()
    processor._mark_multimodal_processing_complete = AsyncMock()

    with pytest.raises(RuntimeError, match=r"0/1 succeeded") as exc_info:
        await processor._process_multimodal_content_individual(
            [{"type": "image"}], "source.pdf", "doc-1"
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "returned no chunk results" in str(exc_info.value.__cause__)
    processor._update_doc_status_with_chunks_type_aware.assert_not_awaited()
    processor._mark_multimodal_processing_complete.assert_not_awaited()
