"""Operation-local context for document ingestion on shared modal processors."""

from contextvars import ContextVar
from functools import wraps
from typing import Any


_sources: ContextVar[dict[int, tuple[Any, str]] | None] = ContextVar(
    "raganything_document_context", default=None
)


def document_context(func):
    """Isolate context setters for one ingestion, including its child tasks."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        token = _sources.set({})
        try:
            return await func(*args, **kwargs)
        finally:
            _sources.reset(token)

    return wrapper


def set_document_source(processor, content_source: Any, content_format: str) -> bool:
    """Set a local override, or return False for direct processor usage."""
    sources = _sources.get()
    if sources is None:
        return False
    # Child tasks inherit snapshots. Never mutate an inherited mapping.
    _sources.set({**sources, id(processor): (content_source, content_format)})
    return True


def get_document_source(processor) -> tuple[Any, str] | None:
    sources = _sources.get()
    return sources.get(id(processor)) if sources is not None else None
