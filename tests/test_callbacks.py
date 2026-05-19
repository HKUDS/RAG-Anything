"""Tests for the processing callbacks and events system."""

import pytest
from raganything.callbacks import (
    ProcessingCallback,
    ProcessingEvent,
    MetricsCallback,
    CallbackManager,
)


class RecordingCallback(ProcessingCallback):
    """Callback that records all events for testing."""

    def __init__(self):
        self.events = []

    def on_parse_start(self, file_path, **kw):
        self.events.append(("parse_start", file_path))

    def on_parse_complete(self, file_path, content_blocks=0, **kw):
        self.events.append(("parse_complete", file_path, content_blocks))

    def on_parse_error(self, file_path, error="", **kw):
        self.events.append(("parse_error", file_path, str(error)))

    def on_text_insert_start(self, file_path, **kw):
        self.events.append(("text_insert_start", file_path))

    def on_text_insert_complete(self, file_path, **kw):
        self.events.append(("text_insert_complete", file_path))

    def on_multimodal_start(self, file_path, item_count=0, **kw):
        self.events.append(("multimodal_start", file_path, item_count))

    def on_multimodal_item_complete(
        self, file_path, item_index=0, item_type="", total_items=0, **kw
    ):
        self.events.append(("multimodal_item", file_path, item_index, item_type))

    def on_multimodal_complete(self, file_path, processed_count=0, **kw):
        self.events.append(("multimodal_complete", file_path, processed_count))

    def on_document_complete(self, file_path, **kw):
        self.events.append(("document_complete", file_path))

    def on_document_error(self, file_path, error="", stage="", **kw):
        self.events.append(("document_error", file_path, str(error), stage))

    def on_query_start(self, query, mode="", **kw):
        self.events.append(("query_start", query, mode))

    def on_query_complete(self, query, mode="", **kw):
        self.events.append(("query_complete", query, mode))

    def on_batch_start(self, file_count=0, **kw):
        self.events.append(("batch_start", file_count))

    def on_batch_complete(self, total_files=0, successful=0, failed=0, **kw):
        self.events.append(("batch_complete", total_files, successful, failed))


