# -*- coding: utf-8 -*-
"""
Doubao Vision Embedding Adapter.

Layer: Infrastructure
Primary Responsibility: Calls the doubao-embedding-vision multimodal API,
    auto-detects embedding dimension, preprocesses images, and validates
    returned vectors.
Key Dependencies: httpx, numpy, PIL

The doubao API endpoint is NOT OpenAI-compatible. It uses:
- URL: ``POST /api/v3/embeddings/multimodal`` (not ``/v1/embeddings``)
- Input: multimodal dicts ``[{type, text/image_url}, ...]`` (not plain strings)

This module provides a custom adapter that conforms to the LightRAG
``EmbeddingFunc`` calling convention so it can be used as a drop-in
embedding function for NanoVectorDB.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────
_DEFAULT_HOST = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_MODEL = "doubao-embedding-vision-251215"
# NanoVectorDB stores vectors as float32 internally (dbs.py line 25),
# so we always return float32 regardless of what the API provides.
_DEFAULT_TIMEOUT = 60.0  # seconds — vision embeddings can be slow
# Image preprocessing limits (from ImageModalProcessor + doubao docs)
_MAX_LONG_EDGE = 2048  # px — balance quality vs token cost
_MIN_DIM = 10  # px
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Dimension Discovery ─────────────────────────────────────

def _dim_cache_path(working_dir: str) -> str:
    return os.path.join(working_dir, ".vision_embed_meta.json")


def _read_cached_dim(working_dir: str) -> tuple[Optional[int], Optional[str]]:
    """Return (dim, model) from cache or (None, None)."""
    path = _dim_cache_path(working_dir)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("dim"), data.get("model")
        except Exception:
            pass
    return None, None


def _write_cached_dim(working_dir: str, dim: int, model: str) -> None:
    """Persist discovered dimension atomically."""
    path = _dim_cache_path(working_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"dim": dim, "model": model, "updated": time.time()}, f)
    os.replace(tmp, path)


# ── Image Preprocessing ─────────────────────────────────────

def _preprocess_image(image_path: str, max_long_edge: int = _MAX_LONG_EDGE) -> tuple[str, dict]:
    """Resize and encode an image for the doubao embedding API.

    Returns ``(data_uri, metadata)`` where *data_uri* is a base64 data URI
    and *metadata* records original/processed dimensions.
    """
    with open(image_path, "rb") as f:
        raw = f.read()
    original_size = len(raw)
    return _preprocess_from_bytes(raw, original_size, max_long_edge)


def _preprocess_image_bytes(image_bytes: bytes, max_long_edge: int = _MAX_LONG_EDGE) -> tuple[str, dict]:
    """Resize and encode raw image bytes for the doubao embedding API.

    Returns ``(data_uri, metadata)``.
    """
    original_size = len(image_bytes)
    return _preprocess_from_bytes(image_bytes, original_size, max_long_edge)


def _preprocess_from_bytes(raw: bytes, original_size: int, max_long_edge: int = _MAX_LONG_EDGE) -> tuple[str, dict]:
    """Core preprocessing logic shared by file-path and in-memory entry points."""
    from PIL import Image as PILImage

    img = PILImage.open(io.BytesIO(raw))
    original_dims = img.size

    # Convert to RGB (drop alpha, handle CMYK/P)
    if img.mode in ("RGBA", "P", "CMYK"):
        img = img.convert("RGB")

    # Resize if long edge exceeds max
    w, h = img.size
    if max(w, h) > max_long_edge:
        ratio = max_long_edge / max(w, h)
        new_size = (max(_MIN_DIM, int(w * ratio)), max(_MIN_DIM, int(h * ratio)))
        img = img.resize(new_size, PILImage.LANCZOS)

    # Encode to JPEG (universally supported by vision models)
    quality = 85
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    processed = buf.getvalue()

    # Iterative quality reduction if over size limit
    while len(processed) > _MAX_FILE_BYTES and quality > 20:
        quality -= 15
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        processed = buf.getvalue()

    b64 = base64.b64encode(processed).decode("ascii")
    data_uri = f"data:image/jpeg;base64,{b64}"

    metadata = {
        "original_size": original_size,
        "processed_size": len(processed),
        "width_before": original_dims[0],
        "height_before": original_dims[1],
        "width_after": img.size[0],
        "height_after": img.size[1],
        "quality": quality,
    }
    return data_uri, metadata


# ── Vector Validation ───────────────────────────────────────

def _validate_embedding(vector: np.ndarray, context: str = "") -> bool:
    """Check for NaN, Inf, zero-norm. Returns True if valid.

    A single NaN in NanoVectorDB would corrupt all subsequent
    ``np.dot(matrix, query)`` queries — they'd all return NaN.
    """
    if vector.size == 0:
        logger.warning("[vision-embed] Empty vector %s", context)
        return False
    if np.any(np.isnan(vector)):
        logger.warning("[vision-embed] NaN detected in vector %s", context)
        return False
    if np.any(np.isinf(vector)):
        logger.warning("[vision-embed] Inf detected in vector %s", context)
        return False
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        logger.warning("[vision-embed] Zero-norm vector %s", context)
        return False
    # Log suspiciously large magnitudes (typical range is 0.5–20)
    if norm > 100.0:
        logger.warning(
            "[vision-embed] Large magnitude %.2f %s — possible model anomaly",
            norm, context,
        )
    return True


# ── Main Adapter ─────────────────────────────────────────────

class DoubaoEmbeddingAdapter:
    """Multimodal embedding adapter for doubao-embedding-vision.

    Conforms to the calling convention expected by LightRAG's
    ``EmbeddingFunc``: ``func(texts: list[str]) -> list[list[float]]``.

    Image entries are detected by a ``[VISION_EMBED:base64_data_uri]``
    marker prefix in the text string. Pure text entries are embedded
    as ``{"type": "text", ...}``.

    Usage::

        adapter = DoubaoEmbeddingAdapter(
            api_key="...", model="doubao-embedding-vision-251215",
        )
        await adapter.discover_dimension()
        vectors = await adapter(["hello world", vision_marker_string])
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_HOST,
        model: str = _DEFAULT_MODEL,
        dimension: int = 0,
        timeout: float = _DEFAULT_TIMEOUT,
        max_concurrent: int = 2,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._dim = dimension  # 0 = not yet discovered
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._total_calls = 0
        self._total_failures = 0

    # ── Dimension management ─────────────────────────────

    @property
    def dim(self) -> int:
        """Current embedding dimension (0 if not yet discovered)."""
        return self._dim

    @property
    def embedding_dim(self) -> int:
        """Alias for compatibility with EmbeddingFunc.embedding_dim."""
        return self._dim

    async def discover_dimension(self) -> int:
        """Probe the API to discover the native embedding dimension.

        Sends a minimal text probe and measures the returned vector length.
        Caches the result in ``{working_dir}/.vision_embed_meta.json``.
        """
        if self._dim > 0:
            return self._dim

        try:
            vector = await self._call_api(
                [{"type": "text", "text": "dimension probe"}]
            )
            self._dim = len(vector[0])
            logger.info(
                "[vision-embed] Discovered dimension=%d for model=%s",
                self._dim, self.model,
            )
            return self._dim
        except Exception as e:
            logger.error(
                "[vision-embed] Dimension discovery failed: %s. "
                "Set VISION_EMBEDDING_DIM env var to skip auto-detection.",
                e,
            )
            raise

    # ── Main entry point (EmbeddingFunc-compatible) ──────

    async def __call__(
        self, texts: list[str], model: str = "", **kwargs
    ) -> list[list[float]]:
        """Embed a batch of text/image entries.

        Args:
            texts: List of strings. Entries prefixed with
                ``[VISION_EMBED:data:image/...]`` are treated as images;
                all others are plain text.
            model: Ignored (kept for EmbeddingFunc compatibility).

        Returns:
            List of embedding vectors (one per input).
        """
        return await self.embed(texts, **kwargs)

    async def embed(
        self, texts: list[str], dimension: Optional[int] = None, **kwargs
    ) -> list[list[float]]:
        """Embed a batch — detects image markers and builds multimodal input."""
        if not texts:
            return []

        multimodal_input = self._build_multimodal_input(texts)
        if not multimodal_input:
            return []

        dim = dimension or self._dim or 0
        return await self._call_api(multimodal_input, dimension=dim)

    async def embed_image(
        self, image_path: str, caption_text: str = ""
    ) -> Optional[np.ndarray]:
        """Embed a single image file, optionally with caption text.

        Returns a float32 numpy array of shape (dim,), or None on failure.
        """
        try:
            data_uri, _meta = _preprocess_image(image_path)
        except Exception as e:
            logger.warning(
                "[vision-embed] Image preprocessing failed for %s: %s",
                image_path, e,
            )
            return None
        return await self._embed_from_data_uri(
            data_uri, caption_text, label=os.path.basename(image_path)
        )

    async def embed_image_bytes(
        self, image_bytes: bytes, caption_text: str = "", label: str = "query_image"
    ) -> Optional[np.ndarray]:
        """Embed raw image bytes (for query-time images from chat uploads).

        Unlike ``embed_image`` which reads from a file path, this method
        preprocesses raw bytes in-memory — no temp file needed.

        Args:
            image_bytes: Raw image bytes (JPEG/PNG/WebP/…).
            caption_text: Optional text description (e.g. user's question).
            label: Human-readable label for log messages.

        Returns:
            Float32 numpy array of shape (dim,), L2-normalized, or None on failure.
        """
        try:
            data_uri, _meta = _preprocess_image_bytes(image_bytes)
        except Exception as e:
            logger.warning(
                "[vision-embed] In-memory preprocessing failed for %s: %s",
                label, e,
            )
            return None
        return await self._embed_from_data_uri(
            data_uri, caption_text, label=label
        )

    async def _embed_from_data_uri(
        self, data_uri: str, caption_text: str = "", label: str = "image"
    ) -> Optional[np.ndarray]:
        """Internal: embed from a precomputed data URI."""
        # Build multimodal input: caption text (if any) + image
        items = []
        if caption_text:
            items.append({"type": "text", "text": caption_text[:2000]})
        items.append({"type": "image_url", "image_url": {"url": data_uri}})

        try:
            vectors = await self._call_api(items)
            if vectors:
                vec = np.array(vectors[0], dtype=np.float32)
                if _validate_embedding(vec, f"image={label}"):
                    # L2-normalize for cosine-via-dot-product
                    norm = float(np.linalg.norm(vec))
                    if abs(norm - 1.0) > 1e-5:
                        vec = vec / norm
                    return vec
            return None
        except Exception as e:
            logger.warning(
                "[vision-embed] API call failed for %s: %s",
                label, e,
            )
            return None

    # ── Internal helpers ────────────────────────────────

    _VISION_MARKER = "[VISION_EMBED:"

    @classmethod
    def make_vision_marker(cls, data_uri: str) -> str:
        """Wrap a base64 data URI so the adapter recognises it as an image entry."""
        return f"{cls._VISION_MARKER}{data_uri}]"

    @classmethod
    def is_vision_marker(cls, text: str) -> bool:
        return text.startswith(cls._VISION_MARKER)

    def _build_multimodal_input(self, texts: list[str]) -> list[dict]:
        """Convert a string list to doubao multimodal dicts."""
        items: list[dict] = []
        for text in texts:
            if self.is_vision_marker(text):
                # Extract base64 data URI from marker
                inner = text[len(self._VISION_MARKER):].rstrip("]")
                items.append({
                    "type": "image_url",
                    "image_url": {"url": inner},
                })
            elif text.strip():
                items.append({"type": "text", "text": text[:8000]})
            else:
                items.append({"type": "text", "text": " "})  # API rejects empty
        return items

    async def _call_api(
        self, multimodal_input: list[dict], dimension: int = 0
    ) -> list[list[float]]:
        """POST to the doubao multimodal embedding endpoint.

        Gate: single-file concurrency through self._semaphore.
        """
        import httpx

        async with self._semaphore:
            body: dict = {"model": self.model, "input": multimodal_input}
            if dimension > 0:
                body["dimensions"] = dimension

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings/multimodal",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                self._total_calls += 1
                if not resp.is_success:
                    self._total_failures += 1
                    resp.raise_for_status()

                data = resp.json()
                # Log token usage for cost tracking
                usage = data.get("usage", {})
                if usage:
                    details = usage.get("prompt_tokens_details", {})
                    logger.debug(
                        "[vision-embed] call=%d text_tokens=%s image_tokens=%s",
                        self._total_calls,
                        details.get("text_tokens", "?"),
                        details.get("image_tokens", "?"),
                    )

                # The doubao API returns data as a dict: {"embedding": [...]}
                # (not a list of dicts like OpenAI). Wrap in a list for
                # compatibility with the EmbeddingFunc calling convention.
                result = data["data"]
                if isinstance(result, list):
                    return [item["embedding"] for item in result]
                elif isinstance(result, dict):
                    return [result["embedding"]]
                else:
                    raise ValueError(f"Unexpected data format: {type(result)}")

    # ── Stats ──────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return {
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "dimension": self._dim,
            "model": self.model,
        }


