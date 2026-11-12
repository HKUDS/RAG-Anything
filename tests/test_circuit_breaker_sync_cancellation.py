"""Interrupted synchronous probes must not permanently block recovery."""

import asyncio

import pytest

from raganything import CircuitBreaker


def test_sync_probe_releases_slot_after_cancelled_asyncio_run():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0)
    breaker.record_failure()

    async def cancelled_request():
        task = asyncio.current_task()
        asyncio.get_running_loop().call_soon(task.cancel)
        await asyncio.sleep(10)

    @breaker
    def request():
        return asyncio.run(cancelled_request())

    with pytest.raises(asyncio.CancelledError):
        request()

    assert breaker.state == "half-open"
    assert breaker(lambda: "recovered")() == "recovered"
    assert breaker.state == "closed"


def test_sync_probe_releases_slot_after_keyboard_interrupt():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0)
    breaker.record_failure()
    interruption = KeyboardInterrupt("request interrupted")

    @breaker
    def request():
        raise interruption

    with pytest.raises(KeyboardInterrupt) as caught:
        request()

    assert caught.value is interruption
    assert breaker.state == "half-open"
    assert breaker(lambda: "recovered")() == "recovered"
    assert breaker.state == "closed"
