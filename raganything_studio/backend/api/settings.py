from __future__ import annotations

import importlib.util
import shutil
import sys
import time

from fastapi import APIRouter, Depends

from raganything_studio.backend.config import (
    ModelChannelConfig,
    ModelProviderProfile,
    StudioSettings,
)
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.dependencies import get_rag_service, get_settings_store
from raganything_studio.backend.schemas.settings import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    EnvironmentResponse,
    ModelInfo,
    ModelChannelResponse,
    ModelListRequest,
    ModelListResponse,
    ModelProfileResponse,
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
    def resolve_key(
        submitted: str | None, saved_key: str | None
    ) -> str | None:
        return submitted if submitted else saved_key

    saved_profile = _profile_for_request(saved, payload.profile_id)

    try:
        if payload.kind == "llm":
            api_key = resolve_key(payload.api_key, saved_profile.llm.api_key)
            latency = await _test_llm(payload.model, payload.base_url, api_key)
            return ConnectionTestResponse(ok=True, latency_ms=latency)

        if payload.kind == "embedding":
            api_key = resolve_key(payload.api_key, saved_profile.embedding.api_key)
            latency, dim = await _test_embedding(
                payload.model, payload.base_url, api_key,
                payload.embedding_dim, payload.embedding_max_token_size,
            )
            return ConnectionTestResponse(ok=True, latency_ms=latency, detected_dim=dim)

        if payload.kind == "vision":
            api_key = resolve_key(payload.api_key, saved_profile.vision.api_key)
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
    profile = _profile_for_request(saved, None)
    saved_key = (
        profile.llm.api_key
        or profile.embedding.api_key
        or profile.vision.api_key
        or saved.llm_api_key
        or saved.embedding_api_key
        or saved.vision_api_key
    )
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

    t0 = time.perf_counter()
    vectors = await openai_embed.func(
        ["connection test"],
        model=model,
        api_key=api_key,
        base_url=base_url,
        embedding_dim=dim,
        max_token_size=max_token_size,
    )
    latency = round((time.perf_counter() - t0) * 1000, 1)

    if hasattr(vectors, "shape") and len(vectors.shape) >= 2:
        detected_dim = int(vectors.shape[1])
    else:
        detected_dim = len(vectors[0]) if len(vectors) > 0 else dim
    return latency, detected_dim


async def _test_vision(model: str, base_url: str | None, api_key: str | None) -> float:
    """
    Test a vision model with a real multimodal message containing a 1×1 white PNG.
    Plain text-only calls are rejected by most VLM endpoints (including Zhipu GLM-4V)
    with InvalidResponseError because they require an image content block.
    """
    import httpx

    if not base_url:
        raise ValueError("No base URL configured for the vision provider")

    # 1×1 white PNG, base64-encoded — smallest valid image that exercises the vision path
    _WHITE_1X1_PNG = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )

    payload = {
        "model": model,
        "max_tokens": 4,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_WHITE_1X1_PNG}"},
                    },
                    {"type": "text", "text": "Reply with the single word: ok"},
                ],
            }
        ],
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = base_url.rstrip("/") + "/chat/completions"
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    return round((time.perf_counter() - t0) * 1000, 1)


# ── helpers ───────────────────────────────────────────────────────────────────

_VISION_PATTERNS = (
    # explicit vision/multimodal keywords in model ID
    "vl", "vision", "visual", "multimodal", "image",
    # well-known multimodal model families
    "gpt-4o", "gpt-4-turbo", "gpt-4-vision",
    "claude-3", "gemini",
    "glm-4v", "glm-z1",           # Zhipu VL models
    "qwen-vl", "qwen2-vl",        # Alibaba VL
    "internvl", "minicpm-v",
    "llava", "bakllava",
    "pixtral",
    "phi-3-vision",
)


def _is_vision_capable(model_id: str) -> bool:
    lower = model_id.lower()
    return any(pat in lower for pat in _VISION_PATTERNS)


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
            vision_capable=_is_vision_capable(m.get("id", "")),
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
        active_profile_id=current_settings.active_profile_id,
        profiles=[
            _profile_response(profile) for profile in current_settings.profiles
        ],
    )


def _profile_for_request(
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
    return ModelProviderProfile(
        id="default",
        name="Default RAG Profile",
        llm=ModelChannelConfig(
            provider=settings.llm_provider,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        ),
        embedding=ModelChannelConfig(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            embedding_dim=settings.embedding_dim,
            embedding_max_token_size=settings.embedding_max_token_size,
        ),
        vision=ModelChannelConfig(
            provider=settings.vision_provider,
            model=settings.vision_model,
            base_url=settings.vision_base_url,
            api_key=settings.vision_api_key,
        ),
    )


def _profile_response(profile: ModelProviderProfile) -> ModelProfileResponse:
    return ModelProfileResponse(
        id=profile.id,
        name=profile.name,
        llm=_channel_response(profile.llm),
        embedding=_channel_response(profile.embedding),
        vision=_channel_response(profile.vision),
    )


def _channel_response(channel: ModelChannelConfig) -> ModelChannelResponse:
    return ModelChannelResponse(
        provider=channel.provider,
        model=channel.model,
        base_url=channel.base_url,
        api_key_configured=bool(channel.api_key),
        embedding_dim=channel.embedding_dim,
        embedding_max_token_size=channel.embedding_max_token_size,
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
