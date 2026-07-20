import asyncio
import importlib.util
import sys
import types
from pathlib import Path


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
