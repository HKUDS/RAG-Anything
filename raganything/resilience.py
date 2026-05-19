"""
Retry and resilience utilities for RAGAnything.

Provides decorators and helpers for handling transient failures in LLM API
calls, embedding requests, and other network-dependent operations.

Addresses GitHub issue #172 — process_document_complete getting stuck due to
intermittent network errors.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from typing import Any, Callable, Optional, Sequence, Type, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Default transient exceptions that are safe to retry.
# Intentionally focused on network / upstream failures.
# Local programming errors (TypeError, ValueError, KeyError, etc.) and most
# OSError subclasses (FileNotFoundError, PermissionError, ...) should not be
# retried by default.
_DEFAULT_RETRYABLE: tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
)

try:
    import httpx

    _DEFAULT_RETRYABLE = _DEFAULT_RETRYABLE + (
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    )
except ImportError:
    pass

try:
    import openai

    _DEFAULT_RETRYABLE = _DEFAULT_RETRYABLE + (
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.RateLimitError,
        openai.InternalServerError,
    )
except ImportError:
    pass


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[Sequence[Type[BaseException]]] = None,
    on_retry: Optional[Callable[[BaseException, int, float], None]] = None,
) -> Callable[[F], F]:
    """Decorator that retries a **synchronous** function on transient failures.

    Uses exponential backoff with optional jitter to avoid thundering-herd
    problems when multiple workers hit rate limits simultaneously.

    Args:
        max_attempts: Total number of attempts (including the first call).
        base_delay: Initial delay in seconds between retries.
        max_delay: Upper-bound on the delay between retries.
        exponential_base: Multiplier applied to the delay after each retry.
        jitter: If ``True``, adds random jitter (0–50 % of computed delay).
        retryable_exceptions: Exception types that trigger a retry.
            Defaults to common network / API transient errors.
        on_retry: Optional callback ``(exception, attempt, delay)`` invoked
            before each retry sleep.

    Returns:
        The decorated function, with retry behaviour.

    Example::

        @retry(max_attempts=5, base_delay=2.0)
        def call_llm(prompt: str) -> str:
            return openai.ChatCompletion.create(...)
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if base_delay < 0 or max_delay < 0:
        raise ValueError("base_delay and max_delay must be >= 0")
    if exponential_base <= 0:
        raise ValueError("exponential_base must be > 0")

    if retryable_exceptions is None:
        retryable_exceptions = _DEFAULT_RETRYABLE

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except tuple(retryable_exceptions) as exc:
                    last_exception = exc
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__qualname__,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay,
                    )
                    if jitter:
                        import random

                        delay *= 1.0 + random.uniform(0, 0.5)
                    if on_retry is not None:
                        on_retry(exc, attempt, delay)
                    logger.warning(
                        "%s attempt %d/%d failed (%s), retrying in %.1fs…",
                        func.__qualname__,
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        delay,
                    )
                    time.sleep(delay)
            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[Sequence[Type[BaseException]]] = None,
    on_retry: Optional[Callable[[BaseException, int, float], Any]] = None,
) -> Callable[[F], F]:
    """Decorator that retries an **async** function on transient failures.

    Async counterpart of :func:`retry`.  Uses ``asyncio.sleep`` instead of
    blocking ``time.sleep``.

    Args:
        max_attempts: Total number of attempts (including the first call).
        base_delay: Initial delay in seconds between retries.
        max_delay: Upper-bound on the delay between retries.
        exponential_base: Multiplier applied to the delay after each retry.
        jitter: If ``True``, adds random jitter (0–50 % of computed delay).
        retryable_exceptions: Exception types that trigger a retry.
        on_retry: Optional async-compatible callback.

    Returns:
        The decorated async function, with retry behaviour.

    Example::

        @async_retry(max_attempts=5, base_delay=2.0)
        async def call_llm_async(prompt: str) -> str:
            return await aclient.chat.completions.create(...)
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if base_delay < 0 or max_delay < 0:
        raise ValueError("base_delay and max_delay must be >= 0")
    if exponential_base <= 0:
        raise ValueError("exponential_base must be > 0")

    if retryable_exceptions is None:
        retryable_exceptions = _DEFAULT_RETRYABLE

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except tuple(retryable_exceptions) as exc:
                    last_exception = exc
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__qualname__,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay,
                    )
                    if jitter:
                        import random

                        delay *= 1.0 + random.uniform(0, 0.5)
                    if on_retry is not None:
                        result = on_retry(exc, attempt, delay)
                        if asyncio.iscoroutine(result):
                            await result
                    logger.warning(
                        "%s attempt %d/%d failed (%s), retrying in %.1fs…",
                        func.__qualname__,
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


class CircuitBreaker:
    """Simple circuit breaker to prevent cascading failures.

    When the failure count exceeds ``failure_threshold`` within the
    ``reset_timeout`` window, the breaker *opens* and subsequent calls
    raise ``CircuitBreakerOpen`` immediately without executing the
    protected function.  After ``reset_timeout`` seconds the breaker
    enters a *half-open* state and allows one trial call through.

    Args:
        failure_threshold: Number of failures before opening the circuit.
        reset_timeout: Seconds to wait before transitioning to half-open.
        name: Human-readable name for log messages.
    """

    class CircuitBreakerOpen(Exception):
        """Raised when the circuit breaker is open."""

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        name: str = "default",
        failure_exceptions: Optional[Sequence[Type[BaseException]]] = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.name = name

        # Exceptions that are treated as upstream failures.
        # By default these mirror the retry helpers so application bugs do not
        # open the breaker unless explicitly configured to do so.
        self._failure_exceptions: tuple[Type[BaseException], ...] = tuple(
            failure_exceptions or _DEFAULT_RETRYABLE
        )

        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state: str = "closed"  # closed | open | half-open
        # Concurrency control for half-open single-flight behaviour
        self._lock = threading.Lock()
        self._trial_in_flight: bool = False

    @property
    def state(self) -> str:
        """Current circuit breaker state."""
        with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure_time >= self.reset_timeout:
                    self._state = "half-open"
            return self._state

    def record_success(self) -> None:
        """Record a successful call, resetting the breaker."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"
            self._trial_in_flight = False

    def record_failure(self) -> None:
        """Record a failed call, potentially opening the breaker."""
        with self._lock:
            now = time.time()
            if self._state == "half-open":
                # A failed half-open probe should reopen the breaker immediately.
                self._failure_count = self.failure_threshold
            else:
                # Only failures within the configured window contribute towards
                # opening the breaker. A stale failure should not count against
                # the next request burst.
                if (
                    self._last_failure_time
                    and now - self._last_failure_time >= self.reset_timeout
                ):
                    self._failure_count = 0
                self._failure_count += 1
            self._last_failure_time = now
            if self._failure_count >= self.failure_threshold:
                self._state = "open"
                self._trial_in_flight = False
                logger.warning(
                    "Circuit breaker '%s' opened after %d failures",
                    self.name,
                    self._failure_count,
                )

    def _acquire_permission(self) -> None:
        """Check and update state before executing a protected call.

        - If the breaker is open and reset_timeout has not elapsed, raise.
        - If the breaker moves to half-open, allow exactly one in-flight
          trial call and reject additional concurrent calls.
        - If the breaker is closed, allow the call.
        """
        with self._lock:
            # Transition open -> half-open if timeout has elapsed.
            if self._state == "open":
                if time.time() - self._last_failure_time >= self.reset_timeout:
                    self._state = "half-open"

            if self._state == "open":
                # Still within timeout window.
                raise self.CircuitBreakerOpen(
                    f"Circuit breaker '{self.name}' is open — call rejected"
                )

            if self._state == "half-open":
                if self._trial_in_flight:
                    # Single-flight: only one trial call is allowed.
                    raise self.CircuitBreakerOpen(
                        f"Circuit breaker '{self.name}' is half-open — trial in progress"
                    )
                # Mark that a trial call is now in-flight.
                self._trial_in_flight = True
                return

            # closed: allow call as normal.
            return

    def __call__(self, func: F) -> F:
        """Use as a decorator around sync functions."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._acquire_permission()
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except tuple(self._failure_exceptions):
                # Upstream / transient failure: contributes towards opening
                # the breaker.
                self.record_failure()
                raise
            except Exception:
                # Application bug or non-transient local error: do not treat as
                # upstream instability. We still need to clear the half-open
                # trial gate so that future calls are not permanently blocked.
                with self._lock:
                    if self._state == "half-open":
                        self._trial_in_flight = False
                raise

        return wrapper  # type: ignore[return-value]

    def async_call(self, func: F) -> F:
        """Use as a decorator around async functions."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._acquire_permission()
            try:
                result = await func(*args, **kwargs)
                self.record_success()
                return result
            except tuple(self._failure_exceptions):
                self.record_failure()
                raise
            except Exception:
                with self._lock:
                    if self._state == "half-open":
                        self._trial_in_flight = False
                raise

        return wrapper  # type: ignore[return-value]
