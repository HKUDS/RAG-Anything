"""Elapsed-time circuit breaker windows must survive wall-clock adjustments."""

from types import SimpleNamespace

import pytest

from raganything import resilience


@pytest.fixture
def clock(monkeypatch):
    now = SimpleNamespace(elapsed=100.0, wall=1000.0)
    monkeypatch.setattr(
        resilience,
        "time",
        SimpleNamespace(monotonic=lambda: now.elapsed, time=lambda: now.wall),
    )
    return now


@pytest.mark.parametrize("wall_shift", [-3600, 3600])
def test_state_waits_for_elapsed_timeout(clock, wall_shift):
    breaker = resilience.CircuitBreaker(failure_threshold=1, reset_timeout=10)
    breaker.record_failure()
    clock.wall += wall_shift
    assert breaker.state == "open"
    clock.elapsed += 10
    assert breaker.state == "half-open"


@pytest.mark.parametrize("wall_shift", [-3600, 3600])
def test_protected_call_waits_for_elapsed_timeout(clock, wall_shift):
    breaker = resilience.CircuitBreaker(failure_threshold=1, reset_timeout=10)
    calls = []

    @breaker
    def operation():
        calls.append(1)
        return "recovered"

    breaker.record_failure()
    clock.wall += wall_shift
    with pytest.raises(resilience.CircuitBreaker.CircuitBreakerOpen):
        operation()
    assert calls == []
    clock.elapsed += 10
    assert operation() == "recovered"
    assert breaker.state == "closed"


@pytest.mark.parametrize("wall_shift", [-3600, 3600])
def test_failure_window_expires_by_elapsed_time(clock, wall_shift):
    breaker = resilience.CircuitBreaker(failure_threshold=2, reset_timeout=10)
    breaker.record_failure()
    clock.wall += wall_shift
    clock.elapsed += 10
    breaker.record_failure()
    assert breaker.state == "closed"
    breaker.record_failure()
    assert breaker.state == "open"
