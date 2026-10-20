import asyncio
import importlib.util
import logging
import sys
import threading
import types
from pathlib import Path

import pytest


@pytest.mark.parametrize("parse_fails", [False, True])
def test_rag_batch_keeps_event_loop_responsive(monkeypatch, tmp_path, parse_fails):
    parse_started = threading.Event()
    heartbeat = threading.Event()

    class Parser:
        OFFICE_FORMATS = set()
        IMAGE_FORMATS = set()
        TEXT_FORMATS = {".txt"}

        def parse_document(self, file_path, output_dir, method="auto", **kwargs):
            self.options = (method, kwargs)
            parse_started.set()
            self.loop_responded = heartbeat.wait(5)
            if parse_fails:
                raise ValueError("parse failed")
            return [{"type": "text", "text": Path(file_path).read_text()}]

    parser = Parser()
    repo_root = Path(__file__).parents[1]
    package = types.ModuleType("raganything")
    package.__path__ = [str(repo_root / "raganything")]
    parser_module = types.ModuleType("raganything.parser")
    parser_module.get_parser = lambda parser_type: parser
    monkeypatch.setitem(sys.modules, "raganything", package)
    monkeypatch.setitem(sys.modules, "raganything.parser", parser_module)

    modules = {}
    for name in ("batch_parser", "batch"):
        full_name = f"raganything.{name}"
        spec = importlib.util.spec_from_file_location(
            full_name, repo_root / "raganything" / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, module)
        spec.loader.exec_module(module)
        modules[name] = module

    events = []

    class Harness(modules["batch"].BatchMixin):
        config = types.SimpleNamespace(
            parser="test",
            parser_output_dir=str(tmp_path / "out"),
            parse_method="txt",
            max_concurrent_files=1,
            recursive_folder_processing=False,
        )
        logger = logging.getLogger(__name__)
        callback_manager = types.SimpleNamespace(
            dispatch=lambda name, **data: events.append((name, data))
        )

        def __init__(self):
            self.processed = []

        async def _ensure_lightrag_initialized(self):
            return {"success": True}

        async def process_document_complete(self, file_path, **kwargs):
            self.processed.append((file_path, kwargs))

    document = tmp_path / "document.txt"
    document.write_text("test document", encoding="utf-8")
    harness = Harness()

    async def run():
        async def heartbeat_during_parse():
            while not parse_started.is_set():
                await asyncio.sleep(0)
            heartbeat.set()

        return await asyncio.wait_for(
            asyncio.gather(
                harness.process_documents_with_rag_batch(
                    [str(document)],
                    show_progress=False,
                    incremental=True,
                    backend="pipeline",
                ),
                heartbeat_during_parse(),
            ),
            timeout=10,
        )

    result, _ = asyncio.run(run())

    assert parser.loop_responded
    assert parser.options == ("txt", {"backend": "pipeline"})
    parsed = result["parse_result"]
    if parse_fails:
        assert parsed.failed_files == [str(document)]
        assert parsed.successful_files == []
        assert harness.processed == []
        assert result["successful_rag_files"] == 0
    else:
        assert parsed.successful_files == [str(document)]
        assert parsed.failed_files == []
        assert harness.processed == [
            (
                str(document),
                {
                    "output_dir": harness.config.parser_output_dir,
                    "parse_method": "txt",
                    "backend": "pipeline",
                },
            )
        ]
        assert result["successful_rag_files"] == 1
    assert result["failed_rag_files"] == 0
    assert [name for name, _ in events] == ["on_batch_start", "on_batch_complete"]
    assert events[0][1] == {"file_count": 1}
    assert events[1][1]["successful"] == (0 if parse_fails else 1)
