"""A non-positive worker limit must be rejected, not drop every file.

ThreadPoolExecutor raises for it only once the batch runs, where the error
was swallowed and an empty result returned (successful=[], failed=[]).
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from raganything.batch import BatchMixin
from raganything.batch_parser import BatchParser

MESSAGE = "max_workers must be greater than zero"


@pytest.mark.parametrize("max_workers", [0, -1])
def test_batch_parser_rejects_nonpositive_workers(max_workers):
    with pytest.raises(ValueError, match=MESSAGE):
        BatchParser(
            parser_type="docling",
            max_workers=max_workers,
            skip_installation_check=True,
        )


@pytest.fixture
def harness(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "document.txt").write_text("Document", encoding="utf-8")
    rag = BatchMixin()
    rag.config = SimpleNamespace(
        parser="docling",
        parser_output_dir=str(tmp_path / "out"),
        parse_method="auto",
        max_concurrent_files=1,
        recursive_folder_processing=True,
    )
    rag.logger = logging.getLogger(__name__)
    rag._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    rag.process_document_complete = AsyncMock()
    rag.paths = [str(tmp_path / "docs")]
    return rag


@pytest.mark.parametrize("max_workers", [0, -1])
@pytest.mark.parametrize("use_config", [False, True])
def test_batch_methods_reject_nonpositive_workers(harness, max_workers, use_config):
    if use_config:
        harness.config.max_concurrent_files = max_workers
    kwargs = {"max_workers": None if use_config else max_workers}

    with pytest.raises(ValueError, match=MESSAGE):
        harness.process_documents_batch(harness.paths, show_progress=False, **kwargs)
    with pytest.raises(ValueError, match=MESSAGE):
        asyncio.run(
            harness.process_documents_with_rag_batch(
                harness.paths, show_progress=False, **kwargs
            )
        )
    harness._ensure_lightrag_initialized.assert_not_awaited()
    harness.process_document_complete.assert_not_awaited()
