"""
RAG-Anything Query Sub-Package.

Provides query pipeline and query utilities.
Conversation management has been migrated to PostgreSQL (pg_agent_repo.py).
"""

from .pipeline import QueryMixin
from .utils import (
    DEGRADED_CONTEXT_HINT,
    rerank_chunks,
    rewrite_query,
)

__all__ = [
    "DEGRADED_CONTEXT_HINT",
    "QueryMixin",
    "rerank_chunks",
    "rewrite_query",
]
