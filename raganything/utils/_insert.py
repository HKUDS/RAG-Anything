# -*- coding: utf-8 -*-
"""
Text Content Insertion Utilities.

Layer: Core
Primary Responsibility: LightRAG text insertion — pure text and multimodal-aware
    insertion with backward-compatible ainsert API detection.
Key Dependencies: lightrag (LightRAG.ainsert), lightrag.utils (logger)
"""

from __future__ import annotations

import inspect
from typing import Any
from lightrag.utils import logger


async def insert_text_content(
    lightrag,
    input: str | list[str],
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    ids: str | list[str] | None = None,
    file_paths: str | list[str] | None = None,
):
    """
    Insert pure text content into LightRAG

    Args:
        lightrag: LightRAG instance
        input: Single document string or list of document strings
        split_by_character: if split_by_character is not None, split the string
            by character, if chunk longer than chunk_token_size, it will be split
            again by token size.
        split_by_character_only: if split_by_character_only is True, split the
            string by character only, when split_by_character is None, this
            parameter is ignored.
        ids: single string of the document ID or list of unique document IDs,
            if not provided, MD5 hash IDs will be generated
        file_paths: single string of the file path or list of file paths,
            used for citation
    """
    logger.info("Starting text content insertion into LightRAG...")

    await lightrag.ainsert(
        input=input,
        file_paths=file_paths,
        split_by_character=split_by_character,
        split_by_character_only=split_by_character_only,
        ids=ids,
    )

    logger.info("Text content insertion complete")


async def insert_text_content_with_multimodal_content(
    lightrag,
    input: str | list[str],
    multimodal_content: list[dict[str, Any]] | None = None,
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    ids: str | list[str] | None = None,
    file_paths: str | list[str] | None = None,
    scheme_name: str | None = None,
):
    """
    Insert pure text content into LightRAG

    Args:
        lightrag: LightRAG instance
        input: Single document string or list of document strings
        multimodal_content: Multimodal content list (optional)
        split_by_character: character-based splitting
        split_by_character_only: character-only splitting mode
        ids: document IDs
        file_paths: file paths for citation
        scheme_name: scheme name (optional)
    """
    logger.info("Starting text content insertion into LightRAG...")

    insert_kwargs = {
        "input": input,
        "file_paths": file_paths,
        "split_by_character": split_by_character,
        "split_by_character_only": split_by_character_only,
        "ids": ids,
    }

    try:
        insert_signature = inspect.signature(lightrag.ainsert)
        supported_params = insert_signature.parameters
        accepts_any_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in supported_params.values()
        )
    except (TypeError, ValueError):
        supported_params = {}
        accepts_any_kwargs = True

    if multimodal_content is not None and (
        accepts_any_kwargs or "multimodal_content" in supported_params
    ):
        insert_kwargs["multimodal_content"] = multimodal_content
    elif multimodal_content is not None:
        logger.warning(
            "LightRAG ainsert() does not accept multimodal_content; "
            "retrying with text-only insertion so doc_status is still created"
        )

    if scheme_name is not None and (
        accepts_any_kwargs or "scheme_name" in supported_params
    ):
        insert_kwargs["scheme_name"] = scheme_name
    elif scheme_name is not None:
        logger.warning(
            "LightRAG ainsert() does not accept scheme_name; "
            "continuing without it for compatibility"
        )

    await lightrag.ainsert(**insert_kwargs)

    logger.info("Text content insertion complete")