class TestCallbackManager:
    def test_register_and_dispatch(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        mgr.dispatch("on_parse_start", file_path="test.pdf", parser="mineru")
        assert len(cb.events) == 1
        assert cb.events[0] == ("parse_start", "test.pdf")

    def test_multiple_callbacks(self):
        mgr = CallbackManager()
        cb1 = RecordingCallback()
        cb2 = RecordingCallback()
        mgr.register(cb1)
        mgr.register(cb2)
        mgr.dispatch("on_parse_start", file_path="test.pdf")
        assert len(cb1.events) == 1
        assert len(cb2.events) == 1

    def test_unregister(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        mgr.unregister(cb)
        mgr.dispatch("on_parse_start", file_path="test.pdf")
        assert len(cb.events) == 0

    def test_register_rejects_non_callback(self):
        mgr = CallbackManager()
        with pytest.raises(TypeError, match="ProcessingCallback"):
            mgr.register("not a callback")

    def test_dispatch_handles_callback_errors(self):
        class ErrorCallback(ProcessingCallback):
            def on_parse_start(self, **kw):
                raise RuntimeError("callback error")

        mgr = CallbackManager()
        mgr.register(ErrorCallback())
        # Should not raise — errors are logged and swallowed
        mgr.dispatch("on_parse_start", file_path="test.pdf")

    def test_dispatch_unknown_event(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        # Unknown events are silently ignored
        mgr.dispatch("on_unknown_event", file_path="test.pdf")
        assert len(cb.events) == 0

    def test_event_log_disabled_by_default(self):
        mgr = CallbackManager()
        mgr.dispatch("on_parse_start", file_path="test.pdf")
        assert len(mgr.event_log) == 0

    def test_event_log_enabled(self):
        mgr = CallbackManager()
        mgr.enable_event_log(True)
        mgr.dispatch("on_parse_start", file_path="test.pdf")
        assert len(mgr.event_log) == 1
        assert mgr.event_log[0].event_type == "on_parse_start"
        assert mgr.event_log[0].file_path == "test.pdf"

    def test_clear_event_log(self):
        mgr = CallbackManager()
        mgr.enable_event_log(True)
        mgr.dispatch("on_parse_start", file_path="test.pdf")
        mgr.clear_event_log()
        assert len(mgr.event_log) == 0


class TestProcessingEvent:
    def test_to_dict(self):
        event = ProcessingEvent(
            event_type="on_parse_start",
            file_path="test.pdf",
            stage="parsing",
        )
        d = event.to_dict()
        assert d["event_type"] == "on_parse_start"
        assert d["file_path"] == "test.pdf"
        assert d["stage"] == "parsing"
        assert isinstance(d["timestamp"], float)


class TestMetricsCallback:
    def test_collects_metrics(self):
        m = MetricsCallback()
        m.on_parse_complete(file_path="a.pdf", content_blocks=10, duration_seconds=1.5)
        m.on_parse_complete(file_path="b.pdf", content_blocks=5, duration_seconds=0.5)
        m.on_text_insert_complete(file_path="a.pdf", duration_seconds=2.0)
        m.on_multimodal_complete(
            file_path="a.pdf", processed_count=3, duration_seconds=3.0
        )
        m.on_document_complete(file_path="a.pdf")
        m.on_document_complete(file_path="b.pdf")
        m.on_document_error(file_path="c.pdf", error="parse failed", stage="parsing")
        m.on_query_complete(query="test", duration_seconds=0.3)

        assert m.metrics["documents_processed"] == 2
        assert m.metrics["documents_failed"] == 1
        assert m.metrics["total_content_blocks"] == 15
        assert m.metrics["total_multimodal_items"] == 3
        assert m.metrics["queries_executed"] == 1
        assert len(m.metrics["errors"]) == 1

    def test_summary(self):
        m = MetricsCallback()
        m.on_document_complete(file_path="a.pdf")
        summary = m.summary()
        assert "Documents processed" in summary
        assert "1" in summary

    def test_reset(self):
        m = MetricsCallback()
        m.on_document_complete(file_path="a.pdf")
        m.reset()
        assert m.metrics["documents_processed"] == 0


class TestRAGAnythingIntegration:
    def test_process_document_emits_callbacks(self, monkeypatch, tmp_path):
        pytest.importorskip("lightrag")

        from raganything import RAGAnything, RAGAnythingConfig
        import raganything.processor as processor_module
        import asyncio

        config = RAGAnythingConfig()
        config.parser_output_dir = str(tmp_path)
        rag = RAGAnything(config=config)
        cb = RecordingCallback()
        rag.callback_manager.register(cb)

        async def fake_ensure():
            return {"success": True}

        async def fake_parse(
            file_path, output_dir, parse_method, display_stats, **kwargs
        ):
            # Single text block, no multimodal content.
            return ([{"type": "text", "text": "hello world"}], "doc-123")

        async def fake_mm(items, file_path, doc_id):
            return

        async def fake_mark(doc_id):
            return

        async def fake_insert_text_content(*args, **kwargs):
            return

        monkeypatch.setattr(rag, "_ensure_lightrag_initialized", fake_ensure)
        monkeypatch.setattr(rag, "parse_document", fake_parse)
        monkeypatch.setattr(rag, "_process_multimodal_content", fake_mm)
        monkeypatch.setattr(rag, "_mark_multimodal_processing_complete", fake_mark)
        monkeypatch.setattr(
            processor_module, "insert_text_content", fake_insert_text_content
        )

        asyncio.run(
            rag.process_document_complete(
                str(tmp_path / "dummy.pdf"),
                output_dir=str(tmp_path),
                parse_method="auto",
                display_stats=False,
            )
        )

        event_kinds = [e[0] for e in cb.events]
        assert "parse_start" in event_kinds
        assert "parse_complete" in event_kinds
        assert "text_insert_start" in event_kinds
        assert "text_insert_complete" in event_kinds
        assert "document_complete" in event_kinds

    def test_query_emits_callbacks(self, monkeypatch):
        pytest.importorskip("lightrag")

        from raganything import RAGAnything, RAGAnythingConfig
        import asyncio

        class FakeLightRAG:
            async def aquery(self, query, param, system_prompt=None):
                return "answer"

        config = RAGAnythingConfig()
        rag = RAGAnything(config=config)
        rag.lightrag = FakeLightRAG()

        cb = RecordingCallback()
        rag.callback_manager.register(cb)

        async def run_query():
            return await rag.aquery("hello", mode="mix")

        result = asyncio.run(run_query())
        assert result == "answer"

        event_kinds = [e[0] for e in cb.events]
        assert ("query_start", "hello", "mix") in cb.events
        assert any(kind == "query_complete" for kind in event_kinds)
