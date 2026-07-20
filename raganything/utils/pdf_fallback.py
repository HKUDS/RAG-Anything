"""Portable PDF media extraction used when a primary parser cannot start."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_VLM_SUPPORTED_RAW_FORMATS = {
    "GIF": ".gif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


def _save_as_png(image: Any) -> tuple[bytes, str]:
    """Convert a decoded PDF image into an unambiguous VLM-supported PNG."""
    normalized = image.copy()
    if normalized.mode not in {"RGB", "RGBA"}:
        normalized = normalized.convert("RGBA" if "transparency" in normalized.info else "RGB")
    buffer = io.BytesIO()
    normalized.save(buffer, format="PNG")
    return buffer.getvalue(), ".png"


def _normalize_pdf_image(image: Any) -> tuple[bytes, str] | None:
    """Return valid image bytes and an extension matching their real format.

    PDF image display names are not reliable: pypdf can expose JPEG2000 bytes
    through an item named ``*.png``. Keep raw bytes only for formats accepted by
    the VLM and normalize every other decoded image to PNG.
    """
    raw_data = getattr(image, "data", None)
    if isinstance(raw_data, (bytes, bytearray)) and raw_data:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(raw_data)) as decoded:
                image_format = (decoded.format or "").upper()
                suffix = _VLM_SUPPORTED_RAW_FORMATS.get(image_format)
                if suffix:
                    return bytes(raw_data), suffix
                decoded.load()
                return _save_as_png(decoded)
        except (ImportError, OSError, ValueError):
            pass

    decoded_image = getattr(image, "image", None)
    if decoded_image is None:
        return None

    try:
        return _save_as_png(decoded_image)
    except (AttributeError, OSError, ValueError):
        return None


def extract_pdf_embedded_images(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    max_images: int = 64,
) -> list[dict[str, Any]]:
    """Extract embedded PDF images into parser-compatible content items.

    This is intentionally a fallback rather than a replacement for Docling. It
    preserves actual embedded media when the native Docling PDF pipeline cannot
    initialize, so downstream multimodal processing still receives image items.
    """
    source = Path(pdf_path)
    if max_images <= 0 or not source.is_file():
        return []

    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("PDF media fallback is unavailable because pypdf is not installed")
        return []

    try:
        fingerprint = hashlib.sha256(
            f"{source.resolve()}:{source.stat().st_size}:{source.stat().st_mtime_ns}".encode("utf-8")
        ).hexdigest()[:20]
        media_dir = Path(output_dir) / "pdf_fallback_media" / fingerprint
        media_dir.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(str(source))
        items: list[dict[str, Any]] = []
        for page_idx, page in enumerate(reader.pages):
            page_images = getattr(page, "images", None)
            if page_images is None:
                continue
            try:
                image_pairs = list(page_images.items())
            except AttributeError:
                image_pairs = list(enumerate(page_images))

            for image_idx, (image_name, image) in enumerate(image_pairs):
                if len(items) >= max_images:
                    logger.warning(
                        "PDF media fallback capped at %d images for %s",
                        max_images,
                        source.name,
                    )
                    return items

                normalized = _normalize_pdf_image(image)
                if normalized is None:
                    logger.debug(
                        "Skipping PDF image without a VLM-supported representation: page=%d image=%s",
                        page_idx,
                        image_name,
                    )
                    continue

                image_data, suffix = normalized
                destination = media_dir / f"page_{page_idx + 1:04d}_image_{image_idx + 1:03d}{suffix}"
                destination.write_bytes(image_data)
                items.append(
                    {
                        "type": "image",
                        "img_path": str(destination.resolve()),
                        "image_caption": [],
                        "image_footnote": [],
                        "page_idx": page_idx,
                        "source": "pdf_embedded_image_fallback",
                    }
                )

        if items:
            logger.info("Extracted %d embedded PDF images from %s", len(items), source.name)
        return items
    except Exception as exc:
        logger.warning("PDF media fallback failed for %s: %s", source, exc)
        return []
