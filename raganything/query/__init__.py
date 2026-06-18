"""
RAG-Anything Query Sub-Package.

Provides query pipeline, conversation management, and query utilities.
"""

from .conversation import (
    ConversationContext,
    ConversationManager,
    ThreadSummary,
)
from .pipeline import QueryMixin
from .utils import (
    DEGRADED_CONTEXT_HINT,
    rerank_chunks,
    rewrite_query,
)

__all__ = [
    "ConversationContext",
    "ConversationManager",
    "DEGRADED_CONTEXT_HINT",
    "QueryMixin",
    "rerank_chunks",
    "rewrite_query",
    "ThreadSummary",
]
