"""Late results must not override a newer circuit-breaker recovery cycle."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import raganything.resilience as resilience_module
from raganything.resilience import CircuitBreaker


@pytest.mark.parametrize("state", ["open", "half-open", "closed"])
@pytest.mark.parametrize("fails", [False, True])
def test_late_sync_result_preserves_recovery_cycle(monkeypatch, state, fails):
    now = [1000.0]
    monkeypatch.setattr(resilience_module.time, "time", lambda: now[0])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=60)
    started = threading.Event()
    release = threading.Event()
    probe_started = threading.Event()
    probe_release = threading.Event()

    @breaker
    def older():
        started.set()
        assert release.wait(5)
        if fails:
            raise ConnectionError("old failure")
        return "old result"

    @breaker
    def fail():
        raise ConnectionError("opens circuit")

    @breaker
    def probe():
        probe_started.set()
        assert probe_release.wait(5)
        return "recovered"

    with ThreadPoolExecutor(max_workers=2) as executor:
        old = executor.submit(older)
        recovery = None
        try:
            assert started.wait(5)
            with pytest.raises(ConnectionError, match="opens circuit"):
                fail()
            if state != "open":
                now[0] += 61
                recovery = executor.submit(probe)
                assert probe_started.wait(5)
                if state == "closed":
                    probe_release.set()
                    assert recovery.result(timeout=5) == "recovered"
            release.set()
            if fails:
                with pytest.raises(ConnectionError, match="old failure"):
                    old.result(timeout=5)
            else:
                assert old.result(timeout=5) == "old result"
            assert breaker.state == state
            if state != "closed":
                with pytest.raises(CircuitBreaker.CircuitBreakerOpen):
                    breaker(lambda: "must not execute")()
        finally:
            release.set()
            probe_release.set()
        if recovery is not None:
            assert recovery.result(timeout=5) == "recovered"
            assert breaker.state == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["open", "half-open", "closed"])
@pytest.mark.parametrize("fails", [False, True])
async def test_late_async_result_preserves_recovery_cycle(monkeypatch, state, fails):
    now = [1000.0]
    monkeypatch.setattr(resilience_module.time, "time", lambda: now[0])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=60)
    started = asyncio.Event()
    release = asyncio.Event()
    probe_started = asyncio.Event()
    probe_release = asyncio.Event()

    @breaker.async_call
    async def older():
        started.set()
        await release.wait()
        if fails:
            raise ConnectionError("old failure")
        return "old result"

    @breaker.async_call
    async def fail():
        raise ConnectionError("opens circuit")

    @breaker.async_call
    async def probe():
        probe_started.set()
        await probe_release.wait()
        return "recovered"

    old = asyncio.create_task(older())
    recovery = None
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(ConnectionError, match="opens circuit"):
            await fail()
        if state != "open":
            now[0] += 61
            recovery = asyncio.create_task(probe())
            await asyncio.wait_for(probe_started.wait(), timeout=5)
            if state == "closed":
                probe_release.set()
                assert await asyncio.wait_for(recovery, timeout=5) == "recovered"
        release.set()
        if fails:
            with pytest.raises(ConnectionError, match="old failure"):
                await asyncio.wait_for(old, timeout=5)
        else:
            assert await asyncio.wait_for(old, timeout=5) == "old result"
        assert breaker.state == state
        if state != "closed":
            with pytest.raises(CircuitBreaker.CircuitBreakerOpen):
                await probe()
    finally:
        release.set()
        probe_release.set()
        await asyncio.gather(
            old, *([recovery] if recovery else []), return_exceptions=True
        )
    if recovery is not None:
        assert recovery.result() == "recovered"
        assert breaker.state == "closed"
