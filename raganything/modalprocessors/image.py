# -*- coding: utf-8 -*-
"""
Image Modal Processor.

Layer: Core
Primary Responsibility: ImageModalProcessor — VLM-based image analysis,
    caption generation, entity extraction. Includes image skippability check
    (tiny/decorative images) and base64 encoding.
Key Dependencies: lightrag (LightRAG, compute_mdhash_id), PIL, raganything.prompt (PROMPTS)
"""

import asyncio
import hashlib
import json
import os
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

from lightrag.utils import logger, compute_mdhash_id
from lightrag.lightrag import LightRAG

from raganything.modalprocessors.base import BaseModalProcessor
from raganything.modalprocessors.context import ContextExtractor
from raganything.prompt import PROMPTS
from raganything.prompts_zh import PROMPTS_ZH
from raganything.utils._image import encode_image_to_base64, image_mime_type


# ── Image type classification constants ──────────────────────
# Lightweight heuristics for routing images to type-specific VLM prompts
_IMAGE_TYPE_PROMPTS = {
    "chart": "vision_prompt_chart",       # bar/line/pie charts, data viz
    "diagram": "vision_prompt_diagram",   # flowcharts, architecture, block diagrams
    "photo": "vision_prompt",             # natural photographs (default prompt)
    "screenshot": "vision_prompt_screenshot",  # UI screenshots, app interfaces
    "table_image": "vision_prompt_table_image",  # images that are actually tables
}

# Vision embedding cache: {sha256_hex → np.ndarray}
# Module-level for cross-document reuse within the same process lifetime.
_vision_embed_cache: dict[str, "np.ndarray"] = {}
_VISION_CACHE_MAX_SIZE = int(os.getenv("VISION_EMBED_CACHE_SIZE", "5000"))
_IMAGE_PROMPT_VERSION = "image-description-zh-v2"


def _image_prompt_language() -> str:
    """Return the language used by future image descriptions."""
    value = os.getenv("MULTIMODAL_PROMPT_LANGUAGE", "zh")
    normalized = str(value or "zh").strip().lower().replace("_", "-")
    return "zh" if normalized in {"zh", "zh-cn", "cmn"} else "en"


def _image_prompt_registry() -> Any:
    return PROMPTS_ZH if _image_prompt_language() == "zh" else PROMPTS


