from __future__ import annotations

import asyncio
import contextvars
import hashlib
import inspect
import json
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import status

from raganything_studio.backend.config import ModelProviderProfile
from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.schemas.job import JobStage, ProcessOptions
from raganything_studio.backend.schemas.query import QueryRequest, QueryResponse

_CURRENT_STATS: contextvars.ContextVar["ProcessingStats | None"] = (
    contextvars.ContextVar("raganything_studio_processing_stats", default=None)
)


class RAGAnythingService:
    """Thin async wrapper around the real RAG-Anything APIs."""

    def __init__(self, settings: StudioSettings):
        self._settings = settings
        self._rag_by_profile: dict[str, Any] = {}
        self._processing_semaphore: asyncio.Semaphore | None = None
        self._processing_limit: int | None = None
        self._api_semaphores: dict[str, tuple[int, asyncio.Semaphore]] = {}
        self._write_locks: dict[str, asyncio.Lock] = {}

    def reset(self) -> None:
        self._rag_by_profile.clear()
        self._processing_semaphore = None
        self._processing_limit = None
        self._api_semaphores.clear()
        self._write_locks.clear()

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
    ) -> "ProcessResult":
        options = _effective_options(self._settings, options)
        stats = ProcessingStats()
        token = _CURRENT_STATS.set(stats)
        try:
            limit = _processing_limit(self._settings, options)
            semaphore = self._processing_semaphore_for(limit)
            if semaphore.locked():
                log(f"Waiting for a document processing slot (limit={limit})")

            async with semaphore:
                with stats.timer("preparing"):
                    set_progress(
                        JobStage.PREPARING, 0.05, "Preparing document processing"
                    )
                    document_hash = _sha256_file(Path(document_path))
                    output_dir = options.output_dir or str(
                        self._settings.output_dir / document_id
                    )
                    log(f"Processing document: {document_path}")
                    log(f"Document hash={document_hash[:16]}...")
                    log(
                        f"Preset={options.processing_preset}, "
                        f"parser={options.parser}, parse_method={options.parse_method}"
                    )
                    log(f"Document concurrency limit={limit}")
                    log(
                        "VLM enhancement="
                        f"{'enabled' if options.enable_vlm_enhancement else 'disabled'}"
                    )
                    if options.start_page is not None or options.end_page is not None:
                        log(
                            "Page range="
                            f"{options.start_page or 0}..{options.end_page or 'end'}"
                        )
                    if options.preview_mode:
                        log("Preview mode enabled: parsing only, no RAG storage insert")

                    rag = await self.get_rag(options, options.profile_id)
                    initializer = getattr(rag, "_ensure_lightrag_initialized", None)
                    if callable(initializer):
                        await initializer()
                    _register_job_callback(rag, log, stats)
                    _install_studio_optimizations(
                        rag=rag,
                        settings=self._settings,
                        options=options,
                        stats=stats,
                        document_hash=document_hash,
                        log=log,
                    )

                parser_kwargs = _parser_kwargs(options)

                if options.preview_mode:
                    set_progress(JobStage.PARSING, 0.15, "Parsing preview")
                    with stats.timer("parse"):
                        await rag.parse_document(
                            document_path,
                            output_dir=output_dir,
                            parse_method=options.parse_method,
                            **parser_kwargs,
                        )
                    set_progress(JobStage.FINALIZING, 0.95, "Finalizing preview")
                    with stats.timer("finalizing"):
                        pass
                    return ProcessResult(indexed=False, stats=stats.to_job_metrics())

                set_progress(JobStage.PARSING, 0.15, "Parsing and processing document")
                write_lock = self._write_lock_for(
                    options.working_dir or str(self._settings.working_dir)
                )
                if options.write_lock_enabled and write_lock.locked():
                    log("Waiting for working_dir write lock")

                async def run_pipeline() -> None:
                    await rag.process_document_complete(
                        file_path=document_path,
                        output_dir=output_dir,
                        parse_method=options.parse_method,
                        doc_id=document_id,
                        **parser_kwargs,
                    )

                with stats.timer("total_pipeline"):
                    if options.write_lock_enabled:
                        async with write_lock:
                            log("Acquired working_dir write lock")
                            await run_pipeline()
                    else:
                        await run_pipeline()

                set_progress(
                    JobStage.FINALIZING, 0.95, "Finalizing document processing"
                )
                with stats.timer("finalizing"):
                    pass

                return ProcessResult(indexed=True, stats=stats.to_job_metrics())
        finally:
            _CURRENT_STATS.reset(token)

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

        effective = _effective_options(self._settings, options)

        def llm_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> Any:
            return self._call_model_with_limits(
                "llm",
                effective.llm_max_concurrency or self._settings.llm_max_concurrency,
                effective,
                lambda: openai_complete_if_cache(
                profile.llm.model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=profile.llm.api_key,
                base_url=profile.llm.base_url,
                **kwargs,
                ),
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
                return self._call_model_with_limits(
                    "vlm",
                    effective.vlm_max_concurrency or self._settings.vlm_max_concurrency,
                    effective,
                    lambda: openai_complete_if_cache(
                    profile.vision.model,
                    "",
                    messages=messages,
                    api_key=profile.vision.api_key or profile.llm.api_key,
                    base_url=profile.vision.base_url or profile.llm.base_url,
                    **kwargs,
                    ),
                )
            if image_data:
                return self._call_model_with_limits(
                    "vlm",
                    effective.vlm_max_concurrency or self._settings.vlm_max_concurrency,
                    effective,
                    lambda: openai_complete_if_cache(
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
                    ),
                )
            return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

        def embedding_call(texts: list[str]) -> Any:
            return self._call_model_with_limits(
                "embedding",
                effective.embedding_max_concurrency or self._settings.embedding_max_concurrency,
                effective,
                lambda: openai_embed.func(
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

        embedding_func = EmbeddingFunc(
            embedding_dim=profile.embedding.embedding_dim or self._settings.embedding_dim,
            max_token_size=(
                profile.embedding.embedding_max_token_size
                or self._settings.embedding_max_token_size
            ),
            func=embedding_call,
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
            lightrag_kwargs={
                "embedding_batch_num": effective.embedding_batch_size
                or self._settings.embedding_batch_size,
                "embedding_func_max_async": (
                    effective.embedding_max_concurrency
                    or self._settings.embedding_max_concurrency
                ),
                "llm_model_max_async": (
                    effective.llm_max_concurrency
                    or self._settings.llm_max_concurrency
                ),
            },
        )

    def _processing_semaphore_for(self, limit: int) -> asyncio.Semaphore:
        if self._processing_semaphore is None or self._processing_limit != limit:
            self._processing_semaphore = asyncio.Semaphore(limit)
            self._processing_limit = limit
        return self._processing_semaphore

    def _api_semaphore_for(self, role: str, limit: int) -> asyncio.Semaphore:
        current = self._api_semaphores.get(role)
        if current is None or current[0] != limit:
            semaphore = asyncio.Semaphore(limit)
            self._api_semaphores[role] = (limit, semaphore)
            return semaphore
        return current[1]

    def _write_lock_for(self, working_dir: str) -> asyncio.Lock:
        key = str(Path(working_dir).expanduser().resolve())
        if key not in self._write_locks:
            self._write_locks[key] = asyncio.Lock()
        return self._write_locks[key]

    async def _call_model_with_limits(
        self,
        role: str,
        limit: int,
        options: ProcessOptions,
        call: Callable[[], Any],
    ) -> Any:
        semaphore = self._api_semaphore_for(role, max(1, limit))
        attempts = options.retry_max_attempts or self._settings.retry_max_attempts
        base_delay = options.retry_base_delay
        if base_delay is None:
            base_delay = self._settings.retry_base_delay
        max_delay = options.retry_max_delay
        if max_delay is None:
            max_delay = self._settings.retry_max_delay

        async with semaphore:
            for attempt in range(1, max(1, attempts) + 1):
                try:
                    stats = _CURRENT_STATS.get()
                    if stats is not None:
                        stats.count_api_call(role)
                    started = time.perf_counter()
                    result = call()
                    if inspect.isawaitable(result):
                        result = await result
                    stats = _CURRENT_STATS.get()
                    if stats is not None:
                        stats.add_duration(role, time.perf_counter() - started)
                    return result
                except Exception:
                    stats = _CURRENT_STATS.get()
                    if stats is not None:
                        stats.count_api_call(f"{role}_retries")
                    if attempt >= attempts:
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    await asyncio.sleep(delay)


@dataclass
class ProcessResult:
    indexed: bool
    stats: dict[str, dict[str, float | int]]


@dataclass
class ProcessingStats:
    stage_durations: dict[str, float] = field(default_factory=dict)
    api_call_counts: dict[str, int] = field(default_factory=dict)
    cache_hits: dict[str, int] = field(default_factory=dict)
    cache_misses: dict[str, int] = field(default_factory=dict)

    def timer(self, stage: str) -> "_StatsTimer":
        return _StatsTimer(self, stage)

    def add_duration(self, stage: str, seconds: float) -> None:
        self.stage_durations[stage] = self.stage_durations.get(stage, 0.0) + seconds

    def count_api_call(self, role: str, amount: int = 1) -> None:
        self.api_call_counts[role] = self.api_call_counts.get(role, 0) + amount

    def hit(self, cache_name: str) -> None:
        self.cache_hits[cache_name] = self.cache_hits.get(cache_name, 0) + 1

    def miss(self, cache_name: str) -> None:
        self.cache_misses[cache_name] = self.cache_misses.get(cache_name, 0) + 1

    def to_job_metrics(self) -> dict[str, dict[str, float | int]]:
        return {
            "stage_durations": {
                key: round(value, 3)
                for key, value in self.stage_durations.items()
            },
            "api_call_counts": dict(self.api_call_counts),
            "cache_hits": dict(self.cache_hits),
            "cache_misses": dict(self.cache_misses),
        }


class _StatsTimer:
    def __init__(self, stats: ProcessingStats, stage: str) -> None:
        self._stats = stats
        self._stage = stage
        self._start = 0.0

    def __enter__(self) -> None:
        self._start = time.perf_counter()

    def __exit__(self, *_: object) -> None:
        self._stats.add_duration(self._stage, time.perf_counter() - self._start)


PRESET_OVERRIDES: dict[str, dict[str, Any]] = {
    "fast": {
        "enable_vlm_enhancement": False,
        "enable_image_processing": False,
        "enable_table_processing": False,
        "enable_equation_processing": False,
        "embedding_batch_size": 32,
        "llm_max_concurrency": 2,
        "vlm_max_concurrency": 1,
        "embedding_max_concurrency": 8,
        "retry_max_attempts": 2,
        "enable_parse_cache": True,
        "enable_modal_cache": True,
    },
    "balanced": {
        "embedding_batch_size": 16,
        "llm_max_concurrency": 2,
        "vlm_max_concurrency": 1,
        "embedding_max_concurrency": 4,
        "retry_max_attempts": 3,
        "enable_parse_cache": True,
        "enable_modal_cache": True,
    },
    "deep": {
        "enable_vlm_enhancement": True,
        "enable_image_processing": True,
        "enable_table_processing": True,
        "enable_equation_processing": True,
        "embedding_batch_size": 8,
        "llm_max_concurrency": 1,
        "vlm_max_concurrency": 1,
        "embedding_max_concurrency": 2,
        "retry_max_attempts": 4,
        "enable_parse_cache": True,
        "enable_modal_cache": True,
    },
}


def _effective_options(settings: StudioSettings, options: ProcessOptions) -> ProcessOptions:
    update: dict[str, Any] = {}
    preset = (options.processing_preset or settings.default_processing_preset).lower()
    explicit_fields = (
        getattr(options, "model_fields_set", None)
        or getattr(options, "__fields_set__", set())
    )
    if preset != "custom":
        for key, value in PRESET_OVERRIDES.get(preset, PRESET_OVERRIDES["balanced"]).items():
            if key not in explicit_fields:
                update[key] = value
    update.setdefault("processing_preset", preset)
    update.setdefault("embedding_batch_size", options.embedding_batch_size or settings.embedding_batch_size)
    update.setdefault("llm_max_concurrency", options.llm_max_concurrency or settings.llm_max_concurrency)
    update.setdefault("vlm_max_concurrency", options.vlm_max_concurrency or settings.vlm_max_concurrency)
    update.setdefault(
        "embedding_max_concurrency",
        options.embedding_max_concurrency or settings.embedding_max_concurrency,
    )
    update.setdefault("retry_max_attempts", options.retry_max_attempts or settings.retry_max_attempts)
    update.setdefault(
        "retry_base_delay",
        options.retry_base_delay
        if options.retry_base_delay is not None
        else settings.retry_base_delay,
    )
    update.setdefault(
        "retry_max_delay",
        options.retry_max_delay
        if options.retry_max_delay is not None
        else settings.retry_max_delay,
    )
    update.setdefault("write_lock_enabled", options.write_lock_enabled)
    update.setdefault("enable_parse_cache", options.enable_parse_cache)
    update.setdefault("enable_modal_cache", options.enable_modal_cache)
    update.setdefault("preview_mode", options.preview_mode)
    if hasattr(options, "model_copy"):
        return options.model_copy(update=update)
    return options.copy(update=update)


class _JsonCache:
    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, key: str) -> Any | None:
        return self._read().get(key)

    def set(self, key: str, value: Any) -> None:
        payload = self._read()
        payload[key] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}


def _install_studio_optimizations(
    *,
    rag: Any,
    settings: StudioSettings,
    options: ProcessOptions,
    stats: ProcessingStats,
    document_hash: str,
    log: Callable[[str], None],
) -> None:
    _install_parse_cache(rag, settings, options, stats, document_hash, log)
    _install_modal_cache(rag, settings, options, stats, log)


def _install_parse_cache(
    rag: Any,
    settings: StudioSettings,
    options: ProcessOptions,
    stats: ProcessingStats,
    document_hash: str,
    log: Callable[[str], None],
) -> None:
    if not hasattr(rag, "_studio_original_parse_document"):
        setattr(rag, "_studio_original_parse_document", rag.parse_document)
    original = getattr(rag, "_studio_original_parse_document")
    cache = _JsonCache(settings.data_dir / "cache" / "parse_cache.json")

    async def parse_document_with_studio_cache(
        file_path: str,
        output_dir: str | None = None,
        parse_method: str | None = None,
        display_stats: bool | None = None,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], str]:
        cache_key = _parse_cache_key(
            document_hash=document_hash,
            parser=getattr(getattr(rag, "config", None), "parser", options.parser),
            parse_method=parse_method or options.parse_method,
            kwargs=kwargs,
        )
        if options.enable_parse_cache:
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and isinstance(cached.get("content_list"), list):
                stats.hit("parse")
                log(f"Parse cache hit: {cache_key[:16]}...")
                if output_dir:
                    _write_cached_content_list(
                        Path(output_dir), Path(file_path).stem, cached["content_list"]
                    )
                return cached["content_list"], str(cached.get("doc_id") or "")
            stats.miss("parse")

        content_list, doc_id = await original(
            file_path,
            output_dir=output_dir,
            parse_method=parse_method,
            display_stats=display_stats,
            **kwargs,
        )
        if options.enable_parse_cache:
            cache.set(
                cache_key,
                {
                    "content_list": content_list,
                    "doc_id": doc_id,
                    "document_hash": document_hash,
                    "stored_at": time.time(),
                },
            )
        return content_list, doc_id

    rag.parse_document = parse_document_with_studio_cache


