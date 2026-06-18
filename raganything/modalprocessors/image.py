# -*- coding: utf-8 -*-
"""
Image Modal Processor.

Layer: Core
Primary Responsibility: ImageModalProcessor — VLM-based image analysis,
    caption generation, entity extraction. Includes image skippability check
    (tiny/decorative images) and base64 encoding.
Key Dependencies: lightrag (LightRAG, compute_mdhash_id), PIL, raganything.prompt (PROMPTS)
"""

import json
import base64
from typing import Dict, Any, Tuple
from pathlib import Path

from lightrag.utils import logger, compute_mdhash_id
from lightrag.lightrag import LightRAG

from raganything.modalprocessors.base import BaseModalProcessor
from raganything.modalprocessors.context import ContextExtractor
from raganything.prompt import PROMPTS


class ImageModalProcessor(BaseModalProcessor):
    """Processor specialized for image content"""

    def __init__(
        self,
        lightrag: LightRAG,
        modal_caption_func,
        context_extractor: ContextExtractor = None,
    ):
        """Initialize image processor

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating descriptions (supporting image understanding)
            context_extractor: Context extractor instance
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)

    # Minimum image dimension in pixels; any side smaller → skip VLM call.
    _MIN_IMAGE_DIM = 14
    # Maximum aspect ratio (w/h or h/w); beyond this → likely a line/separator.
    _MAX_ASPECT_RATIO = 50
    # Fewer unique colors → solid/decorative fill, not meaningful content.
    _MIN_UNIQUE_COLORS = 5

    def _check_image_skippable(self, image_path: "Path") -> tuple:
        """Return (reason, label) if the image should skip the VLM, else None.

        Checks (cheapest first): file size → dimensions → aspect ratio → colors.
        """
        import os as _os
        try:
            file_size = _os.path.getsize(str(image_path))
            if file_size < 100:
                return (f"file_too_small_{file_size}B", "Decorative placeholder")
        except OSError:
            return ("unreadable_file", "Unreadable file")

        try:
            from PIL import Image as PILImage
            with PILImage.open(str(image_path)) as img:
                w, h = img.size
                if w < self._MIN_IMAGE_DIM or h < self._MIN_IMAGE_DIM:
                    return (f"too_small_{w}x{h}px", "Decorative element")
                ratio = max(w / max(h, 1), h / max(w, 1))
                if ratio > self._MAX_ASPECT_RATIO:
                    return (f"extreme_aspect_{w}x{h}px", "Separator line")
                try:
                    rgb = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                    colors = rgb.getcolors(maxcolors=self._MIN_UNIQUE_COLORS)
                    if colors is not None and len(colors) < self._MIN_UNIQUE_COLORS:
                        return (
                            f"near_solid_{len(colors)}_colors",
                            "Solid decorative fill",
                        )
                except Exception:
                    pass  # color check is best-effort
        except Exception:
            pass  # if PIL can't open it, let the normal path handle the error

        return None  # not skippable — proceed to VLM

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode image to base64"""
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            return encoded_string
        except Exception as e:
            logger.error(f"Failed to encode image {image_path}: {e}")
            return ""

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate image description and entity info only, without entity relation extraction.
        Used for batch processing stage 1.

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
                        f"{caption_text} (image)" if caption_text
                        else f"decorative_{image_path_obj.stem} (image)"
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

            # Extract context for current item
            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)

            # Build detailed visual analysis prompt with context
            if context:
                vision_prompt = PROMPTS.get(
                    "vision_prompt_with_context", PROMPTS["vision_prompt"]
                ).format(
                    context=context,
                    section_path=section_path if section_path else "None",
                    entity_name=entity_name
                    if entity_name
                    else "unique descriptive name for this image",
                    image_path=image_path,
                    captions=captions if captions else "None",
                    footnotes=footnotes if footnotes else "None",
                )
            else:
                vision_prompt = PROMPTS["vision_prompt"].format(
                    section_path=section_path if section_path else "None",
                    entity_name=entity_name
                    if entity_name
                    else "unique descriptive name for this image",
                    image_path=image_path,
                    captions=captions if captions else "None",
                    footnotes=footnotes if footnotes else "None",
                )

            # Encode image to base64
            image_base64 = self._encode_image_to_base64(image_path)
            if not image_base64:
                raise RuntimeError(f"Failed to encode image to base64: {image_path}")

            # Call vision model with encoded image
            response = await self.modal_caption_func(
                vision_prompt,
                image_data=image_base64,
                system_prompt=PROMPTS["IMAGE_ANALYSIS_SYSTEM"],
            )

            # Parse response (reuse existing logic)
            enhanced_caption, entity_info = self._parse_response(response, entity_name)

            return enhanced_caption, entity_info

        except Exception as e:
            logger.error(f"Error generating image description: {e}")
            # Fallback processing
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"image_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "image",
                "summary": f"Image content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

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
                modal_content, content_type, item_info, entity_name
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
                else f"image_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "image",
                "summary": f"Image content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    def _parse_response(
        self, response: str, entity_name: str = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Parse model response"""
        try:
            return self._parse_typed_response(response, entity_name, "image")
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
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


__all__ = ["ImageModalProcessor"]
