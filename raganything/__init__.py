from .raganything import RAGAnything as RAGAnything
from .config import RAGAnythingConfig as RAGAnythingConfig

__version__ = "1.3.3"
__author__ = "Zirui Guo"
__url__ = "https://github.com/minhnion/RAG-Anything"

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


def get_version() -> str:
    """Return the RAG-Anything version string."""
    return __version__
