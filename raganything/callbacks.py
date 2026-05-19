"""
Processing callbacks and event system for RAGAnything.

Provides a lightweight publish-subscribe mechanism that lets users hook
into every stage of the document processing pipeline — parsing, text
insertion, multimodal processing, and querying.

Usage::

    from raganything.callbacks import ProcessingCallback, CallbackManager

    class MyCallback(ProcessingCallback):
        def on_parse_start(self, file_path: str, **kw):
            print(f"Parsing started: {file_path}")

        def on_parse_complete(self, file_path: str, content_blocks: int, **kw):
            print(f"Parsed {content_blocks} blocks from {file_path}")

    rag = RAGAnything(config=config)
    rag.callback_manager.register(MyCallback())
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import threading

logger = logging.getLogger(__name__)


@dataclass
class ProcessingEvent:
    """Immutable record of a processing pipeline event."""

    event_type: str
    timestamp: float = field(default_factory=time.time)
    file_path: Optional[str] = None
    doc_id: Optional[str] = None
    stage: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "doc_id": self.doc_id,
            "stage": self.stage,
            "details": self.details,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class ProcessingCallback:
    """Base class for processing pipeline callbacks.

    Override any of the ``on_*`` methods to hook into the corresponding
    stage.  Methods that are not overridden are silently ignored.

    All methods receive ``**kwargs`` so that future versions can add
    parameters without breaking existing subclasses.
    """

    # ── Parsing stage ─────────────────────────────────────────────
    def on_parse_start(self, file_path: str, parser: str = "", **kwargs: Any) -> None:
        """Called before document parsing begins."""

    def on_parse_complete(
        self,
        file_path: str,
        content_blocks: int = 0,
        doc_id: str = "",
        duration_seconds: float = 0.0,
        **kwargs: Any,
    ) -> None:
        """Called after document parsing succeeds."""

    def on_parse_error(
        self, file_path: str, error: BaseException | str = "", **kwargs: Any
    ) -> None:
        """Called when document parsing fails."""

    # ── Text insertion stage ──────────────────────────────────────
    def on_text_insert_start(
        self, file_path: str, text_length: int = 0, **kwargs: Any
    ) -> None:
        """Called before text content is inserted into LightRAG."""

    def on_text_insert_complete(
        self, file_path: str, duration_seconds: float = 0.0, **kwargs: Any
    ) -> None:
        """Called after text content insertion succeeds."""

    # ── Multimodal processing stage ───────────────────────────────
    def on_multimodal_start(
        self, file_path: str, item_count: int = 0, **kwargs: Any
    ) -> None:
        """Called before multimodal content processing begins."""

    def on_multimodal_item_complete(
        self,
        file_path: str,
        item_index: int = 0,
        item_type: str = "",
        total_items: int = 0,
        **kwargs: Any,
    ) -> None:
        """Called after each individual multimodal item is processed."""

    def on_multimodal_complete(
        self,
        file_path: str,
        processed_count: int = 0,
        duration_seconds: float = 0.0,
        **kwargs: Any,
    ) -> None:
        """Called after all multimodal content processing completes."""

    # ── Query stage ───────────────────────────────────────────────
    def on_query_start(self, query: str, mode: str = "", **kwargs: Any) -> None:
        """Called before a query is executed."""

    def on_query_complete(
        self,
        query: str,
        mode: str = "",
        duration_seconds: float = 0.0,
        result_length: int = 0,
        **kwargs: Any,
    ) -> None:
        """Called after a query completes."""

    def on_query_error(
        self,
        query: str,
        mode: str = "",
        error: BaseException | str = "",
        **kwargs: Any,
    ) -> None:
        """Called when a query fails."""

    # ── Document complete ─────────────────────────────────────────
    def on_document_complete(
        self,
        file_path: str,
        doc_id: str = "",
        duration_seconds: float = 0.0,
        **kwargs: Any,
    ) -> None:
        """Called when the entire document processing pipeline finishes."""

    def on_document_error(
        self,
        file_path: str,
        error: BaseException | str = "",
        stage: str = "",
        **kwargs: Any,
    ) -> None:
        """Called when document processing fails at any stage."""

    # ── Batch processing ──────────────────────────────────────────
    def on_batch_start(self, file_count: int = 0, **kwargs: Any) -> None:
        """Called when batch processing begins."""

    def on_batch_complete(
        self,
        total_files: int = 0,
        successful: int = 0,
        failed: int = 0,
        duration_seconds: float = 0.0,
        **kwargs: Any,
    ) -> None:
        """Called when batch processing completes."""


class MetricsCallback(ProcessingCallback):
    """Built-in callback that collects processing metrics.

    Access aggregated metrics via the :attr:`metrics` attribute.

    Example::

        metrics_cb = MetricsCallback()
        rag.callback_manager.register(metrics_cb)
        # ... process documents ...
        print(metrics_cb.summary())
    """

    def __init__(self) -> None:
        self.metrics: Dict[str, Any] = {
            "documents_processed": 0,
            "documents_failed": 0,
            "total_content_blocks": 0,
            "total_multimodal_items": 0,
            "total_parse_time": 0.0,
            "total_insert_time": 0.0,
            "total_multimodal_time": 0.0,
            "queries_executed": 0,
            "total_query_time": 0.0,
            "errors": [],
        }

    def on_parse_complete(
        self,
        file_path: str,
        content_blocks: int = 0,
        duration_seconds: float = 0.0,
        **kw: Any,
    ) -> None:
        self.metrics["total_content_blocks"] += content_blocks
        self.metrics["total_parse_time"] += duration_seconds

    def on_text_insert_complete(
        self, file_path: str, duration_seconds: float = 0.0, **kw: Any
    ) -> None:
        self.metrics["total_insert_time"] += duration_seconds

    def on_multimodal_complete(
        self,
        file_path: str,
        processed_count: int = 0,
        duration_seconds: float = 0.0,
        **kw: Any,
    ) -> None:
        self.metrics["total_multimodal_items"] += processed_count
        self.metrics["total_multimodal_time"] += duration_seconds

    def on_document_complete(self, file_path: str, **kw: Any) -> None:
        self.metrics["documents_processed"] += 1

    def on_document_error(
        self,
        file_path: str,
        error: BaseException | str = "",
        stage: str = "",
        **kw: Any,
    ) -> None:
        self.metrics["documents_failed"] += 1
        self.metrics["errors"].append(
            {"file": file_path, "error": str(error), "stage": stage}
        )

    def on_query_complete(
        self, query: str, duration_seconds: float = 0.0, **kw: Any
    ) -> None:
        self.metrics["queries_executed"] += 1
        self.metrics["total_query_time"] += duration_seconds

    def on_query_error(
        self, query: str, error: BaseException | str = "", **kw: Any
    ) -> None:
        self.metrics["errors"].append(
            {"file": None, "error": str(error), "stage": "query"}
        )

    def summary(self) -> str:
        """Return a human-readable summary of collected metrics."""
        m = self.metrics
        lines = [
            "RAGAnything Processing Metrics",
            "=" * 40,
            f"Documents processed : {m['documents_processed']}",
            f"Documents failed    : {m['documents_failed']}",
            f"Content blocks      : {m['total_content_blocks']}",
            f"Multimodal items    : {m['total_multimodal_items']}",
            f"Parse time          : {m['total_parse_time']:.2f}s",
            f"Insert time         : {m['total_insert_time']:.2f}s",
            f"Multimodal time     : {m['total_multimodal_time']:.2f}s",
            f"Queries executed    : {m['queries_executed']}",
            f"Query time          : {m['total_query_time']:.2f}s",
        ]
        if m["errors"]:
            lines.append(f"Errors              : {len(m['errors'])}")
            for err in m["errors"][:5]:
                lines.append(f"  - [{err['stage']}] {err['file']}: {err['error']}")
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all collected metrics."""
        self.__init__()