def _install_modal_cache(
    rag: Any,
    settings: StudioSettings,
    options: ProcessOptions,
    stats: ProcessingStats,
    log: Callable[[str], None],
) -> None:
    if not options.enable_modal_cache:
        return
    processors = getattr(rag, "modal_processors", {}) or {}
    cache = _JsonCache(settings.data_dir / "cache" / "modal_cache.json")
    for processor in processors.values():
        if not hasattr(processor, "generate_description_only"):
            continue
        if not hasattr(processor, "_studio_original_generate_description_only"):
            setattr(
                processor,
                "_studio_original_generate_description_only",
                processor.generate_description_only,
            )
        original = getattr(processor, "_studio_original_generate_description_only")

        async def cached_generate_description_only(
            *args: Any,
            _original: Callable[..., Any] = original,
            **kwargs: Any,
        ) -> Any:
            modal_content = kwargs.get("modal_content") if "modal_content" in kwargs else (args[0] if args else None)
            content_type = kwargs.get("content_type") if "content_type" in kwargs else (args[1] if len(args) > 1 else "unknown")
            cache_key = _modal_cache_key(str(content_type), modal_content)
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and "description" in cached and "entity_info" in cached:
                stats.hit("modal")
                log(f"Modal cache hit ({content_type}): {cache_key[:16]}...")
                return cached["description"], cached["entity_info"]
            stats.miss("modal")
            result = _original(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, tuple) and len(result) >= 2:
                cache.set(
                    cache_key,
                    {
                        "description": result[0],
                        "entity_info": result[1],
                        "content_type": content_type,
                        "stored_at": time.time(),
                    },
                )
            return result

        processor.generate_description_only = cached_generate_description_only


