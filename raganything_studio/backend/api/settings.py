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
    BrowseDirEntry,
    BrowseDirResponse,
    ConnectionTestRequest,
    ConnectionTestResponse,
    EnvironmentResponse,
    InstallDepRequest,
    InstallDepResponse,
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
            latency = await _test_vision(
                payload.model, payload.base_url, api_key, payload.provider
            )
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
        models = await _fetch_models(
            base_url=base_url,
            api_key=api_key,
            provider=payload.provider,
            kind=payload.kind,
        )
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


async def _test_vision(
    model: str, base_url: str | None, api_key: str | None, provider: str
) -> float:
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

    image_url = (
        "https://cdn.bigmodel.cn/static/logo/register.png"
        if provider == "zhipu"
        else f"data:image/png;base64,{_WHITE_1X1_PNG}"
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
                        "image_url": {"url": image_url},
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
        if resp.status_code >= 400:
            raise ValueError(_provider_error(resp))
    return round((time.perf_counter() - t0) * 1000, 1)


# ── helpers ───────────────────────────────────────────────────────────────────

_VISION_PATTERNS = (
    # explicit vision/multimodal keywords in model ID
    "vl", "vision", "visual", "multimodal", "image",
    # well-known multimodal model families
    "gpt-4o", "gpt-4-turbo", "gpt-4-vision",
    "claude-3", "gemini",
    "glm-4v", "glm-4.5v", "glm-z1",  # Zhipu VL models
    "qwen-vl", "qwen2-vl",        # Alibaba VL
    "internvl", "minicpm-v",
    "llava", "bakllava",
    "pixtral",
    "phi-3-vision",
)

_ZHIPU_CURATED_MODELS: dict[str, list[ModelInfo]] = {
    "vision": [
        ModelInfo(id="glm-4.5v", owned_by="Zhipu", context_length=65536, vision_capable=True),
        ModelInfo(id="glm-4v-plus-0111", owned_by="Zhipu", context_length=16384, vision_capable=True),
        ModelInfo(id="glm-4v-plus", owned_by="Zhipu", context_length=16384, vision_capable=True),
    ],
    "llm": [
        ModelInfo(id="glm-4.5", owned_by="Zhipu", context_length=131072),
        ModelInfo(id="glm-4.5-air", owned_by="Zhipu", context_length=131072),
        ModelInfo(id="glm-4-plus", owned_by="Zhipu", context_length=131072),
        ModelInfo(id="glm-4-air-250414", owned_by="Zhipu", context_length=131072),
        ModelInfo(id="glm-4-flash-250414", owned_by="Zhipu", context_length=131072),
    ],
}


def _is_vision_capable(model_id: str) -> bool:
    lower = model_id.lower()
    return any(pat in lower for pat in _VISION_PATTERNS)


async def _fetch_models(
    base_url: str | None,
    api_key: str | None,
    provider: str,
    kind: str | None,
) -> list[ModelInfo]:
    import httpx

    if not base_url:
        raise ValueError("No base URL configured for this provider")

    if provider == "zhipu" and kind in _ZHIPU_CURATED_MODELS:
        curated = _ZHIPU_CURATED_MODELS[kind]
    else:
        curated = []

    url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                raise ValueError(_provider_error(response))
            data = response.json()
    except Exception:
        if curated:
            return curated
        raise

    raw_models: list[dict] = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(raw_models, list):
        raise ValueError(f"Unexpected response format from {url}")

    fetched = [
        ModelInfo(
            id=m.get("id", ""),
            owned_by=m.get("owned_by", ""),
            context_length=m.get("context_length") or m.get("max_tokens"),
            vision_capable=_is_vision_capable(m.get("id", "")),
        )
        for m in raw_models
        if m.get("id")
    ]

    merged = _merge_model_lists(curated, fetched)
    if kind == "vision":
        vision_models = [model for model in merged if model.vision_capable]
        return vision_models or curated
    return merged


def _merge_model_lists(
    preferred: list[ModelInfo], fetched: list[ModelInfo]
) -> list[ModelInfo]:
    seen: set[str] = set()
    merged: list[ModelInfo] = []
    for model in [*preferred, *fetched]:
        if model.id in seen:
            continue
        seen.add(model.id)
        merged.append(model)
    return merged


def _provider_error(response: object) -> str:
    text = getattr(response, "text", "")
    try:
        data = response.json()  # type: ignore[attr-defined]
    except Exception:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)
        message = data.get("message") or data.get("msg")
        if message:
            return str(message)
    status_code = getattr(response, "status_code", "HTTP error")
    return f"{status_code}: {text[:300]}"


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
        default_enable_vlm_enhancement=(
            current_settings.default_enable_vlm_enhancement
        ),
        max_concurrent_files=current_settings.max_concurrent_files,
        default_processing_preset=current_settings.default_processing_preset,
        default_enable_parse_cache=current_settings.default_enable_parse_cache,
        default_enable_modal_cache=current_settings.default_enable_modal_cache,
        default_preview_mode=current_settings.default_preview_mode,
        embedding_batch_size=current_settings.embedding_batch_size,
        llm_max_concurrency=current_settings.llm_max_concurrency,
        vlm_max_concurrency=current_settings.vlm_max_concurrency,
        embedding_max_concurrency=current_settings.embedding_max_concurrency,
        retry_max_attempts=current_settings.retry_max_attempts,
        retry_base_delay=current_settings.retry_base_delay,
        retry_max_delay=current_settings.retry_max_delay,
        write_lock_enabled=current_settings.write_lock_enabled,
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
        docling_available=_module_available("docling"),
        paddleocr_available=_module_available("paddleocr"),
        libreoffice_available=shutil.which("libreoffice") is not None,
        cuda_gpu_present=_nvidia_gpu_present(),
        cuda_available=_cuda_available(),
        mps_available=_mps_available(),
    )


