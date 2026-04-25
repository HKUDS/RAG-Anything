from __future__ import annotations

import importlib.util
import shutil
import sys
import time

from fastapi import APIRouter, Depends

from raganything_studio.backend.config import StudioSettings
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.dependencies import get_rag_service, get_settings_store
from raganything_studio.backend.schemas.settings import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    EnvironmentResponse,
    ModelInfo,
    ModelListRequest,
    ModelListResponse,
    SettingsSaveResponse,
    StudioSettingsResponse,
    StudioSettingsUpdate,
)
from raganything_studio.backend.services.raganything_service import RAGAnythingService

router = APIRouter()


@router.get("", response_model=StudioSettingsResponse)
async def get_studio_settings(
    settings_store: SettingsStore = Depends(get_settings_store),
) -> StudioSettingsResponse:
    return _settings_response(settings_store.get())


@router.put("", response_model=SettingsSaveResponse)
async def update_studio_settings(
    payload: StudioSettingsUpdate,
    settings_store: SettingsStore = Depends(get_settings_store),
    rag_service: RAGAnythingService = Depends(get_rag_service),
) -> SettingsSaveResponse:
    updated = settings_store.update(payload)
    rag_service.reset()
    return SettingsSaveResponse(settings=_settings_response(updated))


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    payload: ConnectionTestRequest,
    settings_store: SettingsStore = Depends(get_settings_store),
) -> ConnectionTestResponse:
    """
    Test a provider connection using the values currently in the form
    (may differ from saved settings). Returns ok/latency/error and,
    for embedding, the detected vector dimension.
    """
    saved = settings_store.get()

    # Resolve the API key: use the submitted value when non-empty,
    # otherwise fall back to the already-saved key so the user does
    # not have to re-enter it just to run a test.
    def resolve_key(submitted: str | None, saved_key: str | None) -> str | None:
        return submitted if submitted else saved_key

    try:
        if payload.kind == "llm":
            api_key = resolve_key(payload.api_key, saved.llm_api_key)
            latency = await _test_llm(payload.model, payload.base_url, api_key)
            return ConnectionTestResponse(ok=True, latency_ms=latency)

        if payload.kind == "embedding":
            api_key = resolve_key(payload.api_key, saved.embedding_api_key)
            latency, dim = await _test_embedding(
                payload.model, payload.base_url, api_key,
                payload.embedding_dim, payload.embedding_max_token_size,
            )
            return ConnectionTestResponse(ok=True, latency_ms=latency, detected_dim=dim)

        if payload.kind == "vision":
            api_key = resolve_key(payload.api_key, saved.vision_api_key)
            latency = await _test_vision(payload.model, payload.base_url, api_key)
            return ConnectionTestResponse(ok=True, latency_ms=latency)

        return ConnectionTestResponse(ok=False, error=f"Unknown kind: {payload.kind!r}")

    except Exception as exc:  # noqa: BLE001
        return ConnectionTestResponse(ok=False, error=str(exc))


# ── provider base-URL registry ───────────────────────────────────────────────

PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "aliyun-bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "baidu-qianfan": "https://qianfan.baidubce.com/v2",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot": "https://api.moonshot.cn/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "mistral": "https://api.mistral.ai/v1",
    "anthropic-compatible": "https://api.anthropic.com/v1",
}


@router.post("/list-models", response_model=ModelListResponse)
async def list_models(
    payload: ModelListRequest,
    settings_store: SettingsStore = Depends(get_settings_store),
) -> ModelListResponse:
    """
    Fetch the model list for a provider. Uses the OpenAI-compatible /models
    endpoint which nearly all platforms support. Falls back to saved API key
    when the submitted key is blank.
    """
    saved = settings_store.get()

    # Pick the best saved key across all three roles as fallback
    saved_key = saved.llm_api_key or saved.embedding_api_key or saved.vision_api_key
    api_key = payload.api_key if payload.api_key else saved_key

    base_url = payload.base_url or PROVIDER_BASE_URLS.get(payload.provider)

    try:
        models = await _fetch_models(base_url, api_key)
        return ModelListResponse(ok=True, models=models)
    except Exception as exc:  # noqa: BLE001
        return ModelListResponse(ok=False, error=str(exc))


