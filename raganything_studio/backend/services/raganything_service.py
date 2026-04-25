from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from fastapi import status

from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.job import JobStage, ProcessOptions
from raganything_studio.backend.schemas.query import QueryRequest, QueryResponse


class RAGAnythingService:
    """Thin async wrapper around the real RAG-Anything APIs."""

    def __init__(self, settings: StudioSettings):
        self._settings = settings
        self._rag: Any | None = None

    def reset(self) -> None:
        self._rag = None

    async def get_rag(self, options: ProcessOptions | None = None) -> Any:
        if self._rag is None:
            self._rag = self._create_rag(options)
        elif options is not None:
            self._rag.update_config(**_config_updates(self._settings, options))
        return self._rag

    async def process_document(
        self,
        document_path: str,
        document_id: str,
        options: ProcessOptions,
        log: Callable[[str], None],
        set_progress: Callable[[JobStage, float, str], None],
    ) -> None:
        set_progress(JobStage.PREPARING, 0.05, "Preparing document processing")
        log(f"Processing document: {document_path}")
        log(f"Parser={options.parser}, parse_method={options.parse_method}")

        rag = await self.get_rag(options)
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
        rag = await self.get_rag()
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

    def _create_rag(self, options: ProcessOptions | None) -> Any:
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

        if not self._settings.llm_api_key or not self._settings.embedding_api_key:
            raise api_error(
                "RAG_INIT_FAILED",
                "Set OPENAI_API_KEY or LLM_API_KEY/EMBEDDING_API_KEY before processing or querying",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        def llm_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> Any:
            return openai_complete_if_cache(
                self._settings.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url,
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
                    self._settings.vision_model,
                    "",
                    messages=messages,
                    api_key=self._settings.vision_api_key or self._settings.llm_api_key,
                    base_url=self._settings.vision_base_url or self._settings.llm_base_url,
                    **kwargs,
                )
            if image_data:
                return openai_complete_if_cache(
                    self._settings.vision_model,
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
                    api_key=self._settings.vision_api_key or self._settings.llm_api_key,
                    base_url=self._settings.vision_base_url or self._settings.llm_base_url,
                    **kwargs,
                )
            return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

        embedding_func = EmbeddingFunc(
            embedding_dim=self._settings.embedding_dim,
            max_token_size=self._settings.embedding_max_token_size,
            func=lambda texts: openai_embed.func(
                texts,
                model=self._settings.embedding_model,
                api_key=self._settings.embedding_api_key,
                base_url=self._settings.embedding_base_url,
            ),
        )

        config = RAGAnythingConfig(**_config_updates(self._settings, options))
        return RAGAnything(
            config=config,
            llm_model_func=llm_model_func,
            vision_model_func=vision_model_func,
            embedding_func=embedding_func,
        )


def _config_updates(
    settings: StudioSettings, options: ProcessOptions | None
) -> dict[str, Any]:
    if options is None:
        return {
            "working_dir": str(settings.working_dir),
            "parser_output_dir": str(settings.output_dir),
        }

    return {
        "working_dir": options.working_dir or str(settings.working_dir),
        "parser_output_dir": options.output_dir or str(settings.output_dir),
        "parser": options.parser,
        "parse_method": options.parse_method,
        "enable_image_processing": options.enable_image_processing,
        "enable_table_processing": options.enable_table_processing,
        "enable_equation_processing": options.enable_equation_processing,
    }


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
