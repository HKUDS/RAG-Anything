# -*- coding: utf-8 -*-
"""
Generic Modal Processor.

Layer: Core
Primary Responsibility: GenericModalProcessor — fallback processor for
    any modal content type not handled by specialized processors.
Key Dependencies: raganything.prompt (PROMPTS)
"""

import json
from typing import Dict, Any, Tuple

from lightrag.utils import logger, compute_mdhash_id
from lightrag.lightrag import LightRAG

from raganything.modalprocessors.base import BaseModalProcessor
from raganything.modalprocessors.context import ContextExtractor
from raganything.prompt import PROMPTS


class GenericModalProcessor(BaseModalProcessor):
    """Generic processor for other types of modal content"""

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
        Generate generic modal description and entity info only, without entity relation extraction.
        Used for batch processing stage 1.
        """
        try:
            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)

            if context:
                generic_prompt = PROMPTS.get(
                    "generic_prompt_with_context", PROMPTS["generic_prompt"]
                ).format(
                    context=context,
                    content_type=content_type,
                    entity_name=entity_name
                    if entity_name
                    else f"descriptive name for this {content_type}",
                    content=str(modal_content),
                )
            else:
                generic_prompt = PROMPTS["generic_prompt"].format(
                    content_type=content_type,
                    entity_name=entity_name
                    if entity_name
                    else f"descriptive name for this {content_type}",
                    content=str(modal_content),
                )

            response = await self.modal_caption_func(
                generic_prompt,
                system_prompt=PROMPTS["GENERIC_ANALYSIS_SYSTEM"].format(
                    content_type=content_type
                ),
            )

            enhanced_caption, entity_info = self._parse_generic_response(
                response, entity_name, content_type
            )
            return enhanced_caption, entity_info

        except Exception as e:
            logger.error(f"Error generating {content_type} description: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"{content_type}_{compute_mdhash_id(str(modal_content))}",
                "entity_type": content_type,
                "summary": f"{content_type} content: {str(modal_content)[:100]}",
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
        """Process generic modal content with context support"""
        try:
            enhanced_caption, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            # ── 图片路径保留：即使没有 ImageModalProcessor，也要在 chunk 中
            # 写入 "Image Path:" 行，确保 extract_image_paths() 能在查询时找到 ──
            image_path_line = ""
            if content_type == "image":
                if isinstance(modal_content, dict):
                    img_path = modal_content.get("img_path", "")
                elif isinstance(modal_content, str):
                    try:
                        import json as _json
                        _data = _json.loads(modal_content)
                        img_path = _data.get("img_path", "")
                    except Exception:
                        img_path = ""
                else:
                    img_path = ""
                if img_path:
                    image_path_line = f"Image Path: {img_path}\n"

            modal_chunk = PROMPTS["generic_chunk"].format(
                content_type=content_type.title(),
                content=str(modal_content),
                enhanced_caption=enhanced_caption,
            )

            # Prepend image path line before the formatted chunk
            if image_path_line:
                modal_chunk = image_path_line + modal_chunk

            return await self._create_entity_and_chunk(
                modal_chunk,
                entity_info,
                file_path,
                batch_mode,
                doc_id,
                chunk_order_index,
            )

        except Exception as e:
            logger.error(f"Error processing {content_type} content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"{content_type}_{compute_mdhash_id(str(modal_content))}",
                "entity_type": content_type,
                "summary": f"{content_type} content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    def _parse_generic_response(
        self, response: str, entity_name: str = None, content_type: str = "content"
    ) -> Tuple[str, Dict[str, Any]]:
        """Parse generic analysis response"""
        try:
            return self._parse_typed_response(response, entity_name, content_type)
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            logger.error(f"Error parsing {content_type} analysis response: {e}")
            logger.debug(f"Raw response: {response}")
            cleaned = self._strip_thinking_tags(response)
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"{content_type}_{compute_mdhash_id(cleaned)}",
                "entity_type": content_type,
                "summary": cleaned[:100] + "..." if len(cleaned) > 100 else cleaned,
            }
            return cleaned, fallback_entity


__all__ = ["GenericModalProcessor"]