# ── provider test helpers ─────────────────────────────────────────────────────

async def _test_llm(model: str, base_url: str | None, api_key: str | None) -> float:
    from lightrag.llm.openai import openai_complete_if_cache  # type: ignore[import]

    t0 = time.perf_counter()
    await openai_complete_if_cache(
        model,
        "Reply with the single word: ok",
        system_prompt=None,
        history_messages=[],
        api_key=api_key,
        base_url=base_url,
        max_tokens=4,
    )
    return round((time.perf_counter() - t0) * 1000, 1)


async def _test_embedding(
    model: str,
    base_url: str | None,
    api_key: str | None,
    dim: int,
    max_token_size: int,
) -> tuple[float, int]:
    from lightrag.llm.openai import openai_embed  # type: ignore[import]
    from lightrag.utils import EmbeddingFunc  # type: ignore[import]

    func = EmbeddingFunc(
        embedding_dim=dim,
        max_token_size=max_token_size,
        func=lambda texts: openai_embed.func(
            texts,
            model=model,
            api_key=api_key,
            base_url=base_url,
        ),
    )

    t0 = time.perf_counter()
    vectors = await func(["connection test"])
    latency = round((time.perf_counter() - t0) * 1000, 1)

    detected_dim = len(vectors[0]) if vectors and len(vectors) > 0 else dim
    return latency, detected_dim


async def _test_vision(model: str, base_url: str | None, api_key: str | None) -> float:
    from lightrag.llm.openai import openai_complete_if_cache  # type: ignore[import]

    t0 = time.perf_counter()
    await openai_complete_if_cache(
        model,
        "Reply with the single word: ok",
        system_prompt=None,
        history_messages=[],
        api_key=api_key,
        base_url=base_url,
        max_tokens=4,
    )
    return round((time.perf_counter() - t0) * 1000, 1)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _fetch_models(base_url: str | None, api_key: str | None) -> list[ModelInfo]:
    import httpx

    if not base_url:
        raise ValueError("No base URL configured for this provider")

    url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    raw_models: list[dict] = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(raw_models, list):
        raise ValueError(f"Unexpected response format from {url}")

    return [
        ModelInfo(
            id=m.get("id", ""),
            owned_by=m.get("owned_by", ""),
            context_length=m.get("context_length") or m.get("max_tokens"),
        )
        for m in raw_models
        if m.get("id")
    ]


def _settings_response(current_settings: StudioSettings) -> StudioSettingsResponse:
    return StudioSettingsResponse(
        data_dir=str(current_settings.data_dir),
        upload_dir=str(current_settings.upload_dir),
        working_dir=str(current_settings.working_dir),
        output_dir=str(current_settings.output_dir),
        settings_file=str(current_settings.settings_file),
        llm_provider=current_settings.llm_provider,
        llm_model=current_settings.llm_model,
        llm_base_url=current_settings.llm_base_url,
        llm_api_key_configured=bool(current_settings.llm_api_key),
        embedding_provider=current_settings.embedding_provider,
        embedding_model=current_settings.embedding_model,
        embedding_dim=current_settings.embedding_dim,
        embedding_max_token_size=current_settings.embedding_max_token_size,
        embedding_base_url=current_settings.embedding_base_url,
        embedding_api_key_configured=bool(current_settings.embedding_api_key),
        vision_provider=current_settings.vision_provider,
        vision_model=current_settings.vision_model,
        vision_base_url=current_settings.vision_base_url,
        vision_api_key_configured=bool(current_settings.vision_api_key),
        default_parser=current_settings.default_parser,
        default_parse_method=current_settings.default_parse_method,
        default_language=current_settings.default_language,
        default_device=current_settings.default_device,
    )


@router.get("/environment", response_model=EnvironmentResponse)
async def get_environment() -> EnvironmentResponse:
    return EnvironmentResponse(
        python=sys.version.split()[0],
        raganything_installed=_module_available("raganything"),
        lightrag_installed=_module_available("lightrag"),
        mineru_available=_module_available("mineru"),
        libreoffice_available=shutil.which("libreoffice") is not None,
        cuda_available=_cuda_available(),
    )


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False
