import os
import uuid
import asyncio
import logging
from typing import List, Optional
from fastapi import Request

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc

# Environment variables (now using standard LLM_BINDING variables)
LM_BASE_URL = os.getenv("LLM_BINDING_HOST", "http://localhost:1234/v1")
LM_API_KEY = os.getenv("LLM_BINDING_API_KEY", "lm-studio")
LM_MODEL_NAME = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
LM_EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m")
LM_EMBED_BASE_URL = os.getenv("EMBEDDING_BINDING_HOST", "http://localhost:1234/v1")
LM_EMBED_API_KEY = os.getenv("EMBEDDING_BINDING_API_KEY", "lm-studio")

# Concurrency limiter and timeout for LM Studio calls
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "4"))
_LLM_SEMAPHORE = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))  # seconds


async def get_rag_dependency(request: Request) -> RAGAnything:
    if not hasattr(request.app.state, "rag_instance"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail="RAG instance not initialized. Please check server startup logs.",
        )
    return request.app.state.rag_instance


async def lmstudio_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[List[dict]] = None,
    **kwargs,
) -> str:
    from lightrag.llm.openai import openai_complete_if_cache

    # Detect analysis prompts that require strict JSON fields
    wants_json = False
    p_low = (prompt or "").lower()
    sp_low = (system_prompt or "").lower()
    if (
        '"detailed_description"' in (prompt or "")
        or '"entity_info"' in (prompt or "")
        or "table" in p_low
        or "equation" in p_low
        or "image" in p_low
        or "analysis" in p_low
        or "table analysis" in sp_low
        or "image analyst" in sp_low
        or "equation analysis" in sp_low
    ):
        wants_json = True

    call_kwargs = dict(kwargs)

    # Filter out parameters that LM Studio doesn't support
    lmstudio_incompatible_params = ["stream", "stream_options", "parallel_tool_calls"]
    for param in lmstudio_incompatible_params:
        call_kwargs.pop(param, None)

    if wants_json:
        # Nudge for strict JSON fields
        system_prompt = (system_prompt or "") + (
            " Return a strict JSON object with fields: detailed_description (string), entity_info (object with keys: entity_name, entity_type, summary)."
        )
        # LM Studio-compatible JSON schema; some backends require this instead of json_object
        call_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "analysis",
                "schema": {
                    "type": "object",
                    "properties": {
                        "detailed_description": {"type": "string"},
                        "entity_info": {
                            "type": "object",
                            "properties": {
                                "entity_name": {"type": "string"},
                                "entity_type": {"type": "string"},
                                "summary": {"type": "string"},
                            },
                            "required": ["entity_name", "entity_type", "summary"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["detailed_description", "entity_info"],
                    "additionalProperties": False,
                },
            },
        }
        # # Deterministic decoding to reduce parse issues
        # call_kwargs.setdefault("temperature", 0.1)
        # call_kwargs.setdefault("top_p", 0.0)
        # call_kwargs.setdefault("max_tokens", 512)

    # Retry with exponential backoff; drop response_format if backend rejects it
    last_err = None
    for attempt in range(3):
        try:
            async with _LLM_SEMAPHORE:
                return await openai_complete_if_cache(
                    model=LM_MODEL_NAME,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages or [],
                    base_url=LM_BASE_URL,
                    api_key=LM_API_KEY,
                    timeout=LLM_REQUEST_TIMEOUT,
                    **call_kwargs,
                )
        except Exception as e:
            msg = str(e)
            # Handle various LM Studio compatibility issues
            if (
                wants_json
                and call_kwargs.get("response_format") is not None
                and (
                    "response_format" in msg
                    or "json_schema" in msg
                    or "must be 'json_schema' or 'text'" in msg
                )
            ):
                # Remove response_format and retry
                call_kwargs.pop("response_format", None)
                await asyncio.sleep(0.25)
                continue
            elif "unexpected keyword argument" in msg:
                # Handle other unexpected parameters
                if "stream" in msg:
                    call_kwargs.pop("stream", None)
                if "stream_options" in msg:
                    call_kwargs.pop("stream_options", None)
                if "parallel_tool_calls" in msg:
                    call_kwargs.pop("parallel_tool_calls", None)
                await asyncio.sleep(0.25)
                continue
            last_err = e
            await asyncio.sleep(0.5 * (2**attempt))
    raise last_err


async def lmstudio_embedding_async(texts: List[str]) -> List[List[float]]:
    from lightrag.llm.openai import openai_embed

    # This allows custom embedding dimensions configured via environment variables
    embeddings = await openai_embed.func(
        texts=texts,
        model=LM_EMBED_MODEL,
        base_url=LM_EMBED_BASE_URL,
        api_key=LM_EMBED_API_KEY,
    )
    return embeddings.tolist()


def make_embedding_func() -> EmbeddingFunc:
    # Get embedding dimension from environment variable, default based on model
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "768"))
    max_token_size = int(os.getenv("MAX_EMBED_TOKENS", "8192"))
    return EmbeddingFunc(
        embedding_dim=embedding_dim,
        max_token_size=max_token_size,
        func=lmstudio_embedding_async,
    )


async def initialize_rag() -> RAGAnything:
    # Fresh working dir to isolate demo runs
    working_dir = os.getenv("WORKING_DIR", f"./rag_storage_service/{uuid.uuid4()}")
    config = RAGAnythingConfig(
        working_dir=working_dir,
        parser="mineru",
        parse_method="auto",
        enable_image_processing=False,  # Disabled - focus on Office documents only
        enable_table_processing=True,  # Keep for Excel/Office table processing
        enable_equation_processing=False,  # Disabled - not needed for Office docs
    )

    rag_instance = RAGAnything(
        config=config,
        llm_model_func=lmstudio_llm_model_func,
        embedding_func=make_embedding_func(),
    )

    # Avoid writing unknown field 'multimodal_processed' with older LightRAG versions
    async def _noop_mark_multimodal(doc_id: str):
        return None

    rag_instance._mark_multimodal_processing_complete = _noop_mark_multimodal

    # For query-only use, bypass parser check and initialize LightRAG storages
    try:
        rag_instance._parser_installation_checked = True
        init_result = await rag_instance._ensure_lightrag_initialized()
        if isinstance(init_result, dict) and not init_result.get("success", False):
            pass
    except Exception:
        pass

    return rag_instance


# Make logger available in core.py
logger = logging.getLogger(__name__)


async def cleanup_rag(rag_instance: Optional[RAGAnything]) -> None:
    """Cleanup RAG instance and finalize storages"""
    if rag_instance is not None:
        try:
            # Finalize storages if lightrag instance is available
            if hasattr(rag_instance, "lightrag") and rag_instance.lightrag:
                try:
                    await rag_instance.lightrag.finalize_storages()
                    logger.info("LightRAG storages finalized successfully")
                except Exception as e:
                    logger.warning(f"Could not finalize storages: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up RAG instance: {e}")
