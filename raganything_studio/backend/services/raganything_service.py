from __future__ import annotations

import asyncio
import traceback
from collections.abc import Callable
from typing import Any

from fastapi import status

from raganything_studio.backend.config import ModelProviderProfile
from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.job import JobStage, ProcessOptions
from raganything_studio.backend.schemas.query import QueryRequest, QueryResponse


class RAGAnythingService:
    """Thin async wrapper around the real RAG-Anything APIs."""

    def __init__(self, settings: StudioSettings):
        self._settings = settings
        self._rag_by_profile: dict[str, Any] = {}
        self._processing_semaphore: asyncio.Semaphore | None = None
        self._processing_limit: int | None = None

    def reset(self) -> None:
        self._rag_by_profile.clear()
        self._processing_semaphore = None
        self._processing_limit = None

    async def get_rag(
        self,
        options: ProcessOptions | None = None,
        profile_id: str | None = None,
        enable_vlm_enhancement: bool | None = None,
    ) -> Any:
        profile = _select_profile(self._settings, profile_id)
        vlm_enabled = _vlm_enabled(
            self._settings, options, enable_vlm_enhancement
        )
        cache_key = f"{profile.id}:vlm={int(vlm_enabled)}"
        if cache_key not in self._rag_by_profile:
            self._rag_by_profile[cache_key] = self._create_rag(
                options, profile, vlm_enabled
            )
        elif options is not None:
            rag = self._rag_by_profile[cache_key]
            rag.update_config(
                **_config_updates(self._settings, options)
            )
            _refresh_processors_if_initialized(rag)
        return self._rag_by_profile[cache_key]

    async def process_document(
        self,
        document_path: str,
        document_id: str,
        options: ProcessOptions,
        log: Callable[[str], None],
        set_progress: Callable[[JobStage, float, str], None],
    ) -> None:
        limit = _processing_limit(self._settings, options)
        semaphore = self._processing_semaphore_for(limit)
        if semaphore.locked():
            log(f"Waiting for a document processing slot (limit={limit})")

        async with semaphore:
            set_progress(JobStage.PREPARING, 0.05, "Preparing document processing")
            log(f"Processing document: {document_path}")
            log(f"Parser={options.parser}, parse_method={options.parse_method}")
            log(f"Document concurrency limit={limit}")
            log(
                "VLM enhancement="
                f"{'enabled' if options.enable_vlm_enhancement else 'disabled'}"
            )

            rag = await self.get_rag(options, options.profile_id)
            _register_job_callback(rag, log)

            set_progress(JobStage.PARSING, 0.15, "Parsing document")
            parser_kwargs = _parser_kwargs(options)

            await rag.process_document_complete(
                file_path=document_path,
                output_dir=options.output_dir or str(self._settings.output_dir / document_id),
                parse_method=options.parse_method,
                doc_id=document_id,
                **parser_kwargs,
            )

            set_progress(JobStage.FINALIZING, 0.95, "Finalizing document processing")

    async def query(self, request: QueryRequest) -> QueryResponse:
        rag = await self.get_rag(
            profile_id=request.profile_id,
            enable_vlm_enhancement=request.use_multimodal,
        )
        query_kwargs: dict[str, Any] = {"vlm_enhanced": request.use_multimodal}
        if request.top_k is not None:
            query_kwargs["top_k"] = request.top_k

        try:
            result = await rag.aquery(request.question, mode=request.mode, **query_kwargs)
        except Exception as exc:
            raise api_error(
                "QUERY_FAILED",
                f"Query failed: {exc}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        return QueryResponse(
            answer=str(result),
            sources=[],
            raw={"result": result},
            trace={
                "retrieved_text": [],
                "retrieved_images": [],
                "retrieved_tables": [],
                "retrieved_equations": [],
                "graph_entities": [],
                "context": "",
            },
        )

    def _create_rag(
        self,
        options: ProcessOptions | None,
        profile: ModelProviderProfile,
        enable_vlm_enhancement: bool,
    ) -> Any:
        try:
            from lightrag.llm.openai import openai_complete_if_cache, openai_embed
            from lightrag.utils import EmbeddingFunc
            from raganything import RAGAnything, RAGAnythingConfig
        except Exception as exc:
            raise api_error(
                "RAG_INIT_FAILED",
                f"RAG-Anything dependencies are not available: {exc}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        if not profile.llm.api_key or not profile.embedding.api_key:
            raise api_error(
                "RAG_INIT_FAILED",
                f"Profile {profile.name!r} needs LLM and Embedding API keys before processing or querying",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        def llm_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> Any:
            return openai_complete_if_cache(
                profile.llm.model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=profile.llm.api_key,
                base_url=profile.llm.base_url,
                **kwargs,
            )

        def vision_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            image_data: str | None = None,
            messages: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> Any:
            if messages:
                return openai_complete_if_cache(
                    profile.vision.model,
                    "",
                    messages=messages,
                    api_key=profile.vision.api_key or profile.llm.api_key,
                    base_url=profile.vision.base_url or profile.llm.base_url,
                    **kwargs,
                )
            if image_data:
                return openai_complete_if_cache(
                    profile.vision.model,
                    "",
                    messages=[
                        {"role": "system", "content": system_prompt}
                        if system_prompt
                        else None,
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_data}"
                                    },
                                },
                            ],
                        },
                    ],
                    api_key=profile.vision.api_key or profile.llm.api_key,
                    base_url=profile.vision.base_url or profile.llm.base_url,
                    **kwargs,
                )
            return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

        embedding_func = EmbeddingFunc(
            embedding_dim=profile.embedding.embedding_dim or self._settings.embedding_dim,
            max_token_size=(
                profile.embedding.embedding_max_token_size
                or self._settings.embedding_max_token_size
            ),
            func=lambda texts: openai_embed.func(
                texts,
                model=profile.embedding.model,
                api_key=profile.embedding.api_key,
                base_url=profile.embedding.base_url,
                embedding_dim=(
                    profile.embedding.embedding_dim or self._settings.embedding_dim
                ),
                max_token_size=(
                    profile.embedding.embedding_max_token_size
                    or self._settings.embedding_max_token_size
                ),
            ),
        )

        config = RAGAnythingConfig(
            **_config_updates(
                self._settings,
                options,
                enable_vlm_enhancement=enable_vlm_enhancement,
            )
        )
        return RAGAnything(
            config=config,
            llm_model_func=llm_model_func,
            vision_model_func=vision_model_func if enable_vlm_enhancement else None,
            embedding_func=embedding_func,
        )

    def _processing_semaphore_for(self, limit: int) -> asyncio.Semaphore:
        if self._processing_semaphore is None or self._processing_limit != limit:
            self._processing_semaphore = asyncio.Semaphore(limit)
            self._processing_limit = limit
        return self._processing_semaphore