class CallbackManager:
    """Manages and dispatches events to registered callbacks.

    Thread-safe for registration/unregistration and event logging.
    Event dispatch iterates over a snapshot of currently registered
    callbacks so that callbacks can safely register/unregister others.
    """

    def __init__(self) -> None:
        self._callbacks: List[ProcessingCallback] = []
        self._event_log: List[ProcessingEvent] = []
        self._log_events: bool = False
        self._lock = threading.RLock()

    def register(self, callback: ProcessingCallback) -> None:
        """Register a callback to receive processing events.

        Args:
            callback: An instance of :class:`ProcessingCallback` (or subclass).

        Raises:
            TypeError: If *callback* is not a :class:`ProcessingCallback`.
        """
        if not isinstance(callback, ProcessingCallback):
            raise TypeError(
                f"Expected ProcessingCallback instance, got {type(callback).__name__}"
            )
        with self._lock:
            self._callbacks.append(callback)

    def unregister(self, callback: ProcessingCallback) -> None:
        """Remove a previously registered callback."""
        with self._lock:
            self._callbacks.remove(callback)

    def enable_event_log(self, enabled: bool = True) -> None:
        """Enable or disable internal event logging.

        When enabled, every dispatched event is recorded in
        :attr:`event_log` for later inspection.
        """
        with self._lock:
            self._log_events = enabled

    @property
    def event_log(self) -> List[ProcessingEvent]:
        """Read-only access to the internal event log."""
        with self._lock:
            return list(self._event_log)

    def clear_event_log(self) -> None:
        """Clear the internal event log."""
        with self._lock:
            self._event_log.clear()

    def dispatch(self, event_name: str, **kwargs: Any) -> None:
        """Dispatch an event to all registered callbacks.

        Args:
            event_name: Name of the callback method (e.g., ``"on_parse_start"``).
            **kwargs: Arguments forwarded to the callback method.
        """
        with self._lock:
            callbacks_snapshot = list(self._callbacks)
            log_events = self._log_events
            if log_events:
                event = ProcessingEvent(
                    event_type=event_name,
                    file_path=kwargs.get("file_path"),
                    doc_id=kwargs.get("doc_id"),
                    stage=kwargs.get("stage"),
                    details=kwargs,
                    duration_seconds=kwargs.get("duration_seconds"),
                    error=str(kwargs["error"]) if "error" in kwargs else None,
                )
                self._event_log.append(event)

        for cb in callbacks_snapshot:
            handler = getattr(cb, event_name, None)
            if handler is not None:
                try:
                    handler(**kwargs)
                except Exception:
                    logger.exception(
                        "Error in callback %s.%s",
                        type(cb).__name__,
                        event_name,
                    )