@router.get("/browse-dir", response_model=BrowseDirResponse)
async def browse_dir(path: str = "") -> BrowseDirResponse:
    """
    List subdirectories (and files) at the given server-side absolute path.
    Defaults to the user's home directory when path is empty.
    Only used by the Settings directory picker — does not expose file contents.
    """
    import os

    base = os.path.expanduser(path) if path else os.path.expanduser("~")
    base = os.path.abspath(base)

    if not os.path.isdir(base):
        base = os.path.dirname(base)

    try:
        raw = os.listdir(base)
    except PermissionError:
        raw = []

    entries: list[BrowseDirEntry] = []
    for name in sorted(raw, key=lambda n: (not os.path.isdir(os.path.join(base, n)), n.lower())):
        if name.startswith("."):
            continue
        full = os.path.join(base, name)
        entries.append(BrowseDirEntry(name=name, path=full, is_dir=os.path.isdir(full)))

    parent = os.path.dirname(base) if base != os.path.dirname(base) else None
    return BrowseDirResponse(path=base, parent=parent, entries=entries)


@router.post("/install-dep", response_model=InstallDepResponse)
async def install_dep(payload: InstallDepRequest) -> InstallDepResponse:
    """
    Run `pip install <package>` in the current Python environment.
    Returns combined stdout/stderr. Runs synchronously (blocks the request)
    so the frontend can poll/wait for completion — installs are typically
    under 60 s for small packages.
    """
    import asyncio
    import subprocess

    # Whitelist: only known safe package targets
    _ALLOWED = {
        "docling", "mineru[core]", "mineru", "paddleocr",
        "paddlepaddle", "paddlepaddle-gpu",
        "torch", "torchvision", "torchaudio",
    }
    if payload.package not in _ALLOWED:
        return InstallDepResponse(
            ok=False, output="",
            error=f"Package '{payload.package}' is not in the allowed install list.",
        )

    cmd = [sys.executable, "-m", "pip", "install", payload.package, "--progress-bar", "off"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        output = stdout.decode(errors="replace")
        ok = proc.returncode == 0
        return InstallDepResponse(ok=ok, output=output, error=None if ok else "pip exited with non-zero status")
    except asyncio.TimeoutError:
        return InstallDepResponse(ok=False, output="", error="Installation timed out after 5 minutes")
    except Exception as exc:  # noqa: BLE001
        return InstallDepResponse(ok=False, output="", error=str(exc))


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _nvidia_gpu_present() -> bool:
    """Return True if an NVIDIA GPU is detected via nvidia-smi or nvcc."""
    return shutil.which("nvidia-smi") is not None or shutil.which("nvcc") is not None


def _cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _mps_available() -> bool:
    """Return True on Apple Silicon Macs where MPS acceleration is usable."""
    import platform
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False
    try:
        import torch
        return bool(torch.backends.mps.is_available())
    except Exception:
        return True  # arm64 macOS without torch — hardware is capable
