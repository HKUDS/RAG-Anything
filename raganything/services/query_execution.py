"""Immutable, content-free execution scope for an interactive query."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Iterator, Mapping
from dataclasses import dataclass
from typing import TypeVar


_Result = TypeVar("_Result")


@dataclass(frozen=True)
class QueryExecutionScope(Mapping[str, object]):
    trace_id: str
    workspace: str
    corpus_revision: str
    permission_scope: str
    settings_fingerprint: str
    llm_profile_fingerprint: str
    deadline_monotonic: float

    def _values(self) -> dict[str, object]:
        return {
            "trace_id": self.trace_id,
            "workspace": self.workspace,
            "corpus_revision": self.corpus_revision,
            "permission_scope": self.permission_scope,
            "settings_fingerprint": self.settings_fingerprint,
            "llm_profile_fingerprint": self.llm_profile_fingerprint,
            "deadline_monotonic": self.deadline_monotonic,
        }

    def __getitem__(self, key: str) -> object:
        return self._values()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values())

    def __len__(self) -> int:
        return 7


async def await_before_deadline(
    awaitable: Awaitable[_Result],
    deadline_monotonic: float | None,
    *,
    cancel_on_timeout: bool = True,
) -> _Result:
    """Wait only for the request budget; optionally detach shared work."""
    if deadline_monotonic is None:
        return await awaitable
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        if isinstance(awaitable, asyncio.Future) and cancel_on_timeout:
            awaitable.cancel()
            awaitable.add_done_callback(_consume_detached_result)
        elif isinstance(awaitable, asyncio.Future):
            awaitable.add_done_callback(_consume_detached_result)
        elif hasattr(awaitable, "close"):
            awaitable.close()
        raise TimeoutError("retrieval deadline expired")
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=remaining)
    except asyncio.CancelledError:
        if cancel_on_timeout:
            task.cancel()
        task.add_done_callback(_consume_detached_result)
        raise
    if task not in done:
        if cancel_on_timeout:
            task.cancel()
        task.add_done_callback(_consume_detached_result)
        raise TimeoutError("retrieval deadline expired")
    return task.result()


def _consume_detached_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        pass
