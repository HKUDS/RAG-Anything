"""Content-free timing for interactive agent queries."""

from __future__ import annotations

import logging
import math
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
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
_PHASE_ORDER = {
    "settings_quota": 0,
    "query_core_acquire": 1,
    "bm25_pg_read": 2,
    "bm25_build": 3,
    "retrieval": 4,
    "media": 5,
    "llm_first_token": 6,
    "llm": 7,
    "llm_last_token": 8,
    "persistence": 9,
}
_CHANNEL_ORDER = {"bm25": 0, "vector": 1, "graph": 2, "na": 3, "other": 4}
_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TRACE_ID_KEY = secrets.token_bytes(16)
_CLOSED_TRACE_LIMIT = 4096

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
    return value if isinstance(value, str) and value in allowed else "other"


@dataclass(frozen=True)
class _CompletedStage:
    phase: str
    outcome: str
    cache_status: str
    channel: str
    elapsed_ms: float
    insertion_order: int


@dataclass
class _JourneyState:
    completed_stages: list[_CompletedStage] = field(default_factory=list)
    phase_started: dict[str, float] = field(default_factory=dict)
    closed: bool = False
    total_elapsed_ms: float | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


_JOURNEY_STATES: dict[str, _JourneyState] = {}
_CLOSED_JOURNEYS: OrderedDict[str, _JourneyState] = OrderedDict()
_JOURNEY_STATES_LOCK = threading.RLock()


def _safe_trace_id(value: object) -> str:
    if isinstance(value, str) and _TRACE_ID_PATTERN.fullmatch(value):
        return value
    raw_value = str(value).encode("utf-8", errors="replace")
    alias = uuid.uuid5(
        uuid.UUID(bytes=_TRACE_ID_KEY), raw_value.decode("utf-8", errors="replace")
    ).hex[:12]
    return f"invalid-{alias}"


def _get_journey_state(trace_id: str) -> _JourneyState:
    with _JOURNEY_STATES_LOCK:
        active = _JOURNEY_STATES.get(trace_id)
        if active is not None:
            return active
        closed = _CLOSED_JOURNEYS.get(trace_id)
        if closed is not None:
            _CLOSED_JOURNEYS.move_to_end(trace_id)
            return closed
        state = _JourneyState()
        _JOURNEY_STATES[trace_id] = state
        return state


def _release_journey_state(trace_id: str, state: _JourneyState) -> None:
    with _JOURNEY_STATES_LOCK:
        if _JOURNEY_STATES.get(trace_id) is state:
            _JOURNEY_STATES.pop(trace_id, None)
            _CLOSED_JOURNEYS[trace_id] = state
            _CLOSED_JOURNEYS.move_to_end(trace_id)
            while len(_CLOSED_JOURNEYS) > _CLOSED_TRACE_LIMIT:
                _CLOSED_JOURNEYS.popitem(last=False)


def _elapsed_ms(value: float) -> float:
    try:
        elapsed_ms = float(value) * 1000
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(elapsed_ms):
        return 0.0
    return max(0.0, elapsed_ms)


def _stage_sort_key(stage: _CompletedStage) -> tuple[int, int, int]:
    return (
        _PHASE_ORDER.get(stage.phase, len(_PHASE_ORDER)),
        _CHANNEL_ORDER.get(stage.channel, len(_CHANNEL_ORDER))
        if stage.phase == "retrieval"
        else 0,
        stage.insertion_order,
    )


