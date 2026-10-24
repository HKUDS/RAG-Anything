"""Operation-local context for document ingestion on shared modal processors."""

from bisect import bisect_left
from contextvars import ContextVar
from functools import wraps
from itertools import chain
from typing import Any

_sources: ContextVar[dict[int, tuple[Any, str]] | None] = ContextVar(
    "raganything_document_context", default=None
)
_page_indexes: ContextVar[dict[int, "_PageIndex"] | None] = ContextVar(
    "raganything_page_indexes", default=None
)


class _PageIndex:
    """Lazy page lookup for a source owned by one ingestion operation.

    Ingestion keeps the source's page assignments and list order stable until
    completion. Keep the original items, not formatted text, so configuration and
    tokenization still run on every extraction. Direct mutable sources are not
    registered here.
    """

    def __init__(self, source):
        self.source = source
        self.length = -1
        self.buckets = None
        self.pages = []
        self.queried = False

    def items(self, start_page, end_page):
        # A single lookup cannot amortize building an index. Keep its scan path.
        if not self.queried:
            self.queried = True
            return self.source
        if self.length != len(self.source):
            buckets = {}
            for position, item in enumerate(self.source):
                if type(item) is not dict:
                    buckets = None
                    break
                page = item.get("page_idx", 0)
                if type(page) is not int:
                    buckets = None
                    break
                buckets.setdefault(page, []).append(position)
            self.buckets = buckets
            self.pages = sorted(buckets) if buckets is not None else []
            self.length = len(self.source)
        if self.buckets is None:
            return self.source
        first = bisect_left(self.pages, start_page)
        last = bisect_left(self.pages, end_page)
        if first == 0 and last == len(self.pages):
            return self.source
        # Page order can differ from document order, including interleaved pages.
        matches = (self.buckets[page] for page in self.pages[first:last])
        return (
            self.source[position] for position in sorted(chain.from_iterable(matches))
        )


def page_context_items(content_source, start_page, end_page):
    """Select indexed candidates only for a registered ingestion source."""
    indexes = _page_indexes.get()
    if indexes is None or type(start_page) is not int or type(end_page) is not int:
        return content_source
    index = indexes.get(id(content_source))
    return index.items(start_page, end_page) if index is not None else content_source


def document_context(func):
    """Isolate context setters for one ingestion, including its child tasks."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        token = _sources.set({})
        index_token = _page_indexes.set({})
        try:
            return await func(*args, **kwargs)
        finally:
            _page_indexes.reset(index_token)
            _sources.reset(token)

    return wrapper


def set_document_source(processor, content_source: Any, content_format: str) -> bool:
    """Set a local override, or return False for direct processor usage."""
    sources = _sources.get()
    if sources is None:
        return False
    # Child tasks inherit snapshots. Never mutate an inherited mapping.
    _sources.set({**sources, id(processor): (content_source, content_format)})
    indexes = _page_indexes.get()
    if type(content_source) is list and content_format != "text_chunks":
        # The cache is shared by this operation's processors and child tasks.
        # Lookup/build is synchronous; source overrides still use copy-on-write.
        index = indexes.get(id(content_source))
        if index is None or index.length != -1:
            indexes[id(content_source)] = _PageIndex(content_source)
    return True


def get_document_source(processor) -> tuple[Any, str] | None:
    sources = _sources.get()
    return sources.get(id(processor)) if sources is not None else None