# ── Factory ──────────────────────────────────────────────────

def create_vision_embed_func(
    working_dir: str = "./rag_storage",
) -> Optional[DoubaoEmbeddingAdapter]:
    """Create a :class:`DoubaoEmbeddingAdapter` from environment variables.

    Returns ``None`` when ``VISION_EMBEDDING_MODEL`` is not configured,
    signaling to the rest of the system that vision embedding is disabled.
    """
    model = os.getenv("VISION_EMBEDDING_MODEL", "")
    if not model:
        return None

    api_key = os.getenv("VISION_EMBEDDING_API_KEY", "")
    if not api_key:
        logger.warning(
            "[vision-embed] VISION_EMBEDDING_MODEL=%s is set but "
            "VISION_EMBEDDING_API_KEY is missing. "
            "Vision embedding disabled. "
            "Get your API key from https://console.volcengine.com/ark",
            model,
        )
        return None

    host = os.getenv("VISION_EMBEDDING_HOST", _DEFAULT_HOST)
    dim = int(os.getenv("VISION_EMBEDDING_DIM", "0"))
    max_async = int(os.getenv("VISION_EMBEDDING_MAX_ASYNC", "4"))

    # Check disk cache first
    if dim <= 0:
        cached_dim, cached_model = _read_cached_dim(working_dir)
        if cached_dim and cached_model == model:
            dim = cached_dim
            logger.info(
                "[vision-embed] Using cached dimension=%d for model=%s",
                dim, model,
            )

    adapter = DoubaoEmbeddingAdapter(
        api_key=api_key,
        base_url=host,
        model=model,
        dimension=dim,
        max_concurrent=max_async,
    )
    logger.info(
        "[vision-embed] Created adapter model=%s host=%s dim=%d",
        model, host, dim,
    )
    return adapter


__all__ = [
    "DoubaoEmbeddingAdapter",
    "create_vision_embed_func",
    "_preprocess_image",
    "_preprocess_image_bytes",
    "_validate_embedding",
]