def _parse_cache_key(
    *, document_hash: str, parser: str, parse_method: str, kwargs: dict[str, Any]
) -> str:
    relevant = {
        key: kwargs.get(key)
        for key in ("lang", "device", "start_page", "end_page", "formula", "table")
        if key in kwargs
    }
    payload = {
        "document_hash": document_hash,
        "parser": parser,
        "parse_method": parse_method,
        **relevant,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _modal_cache_key(content_type: str, modal_content: Any) -> str:
    payload = json.dumps(
        {"content_type": content_type, "content": modal_content},
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _write_cached_content_list(
    output_dir: Path, file_stem: str, content_list: list[dict[str, Any]]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{file_stem}_content_list.json"
    target.write_text(
        json.dumps(content_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _register_job_callback(
    rag: Any, log: Callable[[str], None], stats: ProcessingStats
) -> None:
    try:
        from raganything.callbacks import ProcessingCallback
    except Exception:
        return

    manager = rag.callback_manager
    callbacks = getattr(manager, "_callbacks", None)
    if isinstance(callbacks, list):
        callbacks[:] = [
            callback
            for callback in callbacks
            if not getattr(callback, "_studio_callback", False)
        ]

    class StudioCallback(ProcessingCallback):
        _studio_callback = True

        def on_parse_start(self, file_path: str, parser: str = "", **_: Any) -> None:
            log(f"Started parsing {file_path} with {parser or 'configured parser'}")

        def on_parse_complete(
            self,
            file_path: str,
            content_blocks: int = 0,
            duration_seconds: float | None = None,
            **_: Any,
        ) -> None:
            log(f"Parsed {file_path}: {content_blocks} content blocks")
            if duration_seconds is not None:
                stats.add_duration("parse", duration_seconds)

        def on_text_insert_start(self, file_path: str, **_: Any) -> None:
            log(f"Building text index for {file_path}")

        def on_text_insert_complete(
            self,
            file_path: str,
            duration_seconds: float | None = None,
            **_: Any,
        ) -> None:
            log(f"Text index complete for {file_path}")
            if duration_seconds is not None:
                stats.add_duration("index_insert", duration_seconds)

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

        def on_multimodal_complete(
            self,
            file_path: str,
            duration_seconds: float | None = None,
            **_: Any,
        ) -> None:
            log(f"Multimodal processing complete for {file_path}")
            if duration_seconds is not None:
                stats.add_duration("modal_processing", duration_seconds)

        def on_document_complete(
            self,
            file_path: str,
            duration_seconds: float | None = None,
            **_: Any,
        ) -> None:
            if duration_seconds is not None:
                stats.add_duration("document_total", duration_seconds)

        def on_document_error(self, error: BaseException | str = "", **_: Any) -> None:
            log(f"Document processing error: {error}")

    manager.register(StudioCallback())


def format_traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