@dataclass
class QueryTiming:
    """Monotonic phase timer that never accepts request content as input."""

    trace_id: str
    started_at: float = field(default_factory=time.perf_counter)
    _journey_state: _JourneyState = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.trace_id = _safe_trace_id(self.trace_id)
        self._journey_state = _get_journey_state(self.trace_id)

    def start(self, phase: str) -> None:
        with self._journey_state.lock:
            if (
                self._journey_state.closed
                or phase == "total"
                or phase in self._journey_state.phase_started
            ):
                return
            self._journey_state.phase_started[phase] = time.perf_counter()

    def _emit_phase_locked(
        self,
        phase: str,
        elapsed_ms: float,
        *,
        outcome: str,
        cache_status: str,
        channel: str,
    ) -> float:
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
        self._record_completed_stage(
            metric_phase,
            metric_outcome,
            metric_cache,
            metric_channel,
            elapsed_ms,
        )
        return elapsed_ms

    def _finish_locked(
        self,
        phase: str,
        *,
        outcome: str,
        cache_status: str,
        channel: str,
    ) -> float:
        started_at = self._journey_state.phase_started.pop(phase, None)
        if started_at is None:
            return 0.0
        return self._emit_phase_locked(
            phase,
            _elapsed_ms(time.perf_counter() - started_at),
            outcome=outcome,
            cache_status=cache_status,
            channel=channel,
        )

    def finish(
        self,
        phase: str,
        *,
        outcome: str = "ok",
        cache_status: str = "na",
        channel: str = "na",
    ) -> float:
        with self._journey_state.lock:
            if self._journey_state.closed or phase == "total":
                return 0.0
            return self._finish_locked(
                phase,
                outcome=outcome,
                cache_status=cache_status,
                channel=channel,
            )

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
        with self._journey_state.lock:
            if self._journey_state.closed or phase == "total":
                return 0.0
            return self._emit_phase_locked(
                phase,
                _elapsed_ms(elapsed_seconds),
                outcome=outcome,
                cache_status=cache_status,
                channel=channel,
            )

    def total(self, *, outcome: str = "ok") -> float:
        with self._journey_state.lock:
            if self._journey_state.closed:
                return self._journey_state.total_elapsed_ms or 0.0
            metric_outcome = _bounded(outcome, _OUTCOMES)
            for phase in list(self._journey_state.phase_started):
                self._finish_locked(
                    phase,
                    outcome=metric_outcome,
                    cache_status="na",
                    channel="na",
                )
            elapsed_ms = _elapsed_ms(time.perf_counter() - self.started_at)
            _PHASE_DURATION.labels(
                "total", metric_outcome, "na", "na"
            ).observe(elapsed_ms / 1000)
            _logger.info(
                "QUERY_TIMING trace_id=%s phase=total outcome=%s cache_status=na channel=na elapsed_ms=%.2f",
                self.trace_id,
                metric_outcome,
                elapsed_ms,
            )
            self._journey_state.total_elapsed_ms = elapsed_ms
            self._journey_state.closed = True
            _logger.info(
                "QUERY_JOURNEY trace_id=%s outcome=%s total_elapsed_ms=%.2f stages=%s",
                self.trace_id,
                metric_outcome,
                elapsed_ms,
                self._format_completed_stages(),
            )
            _release_journey_state(self.trace_id, self._journey_state)
            return elapsed_ms

    def _record_completed_stage(
        self,
        phase: str,
        outcome: str,
        cache_status: str,
        channel: str,
        elapsed_ms: float,
    ) -> None:
        """Keep terminal summaries bounded to timing metadata completed before close."""
        if self._journey_state.closed:
            return
        self._journey_state.completed_stages.append(
            _CompletedStage(
                phase=phase,
                outcome=outcome,
                cache_status=cache_status,
                channel=channel,
                elapsed_ms=elapsed_ms,
                insertion_order=len(self._journey_state.completed_stages),
            )
        )

    def _format_completed_stages(self) -> str:
        ordered = sorted(self._journey_state.completed_stages, key=_stage_sort_key)
        if not ordered:
            return "none"
        return ";".join(
            (
                f"{stage.phase if stage.phase != 'retrieval' or stage.channel == 'na' else f'{stage.phase}/{stage.channel}'}"
                f"{{outcome={stage.outcome},cache_status={stage.cache_status},"
                f"channel={stage.channel},elapsed_ms={stage.elapsed_ms:.2f}}}"
            )
            for stage in ordered
        )
