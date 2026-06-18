# -*- coding: utf-8 -*-
"""
Modal Processor Context Extraction.

Layer: Core
Primary Responsibility: ContextConfig (dataclass) and ContextExtractor —
    universal context extraction for multimodal content from MinerU, text_chunks,
    dict, and plain-text content sources.
Key Dependencies: lightrag.utils (logger), stdlib (dataclasses, typing)
"""

from typing import Any, Dict, List
from dataclasses import dataclass

from lightrag.utils import logger


@dataclass
class ContextConfig:
    """Configuration for context extraction"""

    context_window: int = 1  # Window size for context extraction
    context_mode: str = "page"  # "page", "chunk", "token"
    max_context_tokens: int = 2000  # Maximum context tokens
    include_headers: bool = True  # Whether to include headers/titles
    include_captions: bool = True  # Whether to include image/table captions
    filter_content_types: List[str] = None  # Content types to include

    def __post_init__(self):
        if self.filter_content_types is None:
            self.filter_content_types = ["text"]


class ContextExtractor:
    """Universal context extractor supporting multiple content source formats"""

    def __init__(self, config: ContextConfig = None, tokenizer=None):
        """Initialize context extractor

        Args:
            config: Context extraction configuration
            tokenizer: Tokenizer for accurate token counting
        """
        self.config = config or ContextConfig()
        self.tokenizer = tokenizer

    def extract_context(
        self,
        content_source: Any,
        current_item_info: Dict[str, Any],
        content_format: str = "auto",
    ) -> str:
        """Extract context for current item from content source

        Args:
            content_source: Source content (list, dict, or other format)
            current_item_info: Information about current item (page_idx, index, etc.)
            content_format: Format hint for content source ("minerU", "text_chunks", "auto", etc.)

        Returns:
            Extracted context text
        """
        if not content_source and not self.config.context_window:
            return ""

        try:
            # Use format hint if provided, otherwise auto-detect
            if content_format == "minerU" and isinstance(content_source, list):
                return self._extract_from_content_list(
                    content_source, current_item_info
                )
            elif content_format == "text_chunks" and isinstance(content_source, list):
                return self._extract_from_text_chunks(content_source, current_item_info)
            elif content_format == "text" and isinstance(content_source, str):
                return self._extract_from_text_source(content_source, current_item_info)
            else:
                # Auto-detect content source format
                if isinstance(content_source, list):
                    return self._extract_from_content_list(
                        content_source, current_item_info
                    )
                elif isinstance(content_source, dict):
                    return self._extract_from_dict_source(
                        content_source, current_item_info
                    )
                elif isinstance(content_source, str):
                    return self._extract_from_text_source(
                        content_source, current_item_info
                    )
                else:
                    logger.warning(
                        f"Unsupported content source type: {type(content_source)}"
                    )
                    return ""
        except Exception as e:
            logger.error(f"Error extracting context: {e}")
            return ""

    def _extract_from_content_list(
        self, content_list: List[Dict], current_item_info: Dict
    ) -> str:
        """Extract context from MinerU-style content list

        Args:
            content_list: List of content items with page_idx and type info
            current_item_info: Current item information

        Returns:
            Context text from surrounding pages/chunks
        """
        if self.config.context_mode == "page":
            return self._extract_page_context(content_list, current_item_info)
        elif self.config.context_mode == "chunk":
            return self._extract_chunk_context(content_list, current_item_info)
        else:
            return self._extract_page_context(content_list, current_item_info)

    def _extract_page_context(
        self, content_list: List[Dict], current_item_info: Dict
    ) -> str:
        """Extract context based on page boundaries

        Args:
            content_list: List of content items
            current_item_info: Current item with page_idx

        Returns:
            Context text from surrounding pages
        """
        current_page = current_item_info.get("page_idx", 0)
        window_size = self.config.context_window

        start_page = max(0, current_page - window_size)
        end_page = current_page + window_size + 1

        context_texts = []

        for item in content_list:
            item_page = item.get("page_idx", 0)
            item_type = item.get("type", "")

            # Check if item is within context window and matches filter criteria
            if (
                start_page <= item_page < end_page
                and item_type in self.config.filter_content_types
            ):
                text_content = self._extract_text_from_item(item)
                if text_content and text_content.strip():
                    # Add page marker for better context understanding
                    if item_page != current_page:
                        context_texts.append(f"[Page {item_page}] {text_content}")
                    else:
                        context_texts.append(text_content)

        context = "\n".join(context_texts)
        return self._truncate_context(context)

    def _extract_chunk_context(
        self, content_list: List[Dict], current_item_info: Dict
    ) -> str:
        """Extract context based on content chunks

        Args:
            content_list: List of content items
            current_item_info: Current item with index info

        Returns:
            Context text from surrounding chunks
        """
        current_index = current_item_info.get("index", 0)
        window_size = self.config.context_window

        start_idx = max(0, current_index - window_size)
        end_idx = min(len(content_list), current_index + window_size + 1)

        context_texts = []

        for i in range(start_idx, end_idx):
            if i != current_index:
                item = content_list[i]
                item_type = item.get("type", "")

                if item_type in self.config.filter_content_types:
                    text_content = self._extract_text_from_item(item)
                    if text_content and text_content.strip():
                        context_texts.append(text_content)

        context = "\n".join(context_texts)
        return self._truncate_context(context)

    def _extract_text_from_item(self, item: Dict) -> str:
        """Extract text content from a content item

        Args:
            item: Content item dictionary

        Returns:
            Extracted text content
        """
        item_type = item.get("type", "")

        if item_type == "text":
            text = item.get("text", "")
            text_level = item.get("text_level", 0)

            # Add header indication for structured content
            if self.config.include_headers and text_level > 0:
                return f"{'#' * text_level} {text}"
            return text

        elif item_type == "image" and self.config.include_captions:
            captions = item.get("image_caption", item.get("img_caption", []))
            if captions:
                return f"[Image: {', '.join(captions)}]"

        elif item_type == "table" and self.config.include_captions:
            captions = item.get("table_caption", [])
            if captions:
                return f"[Table: {', '.join(captions)}]"

        return ""

    def _extract_from_dict_source(
        self, dict_source: Dict, current_item_info: Dict
    ) -> str:
        """Extract context from dictionary-based content source

        Args:
            dict_source: Dictionary containing content
            current_item_info: Current item information

        Returns:
            Extracted context text
        """
        # Handle different dictionary structures
        if "content" in dict_source:
            context = str(dict_source["content"])
        elif "text" in dict_source:
            context = str(dict_source["text"])
        else:
            # Try to extract any string values
            text_parts = []
            for value in dict_source.values():
                if isinstance(value, str):
                    text_parts.append(value)
            context = "\n".join(text_parts)

        return self._truncate_context(context)

    def _extract_from_text_source(
        self, text_source: str, current_item_info: Dict
    ) -> str:
        """Extract context from plain text source

        Args:
            text_source: Plain text content
            current_item_info: Current item information

        Returns:
            Truncated text context
        """
        return self._truncate_context(text_source)

    def _extract_from_text_chunks(
        self, text_chunks: List[str], current_item_info: Dict
    ) -> str:
        """Extract context from simple text chunks list

        Args:
            text_chunks: List of text strings
            current_item_info: Current item information with index

        Returns:
            Context text from surrounding chunks
        """
        current_index = current_item_info.get("index", 0)
        window_size = self.config.context_window

        start_idx = max(0, current_index - window_size)
        end_idx = min(len(text_chunks), current_index + window_size + 1)

        context_texts = []
        for i in range(start_idx, end_idx):
            if i != current_index:  # Exclude current chunk
                if i < len(text_chunks):
                    chunk_text = str(text_chunks[i]).strip()
                    if chunk_text:
                        context_texts.append(chunk_text)

        context = "\n".join(context_texts)
        return self._truncate_context(context)

    def _truncate_context(self, context: str) -> str:
        """Truncate context to maximum token limit

        Args:
            context: Context text to truncate

        Returns:
            Truncated context text
        """
        if not context:
            return ""

        # Use tokenizer if available for accurate token counting
        if self.tokenizer:
            tokens = self.tokenizer.encode(context)
            if len(tokens) <= self.config.max_context_tokens:
                return context

            # Truncate to max tokens and decode back to text
            truncated_tokens = tokens[: self.config.max_context_tokens]
            truncated_text = self.tokenizer.decode(truncated_tokens)

            # Try to end at a sentence boundary
            last_period = truncated_text.rfind(".")
            last_newline = truncated_text.rfind("\n")

            if last_period > len(truncated_text) * 0.8:
                return truncated_text[: last_period + 1]
            elif last_newline > len(truncated_text) * 0.8:
                return truncated_text[:last_newline]
            else:
                return truncated_text + "..."
        else:
            # Fallback to character-based truncation if no tokenizer
            if len(context) <= self.config.max_context_tokens:
                return context

            # Simple truncation - fallback when no tokenizer available
            truncated = context[: self.config.max_context_tokens]

            # Try to end at a sentence boundary
            last_period = truncated.rfind(".")
            last_newline = truncated.rfind("\n")

            if last_period > len(truncated) * 0.8:
                return truncated[: last_period + 1]
            elif last_newline > len(truncated) * 0.8:
                return truncated[:last_newline]
            else:
                return truncated + "..."


__all__ = ["ContextConfig", "ContextExtractor"]
