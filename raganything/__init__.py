from .raganything import RAGAnything as RAGAnything
from .config import RAGAnythingConfig as RAGAnythingConfig
from .parser import (
    Parser as Parser,
    register_parser as register_parser,
    unregister_parser as unregister_parser,
    list_parsers as list_parsers,
    get_supported_parsers as get_supported_parsers,
)
from .resilience import (
    retry as retry,
    async_retry as async_retry,
    CircuitBreaker as CircuitBreaker,
)
from .callbacks import (
    ProcessingCallback as ProcessingCallback,
    MetricsCallback as MetricsCallback,
    CallbackManager as CallbackManager,
    ProcessingEvent as ProcessingEvent,
)
from .prompt_manager import (
    set_prompt_language as set_prompt_language,
    get_prompt_language as get_prompt_language,
    reset_prompts as reset_prompts,
    register_prompt_language as register_prompt_language,
    get_available_languages as get_available_languages,
)

__version__ = "1.3.1"
__author__ = "Zirui Guo"
__url__ = "https://github.com/HKUDS/RAG-Anything"

__all__ = [
    "RAGAnything",
    "RAGAnythingConfig",
    "Parser",
    "register_parser",
    "unregister_parser",
    "list_parsers",
    "get_supported_parsers",
    "retry",
    "async_retry",
    "CircuitBreaker",
    "ProcessingCallback",
    "MetricsCallback",
    "CallbackManager",
    "ProcessingEvent",
    "set_prompt_language",
    "get_prompt_language",
    "reset_prompts",
    "register_prompt_language",
    "get_available_languages",
]


def get_version() -> str:
    """Return the RAG-Anything version string."""
    return __version__
