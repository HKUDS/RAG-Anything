from .raganything import RAGAnything as RAGAnything
from .config import RAGAnythingConfig as RAGAnythingConfig

# Core parser class is always available.
from .parser import Parser as Parser

# Optional: parser plugin APIs (only present in newer versions / when feature PR is merged).
try:
    from .parser import (
        register_parser as register_parser,
        unregister_parser as unregister_parser,
        list_parsers as list_parsers,
        get_supported_parsers as get_supported_parsers,
    )
except ImportError:
    # Older versions without the custom parser registry: keep base import working.
    pass

# Optional: resilience utilities (may not exist in all installations).
try:
    from .resilience import (
        retry as retry,
        async_retry as async_retry,
        CircuitBreaker as CircuitBreaker,
    )
except ModuleNotFoundError:
    # Resilience module not present in this build.
    pass
except ImportError:
    # Symbols not available; ignore to avoid breaking import raganything.
    pass

# Optional: processing callbacks.
try:
    from .callbacks import (
        ProcessingCallback as ProcessingCallback,
        MetricsCallback as MetricsCallback,
        CallbackManager as CallbackManager,
        ProcessingEvent as ProcessingEvent,
    )
except ModuleNotFoundError:
    pass
except ImportError:
    pass

# Optional: audio modal processor (requires faster-whisper).
try:
    from .modalprocessors_audio import (
        AudioModalProcessor as AudioModalProcessor,
        is_audio_file as is_audio_file,
    )
except ImportError:
    # faster-whisper not installed; audio processing unavailable.
    pass

# Optional: video modal processor (requires scenedetect + moviepy + faster-whisper + opencv).
try:
    from .modalprocessors_video import (
        VideoModalProcessor as VideoModalProcessor,
        is_video_file as is_video_file,
    )
except ImportError:
    # Video dependencies not installed; video processing unavailable.
    pass

# Optional: multilingual prompt manager.
try:
    from .prompt_manager import (
        set_prompt_language as set_prompt_language,
        get_prompt_language as get_prompt_language,
        reset_prompts as reset_prompts,
        register_prompt_language as register_prompt_language,
        get_available_languages as get_available_languages,
    )
except ModuleNotFoundError:
    pass
except ImportError:
    pass

__version__ = "1.3.1"
__author__ = "Zirui Guo"
__url__ = "https://github.com/HKUDS/RAG-Anything"

__all__ = [
    "RAGAnything",
    "RAGAnythingConfig",
    "Parser",
]

# Feature-gated exports: only add names that are actually available in this build.
if "register_parser" in globals():
    __all__.extend(
        [
            "register_parser",
            "unregister_parser",
            "list_parsers",
            "get_supported_parsers",
        ]
    )

if "retry" in globals():
    __all__.extend(
        [
            "retry",
            "async_retry",
            "CircuitBreaker",
        ]
    )

if "ProcessingCallback" in globals():
    __all__.extend(
        [
            "ProcessingCallback",
            "MetricsCallback",
            "CallbackManager",
            "ProcessingEvent",
        ]
    )

if "set_prompt_language" in globals():
    __all__.extend(
        [
            "set_prompt_language",
            "get_prompt_language",
            "reset_prompts",
            "register_prompt_language",
            "get_available_languages",
        ]
    )

if "AudioModalProcessor" in globals():
    __all__.extend(
        [
            "AudioModalProcessor",
            "is_audio_file",
        ]
    )

if "VideoModalProcessor" in globals():
    __all__.extend(
        [
            "VideoModalProcessor",
            "is_video_file",
        ]
    )


def get_version() -> str:
    """Return the RAG-Anything version string."""
    return __version__