def _vlm_cache_key(
    image_hash: str,
    rendered_prompt: str,
    system_prompt: str,
) -> str:
    """Separate cached descriptions by language and prompt-relevant context."""
    cache_context = {
        "version": _IMAGE_PROMPT_VERSION,
        "language": _image_prompt_language(),
        "vision_model": os.getenv("VISION_MODEL", ""),
        "image_hash": image_hash,
        "rendered_prompt": rendered_prompt,
        "system_prompt": system_prompt,
    }
    encoded = json.dumps(cache_context, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ImageModalProcessor(BaseModalProcessor):
    """Processor specialized for image content"""

    # ── Image dedup cache (content hash → VLM result) ──────
    _vlm_result_cache: dict[str, tuple[str, dict]] = {}
    _VLM_CACHE_MAX = int(os.getenv("IMAGE_VLM_CACHE_SIZE", "2000"))

    def __init__(
        self,
        lightrag: LightRAG,
        modal_caption_func,
        context_extractor: ContextExtractor = None,
        vision_embed_func=None,
    ):
        """Initialize image processor

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating descriptions (supporting image understanding)
            context_extractor: Context extractor instance
            vision_embed_func: Optional DoubaoEmbeddingAdapter for vision embeddings.
                When None (default), vision embedding is disabled.
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)
        self.vision_embed_func = vision_embed_func
        # Track pending vision embedding tasks for reliable completion
        self._pending_vision_tasks: list[asyncio.Task] = []
        self._vision_stats = {
            "scheduled": 0,
            "attempted": 0,
            "stored": 0,
            "auth_disabled": 0,
            "failed": 0,
            "content_blocked": 0,
            "invalid_response": 0,
        }

    def _record_vision_stat(self, name: str, amount: int = 1) -> None:
        stats = getattr(self, "_vision_stats", None)
        if not isinstance(stats, dict):
            stats = {}
            self._vision_stats = stats
        stats[name] = int(stats.get(name, 0) or 0) + amount

    # Minimum image dimension in pixels; any side smaller → skip VLM call.
    _MIN_IMAGE_DIM = 14
    # Maximum aspect ratio (w/h or h/w); beyond this → likely a line/separator.
    _MAX_ASPECT_RATIO = 50
    # Fewer unique colors → solid/decorative fill, not meaningful content.
    _MIN_UNIQUE_COLORS = 5
    # Minimum dimensions for meaningful type classification
    _MIN_CLASSIFY_DIM = 50

    # ── Image content hash & dedup ──────────────────────────

    @staticmethod
    def _get_image_content_hash(image_path: "Path") -> str:
        """Full-file SHA256 for exact image dedup across documents.

        Returns hex digest string (64 chars). Uses streaming read
        to handle large images without MemoryError.
        """
        h = hashlib.sha256()
        with open(str(image_path), "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # ── Image type classification ───────────────────────────

    @staticmethod
    def _classify_image_type(image_path: "Path") -> str:
        """Lightweight image type classification for prompt routing.

        Returns one of: "chart", "diagram", "photo", "screenshot",
        "table_image", or "photo" (fallback).

        Uses cheap heuristics (dimensions, aspect ratio, color palette)
        — no ML model needed. Goal: route to the best VLM prompt.
        """
        try:
            from PIL import Image as PILImage
            with PILImage.open(str(image_path)) as img:
                w, h = img.size
                if w < 50 or h < 50:
                    return "photo"  # too small to classify

                ratio = max(w, h) / max(min(w, h), 1)

                # Convert to RGB for color analysis
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")

                # Sample colors (resize small for speed)
                small = img.resize((min(w, 200), min(h, 200)), PILImage.NEAREST)
                colors = small.getcolors(maxcolors=256)
                if not colors:
                    return "photo"

                unique_colors = len(colors)
                total_pixels = small.size[0] * small.size[1]

                # Dominant color ratio (how much the top color dominates)
                dominant_ratio = max(c[0] for c in colors) / total_pixels

                # Heuristic: screenshots have many colors + typical aspect ratios
                if 1.3 <= ratio <= 2.5 and unique_colors > 100:
                    return "screenshot"

                # Heuristic: charts/diagrams have fewer unique colors
                # and often have white/light backgrounds
                if unique_colors < 60 and dominant_ratio > 0.3:
                    # Check for table-like grid patterns (many horizontal/vertical lines)
                    return "chart"

                if unique_colors < 80 and dominant_ratio > 0.15:
                    return "diagram"

                # Heuristic: table images are often very wide or tall text-heavy images
                if ratio > 5 and unique_colors < 200:
                    return "table_image"

                return "photo"
        except Exception:
            return "photo"  # fallback

    def _check_image_skippable(self, image_path: "Path") -> tuple:
        """Return (reason, label) if the image should skip the VLM, else None.

        Checks (cheapest first): file size → dimensions → aspect ratio → colors.
        """
        import os as _os
        try:
            file_size = _os.path.getsize(str(image_path))
            if file_size < 100:
                return (f"file_too_small_{file_size}B", "装饰性占位图")
        except OSError:
            return ("unreadable_file", "无法读取的图片")

        try:
            from PIL import Image as PILImage
            with PILImage.open(str(image_path)) as img:
                w, h = img.size
                if w < self._MIN_IMAGE_DIM or h < self._MIN_IMAGE_DIM:
                    return (f"too_small_{w}x{h}px", "装饰性元素")
                ratio = max(w / max(h, 1), h / max(w, 1))
                if ratio > self._MAX_ASPECT_RATIO:
                    return (f"extreme_aspect_{w}x{h}px", "分隔线")
                try:
                    rgb = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                    colors = rgb.getcolors(maxcolors=self._MIN_UNIQUE_COLORS)
                    if colors is not None and len(colors) < self._MIN_UNIQUE_COLORS:
                        return (
                            f"near_solid_{len(colors)}_colors",
                            "纯色装饰填充",
                        )
                except Exception:
                    pass  # color check is best-effort
        except Exception:
            pass  # if PIL can't open it, let the normal path handle the error

        return None  # not skippable — proceed to VLM

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode image to base64"""
        return encode_image_to_base64(image_path)

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
        doc_id: str = None,
        file_path: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate image description and entity info only, without entity relation extraction.
        Used for batch processing stage 1.

        Includes:
        - Content-hash dedup (skip VLM if identical image already processed)
        - Image type classification for prompt routing
        - Reliable vision embedding (tracked for await on completion)
        - Vision embedding cache (reuse across documents)

        Args:
            modal_content: Image content to process
            content_type: Type of modal content ("image")
            item_info: Item information for context extraction
            entity_name: Optional predefined entity name

        Returns:
            Tuple of (enhanced_caption, entity_info)
        """
        try:
            # Parse image content (reuse existing logic)
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"description": modal_content}
            else:
                content_data = modal_content

            image_path = content_data.get("img_path")
            captions = content_data.get(
                "image_caption", content_data.get("img_caption", [])
            )
            footnotes = content_data.get(
                "image_footnote", content_data.get("img_footnote", [])
            )
            section_path = content_data.get("_section_path", "")

            # Validate image path
            if not image_path:
                raise ValueError(
                    f"No image path provided in modal_content: {modal_content}"
                )

            # Convert to Path object and check if it exists
            image_path_obj = Path(image_path)
            if not image_path_obj.exists():
                raise FileNotFoundError(f"Image file not found: {image_path}")

            # Content hash is part of the later prompt-aware cache fingerprint.
            image_hash = self._get_image_content_hash(image_path_obj)

            # Pre-filter: skip tiny/decorative images (<14px any side) before
            # wasting a VLM API call. Docx parsers often emit separator lines,
            # bullets, and other rendering artifacts as standalone images.
            skip_result = self._check_image_skippable(image_path_obj)
            if skip_result:
                skip_reason, fallback_label = skip_result
                logger.info(
                    f"Skipping VLM for image {image_path}: {skip_reason}"
                )
                caption_text = (
                    captions[0] if isinstance(captions, list) and captions
                    else str(captions) if captions else ""
                )
                fallback_entity = {
                    "entity_name": (
                        f"{caption_text}（图片）" if caption_text
                        else f"装饰性图片_{image_path_obj.stem}"
                    ),
                    "entity_type": "image",
                    "summary": (
                        fallback_label
                        + (f": {caption_text}" if caption_text else "")
                    ),
                }
                return (
                    caption_text or f"[{fallback_label}]",
                    fallback_entity,
                )

            # ── Image type classification for prompt routing ──
            image_type = self._classify_image_type(image_path_obj)
            logger.info(
                f"Image type classified as '{image_type}' for: {image_path}"
            )

            # Extract context for current item
            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)

            # ── Select type-specific prompt ──
            prompt_key = _IMAGE_TYPE_PROMPTS.get(image_type, "vision_prompt")
            # Fall back to default if type-specific prompt doesn't exist
            image_prompts = _image_prompt_registry()
            default_entity_name = (
                "为该图片生成唯一且语义明确的中文名称"
                if _image_prompt_language() == "zh"
                else "unique descriptive name for this image"
            )
            vision_prompt_template = image_prompts.get(
                prompt_key, image_prompts["vision_prompt"]
            )

            # Build detailed visual analysis prompt with context
            if context:
                vision_prompt = image_prompts.get(
                    "vision_prompt_with_context", image_prompts["vision_prompt"]
                ).format(
                    context=context,
                    section_path=section_path if section_path else "None",
                    entity_name=entity_name
                    if entity_name
                    else default_entity_name,
                    image_path=image_path,
                    captions=captions if captions else "None",
                    footnotes=footnotes if footnotes else "None",
                )
            else:
                vision_prompt = vision_prompt_template.format(
                    section_path=section_path if section_path else "None",
                    entity_name=entity_name
                    if entity_name
                    else default_entity_name,
                    image_path=image_path,
                    captions=captions if captions else "None",
                    footnotes=footnotes if footnotes else "None",
                )

            image_system_prompt = image_prompts["IMAGE_ANALYSIS_SYSTEM"]
            vlm_cache_key = _vlm_cache_key(
                image_hash, vision_prompt, image_system_prompt
            )
            cached_vlm = self._vlm_result_cache.get(vlm_cache_key)
            if cached_vlm is not None:
                logger.info(
                    f"VLM cache HIT for image {image_path} (hash={image_hash[:12]}...)"
                )
                enhanced_caption, entity_info = cached_vlm
                # Still need to schedule vision embedding for THIS document.
                await self._schedule_vision_embed(
                    image_path=image_path,
                    entity_name=entity_info.get("entity_name", ""),
                    entity_type=entity_info.get("entity_type", "image"),
                    description=enhanced_caption,
                    doc_id=doc_id,
                    file_path=file_path,
                    image_hash=image_hash,
                )
                return enhanced_caption, entity_info

            # Encode image to base64
            image_base64 = self._encode_image_to_base64(image_path)
            if not image_base64:
                raise RuntimeError(f"Failed to encode image to base64: {image_path}")

            # Call vision model with encoded image
            response = await self._call_modal_caption(
                vision_prompt,
                image_data=image_base64,
                image_mime_type=image_mime_type(image_path),
                system_prompt=image_system_prompt,
            )

            # Parse response (reuse existing logic)
            enhanced_caption, entity_info = self._parse_response(response, entity_name)

            # ── Cache VLM result for cross-document dedup ──
            if len(self._vlm_result_cache) >= self._VLM_CACHE_MAX:
                # Evict oldest entry (FIFO)
                oldest = next(iter(self._vlm_result_cache))
                del self._vlm_result_cache[oldest]
            self._vlm_result_cache[vlm_cache_key] = (enhanced_caption, entity_info)

            # ── Vision embedding (doubao-embedding-vision) ──
            # Tracked for reliable completion: all pending vision tasks are
            # awaited when the document processor calls finalize.
            await self._schedule_vision_embed(
                image_path=image_path,
                entity_name=entity_info.get("entity_name", ""),
                entity_type=entity_info.get("entity_type", "image"),
                description=enhanced_caption,
                doc_id=doc_id,
                file_path=file_path,
                image_hash=image_hash,
            )

            return enhanced_caption, entity_info

        except Exception as e:
            message = str(e).lower()
            if "data_inspection_failed" in message or "inappropriate content" in message:
                self._record_vision_stat("content_blocked")
            elif "missing required" in message or "json" in message:
                self._record_vision_stat("invalid_response")
            logger.error(f"Error generating image description: {e}")
            # Fallback processing
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"图片_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "image",
                "summary": f"图片内容：{str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    async def _schedule_vision_embed(
        self,
        image_path: str,
        entity_name: str,
        entity_type: str = "image",
        description: str = "",
        doc_id: str = "",
        file_path: str = "",
        image_hash: str = "",
    ) -> None:
        """Schedule a tracked vision embedding task.

        Unlike the old fire-and-forget pattern, tasks are tracked in
        ``self._pending_vision_tasks`` so the document processor can
        await their completion before finalizing.
        """
        if self.vision_embed_func is None:
            return
        try:
            from raganything.processor.batch_processor import register_background_task
            self._record_vision_stat("scheduled")
            _vision_task = asyncio.create_task(
                self._compute_and_store_vision(
                    image_path=image_path,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    description=description,
                    doc_id=doc_id,
                    file_path=file_path,
                    image_hash=image_hash,
                )
            )
            _vision_task._raganything_doc_id = doc_id
            register_background_task(_vision_task)
            self._pending_vision_tasks.append(_vision_task)
            # Clean up completed tasks to prevent unbounded growth
            self._pending_vision_tasks = [
                t for t in self._pending_vision_tasks if not t.done()
            ]
            logger.info(
                "[VISION] Scheduled tracked embedding for %s (pending=%d)",
                entity_name, len(self._pending_vision_tasks),
            )
        except Exception as e:
            logger.warning(
                "[VISION] Failed to schedule embedding for %s: %s",
                entity_name, e,
            )

    async def cancel_pending_vision_tasks(self, doc_ids: set[str]) -> int:
        """Cancel unfinished embedding writes for documents being deleted."""
        if not doc_ids:
            return 0

        pending = [
            task
            for task in self._pending_vision_tasks
            if not task.done()
            and getattr(task, "_raganything_doc_id", None) in doc_ids
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        self._pending_vision_tasks = [
            task for task in self._pending_vision_tasks if not task.done()
        ]
        return len(pending)

    async def await_pending_vision_tasks(self, timeout: float = 120.0) -> int:
        """Wait for all pending vision embedding tasks to complete.

        Called by the document processor before finalizing storages.
        Returns the number of tasks that were awaited.
        """
        pending = [t for t in self._pending_vision_tasks if not t.done()]
        if not pending:
            return 0
        logger.info(
            "[VISION] Waiting for %d pending vision embedding tasks (timeout=%ds)...",
            len(pending), timeout,
        )
        done, still_pending = await asyncio.wait(pending, timeout=timeout)
        # Collect exceptions without making vision embedding fatal.
        for task in done:
            try:
                task.result()
            except Exception as exc:
                logger.warning("[VISION] Background task failed: %s", exc)

        if still_pending:
            # ``asyncio.wait`` returns pending tasks instead of raising on a
            # timeout. Leaving them untracked lets them write after storage
            # finalization, so cancel and collect them before returning.
            logger.warning(
                "[VISION] Timed out after %ds; cancelling %d pending task(s)",
                timeout,
                len(still_pending),
            )
            for task in still_pending:
                task.cancel()
            await asyncio.gather(*still_pending, return_exceptions=True)

        self._pending_vision_tasks.clear()
        stats = getattr(self, "_vision_stats", None)
        if isinstance(stats, dict):
            logger.info("[VISION] Embedding summary: %s", dict(stats))
        logger.info(
            "[VISION] Completed %d/%d vision embedding tasks",
            len(done),
            len(pending),
        )
        return len(done)

    async def process_multimodal_content(
        self,
        modal_content,
        content_type: str,
        file_path: str = "manual_creation",
        entity_name: str = None,
        item_info: Dict[str, Any] = None,
        batch_mode: bool = False,
        doc_id: str = None,
        chunk_order_index: int = 0,
    ) -> Tuple[str, Dict[str, Any]]:
        """Process image content with context support"""
        try:
            # Generate description and entity info
            enhanced_caption, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name,
                doc_id=doc_id, file_path=file_path,
            )

            # Build complete image content
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"description": modal_content}
            else:
                content_data = modal_content

            image_path = content_data.get("img_path", "")
            captions = content_data.get(
                "image_caption", content_data.get("img_caption", [])
            )
            footnotes = content_data.get(
                "image_footnote", content_data.get("img_footnote", [])
            )
            section_path = content_data.get("_section_path", "")
            neighbor_text = content_data.get("_neighbor_text", "")

            modal_chunk = PROMPTS["image_chunk"].format(
                section_path=section_path if section_path else "None",
                neighbor_text=neighbor_text if neighbor_text else "None",
                image_path=image_path,
                captions=", ".join(captions) if captions else "None",
                footnotes=", ".join(footnotes) if footnotes else "None",
                enhanced_caption=enhanced_caption,
            )

            return await self._create_entity_and_chunk(
                modal_chunk,
                entity_info,
                file_path,
                batch_mode,
                doc_id,
                chunk_order_index,
            )

        except Exception as e:
            logger.error(f"Error processing image content: {e}")
            # Fallback processing
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"图片_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "image",
                "summary": f"图片内容：{str(modal_content)[:100]}",
            }
            # ``_create_entity_and_chunk`` returns a three-tuple. Keep that
            # contract even when chunk creation itself fails so the individual
            # multimodal fallback can detect and stop on partial persistence.
            return str(modal_content), fallback_entity, []

    def _parse_response(
        self, response: str, entity_name: str = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Parse model response"""
        try:
            description, entity_info = self._parse_typed_response(
                response, entity_name, "image"
            )
            if _image_prompt_language() == "zh":
                name = str(entity_info.get("entity_name") or "")
                if name.endswith(" (image)"):
                    entity_info["entity_name"] = f"{name[:-8]}（图片）"
            return description, entity_info
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            self._record_vision_stat("invalid_response")
            logger.error(f"Error parsing image analysis response: {e}")
            logger.debug(f"Raw response: {response}")
            cleaned = self._strip_thinking_tags(response)
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"image_{compute_mdhash_id(cleaned)}",
                "entity_type": "image",
                "summary": cleaned[:100] + "..." if len(cleaned) > 100 else cleaned,
            }
            return cleaned, fallback_entity

    # ── Vision Embedding (doubao-embedding-vision) ──────────

    async def _compute_and_store_vision(
        self,
        image_path: str,
        entity_name: str,
        entity_type: str = "image",
        description: str = "",
        doc_id: str = "",
        file_path: str = "",
        image_hash: str = "",
    ) -> None:
        """Background task: compute vision embedding and store in ``image_vision_repo``.

        This runs asynchronously after VLM description generation completes.
        Failures are silently logged — vision embedding is an enhancement,
        not a requirement for document processing.

        Uses an in-memory cache (``_vision_embed_cache``) keyed by image content
        hash to avoid redundant API calls for identical images across documents.
        """
        try:
            # Gate: only if vision_embed_func and image_vision_repo are available
            if self.vision_embed_func is None:
                return
            repo = getattr(self.lightrag, 'image_vision_repo', None)
            if repo is None:
                return

            # ── Compute content hash if not provided ──
            if not image_hash:
                image_hash = self._get_image_content_hash(Path(image_path))

            # The embedding input includes the generated description, so cache
            # entries must be isolated by model and description content.
            description_digest = hashlib.sha256(
                description[:500].encode("utf-8")
            ).hexdigest()
            vision_cache_key = (
                f"{self.vision_embed_func.model}:{description_digest}:{image_hash}"
            )

            # ── Check in-memory cache first ──
            cached_vec = _vision_embed_cache.get(vision_cache_key)
            if cached_vec is not None:
                logger.info(
                    "[VISION] Cache HIT for %s (hash=%s...)",
                    entity_name, image_hash[:12],
                )
                # Store cached vector under this document's entity
                await repo.upsert(
                    image_hash=image_hash,
                    vector=cached_vec,
                    metadata={
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                        "image_path": image_path,
                        "description": description,
                        "vision_model": self.vision_embed_func.model,
                        "doc_id": doc_id,
                        "file_path": file_path,
                    },
                )
                await repo.flush()
                return

            # ── Compute fresh embedding ──
            logger.info("[VISION] Computing embedding for %s", entity_name)
            self._record_vision_stat("attempted")
            vec = await self.vision_embed_func.embed_image(
                image_path, caption_text=description[:500]
            )
            if vec is None:
                reason = getattr(self.vision_embed_func, "_disabled_reason", None)
                self._record_vision_stat(
                    "auth_disabled" if reason in {
                        "authentication_failed", "authorization_failed"
                    } else "failed"
                )
                logger.warning(
                    "[VISION] embed_image returned None for %s (reason=%s)",
                    entity_name,
                    reason or "provider_unavailable",
                )
                return  # embed_image logged the reason

            # ── Cache for cross-document reuse ──
            if len(_vision_embed_cache) >= _VISION_CACHE_MAX_SIZE:
                # Evict oldest (FIFO via dict ordering since Python 3.7)
                oldest = next(iter(_vision_embed_cache))
                del _vision_embed_cache[oldest]
            _vision_embed_cache[vision_cache_key] = vec
            self._record_vision_stat("stored")

            # ── Store in image_vision_repo ──
            await repo.upsert(
                image_hash=image_hash,
                vector=vec,
                metadata={
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "image_path": image_path,
                    "description": description,
                    "vision_model": self.vision_embed_func.model,
                    "doc_id": doc_id,
                    "file_path": file_path,
                },
            )
            await repo.flush()

            logger.info(
                "[VISION] SUCCESS: Stored embedding for %s (hash=%s)",
                entity_name, image_hash[:12],
            )
        except Exception as e:
            self._record_vision_stat("failed")
            logger.warning("[VISION] FAILED for %s: %s", image_path, e)


__all__ = ["ImageModalProcessor"]
