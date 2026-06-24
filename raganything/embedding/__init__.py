# -*- coding: utf-8 -*-
"""
RAG-Anything Embedding Package.

Provides:
- DoubaoEmbeddingAdapter — doubao-embedding-vision API client
- ImageVectorRepository — vision vector storage with atomic persistence
- EmbeddingCache — local persistent cache for text embeddings
- make_cached_embed_func — wrap an embedding function with caching
"""

from raganything.embedding.doubao_vision import DoubaoEmbeddingAdapter, create_vision_embed_func
from raganything.embedding.image_vector_repo import ImageVectorRepository
from raganything.embedding.embedding_cache import EmbeddingCache, make_cached_embed_func

__all__ = [
    "DoubaoEmbeddingAdapter",
    "ImageVectorRepository",
    "EmbeddingCache",
    "create_vision_embed_func",
    "make_cached_embed_func",
]
