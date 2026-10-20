import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


def _load_batch_mixin(monkeypatch):
    repo_root = Path(__file__).parents[1]
    package = types.ModuleType("raganything")
    package.__path__ = [str(repo_root / "raganything")]
    batch_parser_module = types.ModuleType("raganything.batch_parser")
    batch_parser_module.BatchParser = object
    batch_parser_module.BatchProcessingResult = object

    monkeypatch.setitem(sys.modules, "raganything", package)
    monkeypatch.setitem(sys.modules, "raganything.batch_parser", batch_parser_module)
    sys.modules.pop("raganything.batch", None)

    spec = importlib.util.spec_from_file_location(
        "raganything.batch", repo_root / "raganything" / "batch.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "raganything.batch", module)
    spec.loader.exec_module(module)
    return module.BatchMixin


def test_process_folder_matches_extensions_case_insensitively(monkeypatch, tmp_path):
    batch_mixin = _load_batch_mixin(monkeypatch)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    upper_pdf = docs_dir / "REPORT.PDF"
    upper_pdf.write_bytes(b"pdf")

    class Harness(batch_mixin):
        def __init__(self):
            self.config = types.SimpleNamespace(
                parser_output_dir=str(tmp_path / "out"),
                parse_method="auto",
                supported_file_extensions=[".pdf"],
                recursive_folder_processing=True,
                max_concurrent_files=1,
            )
            self.logger = types.SimpleNamespace(
                info=lambda *args: None,
                warning=lambda *args: None,
                error=lambda *args: None,
            )
            self.processed = []

        async def _ensure_lightrag_initialized(self):
            return {"success": True}

        async def process_document_complete(self, file_path, **kwargs):
            self.processed.append(file_path)

    harness = Harness()
    asyncio.run(harness.process_folder_complete(str(docs_dir), display_stats=False))

    assert harness.processed == [str(upper_pdf)]


@pytest.fixture
def folder_harness(monkeypatch, tmp_path):
    batch_mixin = _load_batch_mixin(monkeypatch)
    harness = batch_mixin()
    harness.config = types.SimpleNamespace(
        parser_output_dir=str(tmp_path / "out"),
        parse_method="auto",
        supported_file_extensions=[".txt"],
        recursive_folder_processing=True,
        max_concurrent_files=1,
    )
    harness.logger = Mock()
    harness._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    harness.process_document_complete = AsyncMock()
    (tmp_path / "document.txt").write_text("Document")
    return harness


@pytest.mark.parametrize("max_workers", [0, -1])
@pytest.mark.parametrize("use_config", [False, True])
def test_process_folder_rejects_nonpositive_workers(
    tmp_path, folder_harness, max_workers, use_config
):
    if use_config:
        folder_harness.config.max_concurrent_files = max_workers

    async def run():
        with pytest.raises(ValueError, match="max_workers must be greater than zero"):
            await asyncio.wait_for(
                folder_harness.process_folder_complete(
                    str(tmp_path),
                    max_workers=None if use_config else max_workers,
                ),
                timeout=0.1,
            )

    asyncio.run(run())
    folder_harness._ensure_lightrag_initialized.assert_not_awaited()
    folder_harness.process_document_complete.assert_not_awaited()


@pytest.mark.parametrize("configured_workers", [0, 1])
def test_process_folder_accepts_positive_worker_limit(
    tmp_path, folder_harness, configured_workers
):
    folder_harness.config.max_concurrent_files = configured_workers
    asyncio.run(
        asyncio.wait_for(
            folder_harness.process_folder_complete(
                str(tmp_path),
                max_workers=1 if configured_workers == 0 else None,
                display_stats=False,
            ),
            timeout=1,
        )
    )
    folder_harness.process_document_complete.assert_awaited_once()
    assert folder_harness.process_document_complete.await_args.args[0] == str(
        tmp_path / "document.txt"
    )
