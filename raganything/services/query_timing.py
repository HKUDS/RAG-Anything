"""Content-free timing for interactive agent queries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from prometheus_client import Histogram, REGISTRY


_logger = logging.getLogger("rag_server.query_timing")
_PHASES = frozenset({
    "settings_quota", "query_core_acquire", "retrieval", "bm25_pg_read",
    "bm25_build", "media", "llm", "llm_first_token", "llm_last_token",
    "persistence", "total",
})
_OUTCOMES = frozenset({"ok", "error", "timeout", "cancelled"})
_CACHE_STATUSES = frozenset({"hit", "miss", "shared", "na"})
_CHANNELS = frozenset({"bm25", "vector", "graph", "na"})

try:
    _PHASE_DURATION = Histogram(
        "rag_agent_query_phase_duration_seconds",
        "Interactive agent query phase duration.",
        ("phase", "outcome", "cache_status", "channel"),
    )
except ValueError:
    _PHASE_DURATION = REGISTRY._names_to_collectors[
        "rag_agent_query_phase_duration_seconds"
    ]


def _bounded(value: str, allowed: frozenset[str]) -> str:
    return value if value in allowed else "other"


@dataclass
class QueryTiming:
    """Monotonic phase timer that never accepts request content as input."""

    trace_id: str
    started_at: float = field(default_factory=time.perf_counter)
    _phase_started: dict[str, float] = field(default_factory=dict)

    def start(self, phase: str) -> None:
        self._phase_started[phase] = time.perf_counter()

    def finish(
        self,
        phase: str,
        *,
        outcome: str = "ok",
        cache_status: str = "na",
        channel: str = "na",
    ) -> float:
        elapsed_ms = (time.perf_counter() - self._phase_started.pop(phase, self.started_at)) * 1000
        metric_phase = _bounded(phase, _PHASES)
        metric_outcome = _bounded(outcome, _OUTCOMES)
        metric_cache = _bounded(cache_status, _CACHE_STATUSES)
        metric_channel = _bounded(channel, _CHANNELS)
        _PHASE_DURATION.labels(
            metric_phase, metric_outcome, metric_cache, metric_channel
        ).observe(elapsed_ms / 1000)
        _logger.info(
            "QUERY_TIMING trace_id=%s phase=%s outcome=%s cache_status=%s channel=%s elapsed_ms=%.2f",
            self.trace_id,
            metric_phase,
            metric_outcome,
            metric_cache,
            metric_channel,
            elapsed_ms,
        )
        return elapsed_ms

    def record(
        self,
        phase: str,
        elapsed_seconds: float,
        *,
        outcome: str = "ok",
        cache_status: str = "na",
        channel: str = "na",
    ) -> float:
        """Record a completed phase that overlaps another phase timer."""
        elapsed_ms = max(0.0, float(elapsed_seconds) * 1000)
        _PHASE_DURATION.labels(
            _bounded(phase, _PHASES),
            _bounded(outcome, _OUTCOMES),
            _bounded(cache_status, _CACHE_STATUSES),
            _bounded(channel, _CHANNELS),
        ).observe(elapsed_ms / 1000)
        _logger.info(
            "QUERY_TIMING trace_id=%s phase=%s outcome=%s cache_status=%s channel=%s elapsed_ms=%.2f",
            self.trace_id,
            _bounded(phase, _PHASES),
            _bounded(outcome, _OUTCOMES),
            _bounded(cache_status, _CACHE_STATUSES),
            _bounded(channel, _CHANNELS),
            elapsed_ms,
        )
        return elapsed_ms

    def total(self, *, outcome: str = "ok") -> float:
        # Early returns, errors, and client disconnects still close any phase
        # that started, making the timing stream complete without payload data.
        for phase in list(self._phase_started):
            self.finish(phase, outcome=outcome)
        elapsed_ms = (time.perf_counter() - self.started_at) * 1000
        _PHASE_DURATION.labels(
            "total", _bounded(outcome, _OUTCOMES), "na", "na"
        ).observe(elapsed_ms / 1000)
        _logger.info(
            "QUERY_TIMING trace_id=%s phase=total outcome=%s cache_status=na channel=na elapsed_ms=%.2f",
            self.trace_id,
            outcome,
            elapsed_ms,
        )
        return elapsed_ms