def _config_updates(
    settings: StudioSettings,
    options: ProcessOptions | None,
    enable_vlm_enhancement: bool | None = None,
) -> dict[str, Any]:
    if options is None:
        vlm_enabled = (
            settings.default_enable_vlm_enhancement
            if enable_vlm_enhancement is None
            else enable_vlm_enhancement
        )
        return {
            "working_dir": str(settings.working_dir),
            "parser_output_dir": str(settings.output_dir),
            "enable_image_processing": vlm_enabled,
            "enable_table_processing": vlm_enabled,
            "enable_equation_processing": vlm_enabled,
            "max_concurrent_files": settings.max_concurrent_files,
        }

    vlm_enabled = options.enable_vlm_enhancement
    return {
        "working_dir": options.working_dir or str(settings.working_dir),
        "parser_output_dir": options.output_dir or str(settings.output_dir),
        "parser": options.parser,
        "parse_method": options.parse_method,
        "enable_image_processing": (
            vlm_enabled and options.enable_image_processing
        ),
        "enable_table_processing": (
            vlm_enabled and options.enable_table_processing
        ),
        "enable_equation_processing": (
            vlm_enabled and options.enable_equation_processing
        ),
        "max_concurrent_files": _processing_limit(settings, options),
    }


def _vlm_enabled(
    settings: StudioSettings,
    options: ProcessOptions | None,
    override: bool | None,
) -> bool:
    if override is not None:
        return override
    if options is not None:
        return options.enable_vlm_enhancement
    return settings.default_enable_vlm_enhancement


def _processing_limit(settings: StudioSettings, options: ProcessOptions | None) -> int:
    if options is not None and options.max_concurrent_files is not None:
        return max(1, options.max_concurrent_files)
    return max(1, settings.max_concurrent_files)


def _refresh_processors_if_initialized(rag: Any) -> None:
    if getattr(rag, "lightrag", None) is None:
        return
    initializer = getattr(rag, "_initialize_processors", None)
    if callable(initializer):
        initializer()


def _select_profile(
    settings: StudioSettings, profile_id: str | None
) -> ModelProviderProfile:
    wanted = profile_id or settings.active_profile_id
    profile = next(
        (candidate for candidate in settings.profiles if candidate.id == wanted),
        None,
    )
    if profile is not None:
        return profile
    if settings.profiles:
        return settings.profiles[0]
    raise api_error(
        "RAG_INIT_FAILED",
        "No model profile is configured",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _parser_kwargs(options: ProcessOptions) -> dict[str, Any]:
    parser_kwargs: dict[str, Any] = {
        "lang": options.lang,
        "device": options.device,
    }
    if options.start_page is not None:
        parser_kwargs["start_page"] = options.start_page
    if options.end_page is not None:
        parser_kwargs["end_page"] = options.end_page
    return parser_kwargs


def _register_job_callback(rag: Any, log: Callable[[str], None]) -> None:
    try:
        from raganything.callbacks import ProcessingCallback
    except Exception:
        return

    class StudioCallback(ProcessingCallback):
        def on_parse_start(self, file_path: str, parser: str = "", **_: Any) -> None:
            log(f"Started parsing {file_path} with {parser or 'configured parser'}")

        def on_parse_complete(
            self, file_path: str, content_blocks: int = 0, **_: Any
        ) -> None:
            log(f"Parsed {file_path}: {content_blocks} content blocks")

        def on_text_insert_start(self, file_path: str, **_: Any) -> None:
            log(f"Building text index for {file_path}")

        def on_text_insert_complete(self, file_path: str, **_: Any) -> None:
            log(f"Text index complete for {file_path}")

        def on_multimodal_start(
            self, file_path: str, item_count: int = 0, **_: Any
        ) -> None:
            log(f"Processing {item_count} multimodal items for {file_path}")

        def on_multimodal_item_complete(
            self,
            file_path: str,
            item_index: int = 0,
            item_type: str = "",
            total_items: int = 0,
            **_: Any,
        ) -> None:
            log(
                f"Processed {item_type or 'multimodal'} item "
                f"{item_index + 1}/{total_items} for {file_path}"
            )

        def on_multimodal_complete(self, file_path: str, **_: Any) -> None:
            log(f"Multimodal processing complete for {file_path}")

        def on_document_error(self, error: BaseException | str = "", **_: Any) -> None:
            log(f"Document processing error: {error}")

    if not hasattr(rag, "_studio_callback_registered"):
        rag.callback_manager.register(StudioCallback())
        setattr(rag, "_studio_callback_registered", True)


def format_traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
