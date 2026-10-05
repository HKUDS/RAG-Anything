"""Parser options that change a persisted parse result.

Shared by the parse cache (``processor``) and the incremental batch manifest
(``batch_parser``) so both agree on what counts as "the same configuration".
Kept free of heavy imports because ``batch_parser`` is used standalone.
"""

from typing import Any, Dict

PARSER_CACHE_KWARGS = frozenset(
    {
        "lang",
        "device",
        "start_page",
        "end_page",
        "formula",
        "table",
        "backend",
        "source",
        "include_layout_blocks",
    }
)


def relevant_parser_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Return parser options that change the persisted parse result."""
    return {
        key: value
        for key, value in kwargs.items()
        if key in PARSER_CACHE_KWARGS
        and not (key == "include_layout_blocks" and not value)
    }
