"""
RAG-Anything Processor Sub-Package.

Provides document processing mixins composited into a single ProcessorMixin.
"""

from .chunk_processor import ChunkProcessorMixin
from .doc_processor import DocProcessorMixin
from .embed_processor import EmbedProcessorMixin
from .batch_processor import (
    BatchProcessorMixin,
    get_pending_background_tasks,
    register_background_task,
)
from .multimodal_processor import MultimodalProcessorMixin


class ProcessorMixin(
    DocProcessorMixin,
    ChunkProcessorMixin,
    EmbedProcessorMixin,
    BatchProcessorMixin,
    MultimodalProcessorMixin,
):
    """Composite mixin combining all document processing functionality."""


__all__ = [
    "ProcessorMixin",
    "register_background_task",
    "get_pending_background_tasks",
]
