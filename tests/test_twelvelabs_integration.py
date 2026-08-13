"""
Tests for the TwelveLabs video modality integration.

Two layers:

1. **No-network unit tests** — verify config wiring, processor dispatch, and the
   TwelveLabs processor's request construction (Pegasus analyze + Marengo embed)
   using a fully mocked TwelveLabs client. Heavy deps (lightrag) are stubbed at
   the sys.modules level, mirroring tests/test_minimax_integration.py.

2. **Live smoke test** — gated on TWELVELABS_API_KEY; asserts a real Marengo
   text embedding is 512-dim. Skipped automatically when the key/SDK is absent.
"""

import os
import sys
import types
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Lightweight lightrag stub so raganything.twelvelabs imports without heavy deps
# ---------------------------------------------------------------------------


def _load_raganything_module(name):
    """Load a raganything submodule by file path without running the package
    __init__ (which imports dotenv/lightrag not installed for unit tests)."""
    import importlib.util
    from pathlib import Path

    _ensure_lightrag_stub()
    full = f"raganything.{name}"
    if full in sys.modules:
        return sys.modules[full]

    # Preferred path (CI with full deps installed): normal package import.
    try:
        return importlib.import_module(full)
    except Exception:
        pass

    # Fallback for lean unit-test environments where the package __init__ pulls
    # in heavy deps (dotenv/lightrag) we don't install: load the submodule by
    # file path against a namespace package pointing at the real source dir.
    if "raganything" not in sys.modules:
        pkg = types.ModuleType("raganything")
        pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "raganything")]
        sys.modules["raganything"] = pkg

    mod_path = Path(__file__).resolve().parent.parent / "raganything" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(full, mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_lightrag_stub():
    import importlib.util

    # If a real lightrag is installed (e.g. in CI with `.[all]`), use it as-is.
    if "lightrag" in sys.modules or importlib.util.find_spec("lightrag") is not None:
        return
    lightrag_mod = types.ModuleType("lightrag")
    lightrag_utils = types.ModuleType("lightrag.utils")
    lightrag_lightrag = types.ModuleType("lightrag.lightrag")

    def compute_mdhash_id(content, prefix=""):
        import hashlib

        return prefix + hashlib.md5(str(content).encode()).hexdigest()

    lightrag_utils.compute_mdhash_id = compute_mdhash_id
    lightrag_utils.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    lightrag_utils.get_env_value = lambda key, default, t=str: default

    class _LightRAG:
        pass

    lightrag_lightrag.LightRAG = _LightRAG

    # modalprocessors imports a number of lightrag internals; stub them too.
    lightrag_kg = types.ModuleType("lightrag.kg")
    lightrag_kg_shared = types.ModuleType("lightrag.kg.shared_storage")
    lightrag_kg_shared.get_namespace_data = lambda *a, **k: {}
    lightrag_kg_shared.get_pipeline_status_lock = lambda *a, **k: None
    lightrag_operate = types.ModuleType("lightrag.operate")
    lightrag_operate.extract_entities = lambda *a, **k: []
    lightrag_operate.merge_nodes_and_edges = lambda *a, **k: None

    sys.modules["lightrag"] = lightrag_mod
    sys.modules["lightrag.utils"] = lightrag_utils
    sys.modules["lightrag.lightrag"] = lightrag_lightrag
    sys.modules["lightrag.kg"] = lightrag_kg
    sys.modules["lightrag.kg.shared_storage"] = lightrag_kg_shared
    sys.modules["lightrag.operate"] = lightrag_operate


# ---------------------------------------------------------------------------
# Config + dispatch (no network, no twelvelabs SDK required)
# ---------------------------------------------------------------------------


class TestConfigAndDispatch:
    def test_video_processing_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_VIDEO_PROCESSING", raising=False)
        RAGAnythingConfig = _load_raganything_module("config").RAGAnythingConfig

        cfg = RAGAnythingConfig()
        assert cfg.enable_video_processing is False

    def test_dispatch_routes_video_when_registered(self):
        get_processor_for_type = _load_raganything_module(
            "utils"
        ).get_processor_for_type

        processors = {"generic": object(), "video": object()}
        assert get_processor_for_type(processors, "video") is processors["video"]

    def test_dispatch_falls_back_to_generic_without_video(self):
        get_processor_for_type = _load_raganything_module(
            "utils"
        ).get_processor_for_type

        processors = {"generic": object()}
        # No video processor registered -> generic fallback, never KeyError.
        assert get_processor_for_type(processors, "video") is processors["generic"]


# ---------------------------------------------------------------------------
# Processor request wiring (mocked TwelveLabs client, no network)
# ---------------------------------------------------------------------------

twelvelabs = pytest.importorskip("twelvelabs", reason="twelvelabs SDK not installed")


def _import_tl_module():
    """Import raganything.twelvelabs by file path, bypassing the package
    __init__ (which pulls in dotenv/lightrag we don't install for unit tests)."""
    # twelvelabs.py imports raganything.prompt + raganything.modalprocessors.
    _load_raganything_module("prompt")
    _load_raganything_module("modalprocessors")
    return _load_raganything_module("twelvelabs")


def _make_processor():
    TwelveLabsModalProcessor = _import_tl_module().TwelveLabsModalProcessor

    # Bypass BaseModalProcessor.__init__ (needs a real LightRAG); we only test
    # the TwelveLabs request construction here.
    proc = TwelveLabsModalProcessor.__new__(TwelveLabsModalProcessor)
    proc._client = MagicMock()
    proc.pegasus_model = "pegasus1.5"
    proc.marengo_model = "marengo3.0"
    return proc


class TestProcessorWiring:
    def test_resolve_video_ref_priority(self):
        P = _import_tl_module().TwelveLabsModalProcessor

        assert P._resolve_video_ref({"video_url": "u"}) == ("url", "u")
        assert P._resolve_video_ref({"video_id": "i"}) == ("video_id", "i")
        assert P._resolve_video_ref({"video_path": "p"}) == ("path", "p")
        with pytest.raises(ValueError):
            P._resolve_video_ref({"nope": 1})

    def test_analyze_video_url_wiring(self):
        proc = _make_processor()
        proc._client.analyze.return_value = types.SimpleNamespace(
            data="A person rides a bicycle."
        )
        out = proc._analyze_video("url", "https://x/clip.mp4", "describe")
        assert out == "A person rides a bicycle."
        kwargs = proc._client.analyze.call_args.kwargs
        assert kwargs["model_name"] == "pegasus1.5"
        assert kwargs["prompt"] == "describe"
        assert kwargs["max_tokens"] == 2048
        # video passed as a VideoContext_Url with the right url
        assert getattr(kwargs["video"], "url", None) == "https://x/clip.mp4"

    def test_analyze_video_id_wiring(self):
        proc = _make_processor()
        proc._client.analyze.return_value = types.SimpleNamespace(data="desc")
        proc._analyze_video("video_id", "vid123", "p")
        assert proc._client.analyze.call_args.kwargs["video_id"] == "vid123"

    def test_embed_text_returns_vector(self):
        proc = _make_processor()
        seg = types.SimpleNamespace(float_=[0.1] * 512)
        proc._client.embed.create.return_value = types.SimpleNamespace(
            text_embedding=types.SimpleNamespace(segments=[seg])
        )
        vec = proc.embed_text("a query")
        assert len(vec) == 512
        assert proc._client.embed.create.call_args.kwargs["model_name"] == "marengo3.0"

    def test_embed_video_returns_none_for_bare_id(self):
        proc = _make_processor()
        # A bare video_id has no URL/file to embed -> None, no exception.
        assert proc.embed_video("video_id", "vid123") is None


# ---------------------------------------------------------------------------
# Live smoke test (gated on TWELVELABS_API_KEY)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("TWELVELABS_API_KEY"),
    reason="TWELVELABS_API_KEY not set; skipping live TwelveLabs call",
)
def test_marengo_text_embedding_live():
    from twelvelabs import TwelveLabs

    client = TwelveLabs(api_key=os.environ["TWELVELABS_API_KEY"])
    resp = client.embed.create(
        model_name=os.getenv("TWELVELABS_MARENGO_MODEL", "marengo3.0"),
        text="a person riding a bicycle",
    )
    vec = resp.text_embedding.segments[0].float_
    assert len(vec) == 512
