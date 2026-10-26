"""Parser options that change a persisted parse result.

Shared by the parse cache (``processor``) and the incremental batch manifest
(``batch_parser``) so both agree on what counts as "the same configuration".
Kept free of heavy imports because ``batch_parser`` is used standalone.
"""

import hashlib
from os import PathLike, fsdecode
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
        "vlm_url",
        "include_layout_blocks",
        "table_mode",
        "tables",
        "allow_ocr",
        "artifacts_path",
        "cls",
    }
)


def relevant_parser_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Return parser options that change the persisted parse result."""
    relevant = {
        key: value
        for key, value in kwargs.items()
        if key in PARSER_CACHE_KWARGS
        and not (key == "include_layout_blocks" and not value)
    }
    # Docling accepts pathlib paths for its model directory; cache identities
    # must remain JSON-serializable and agree with the equivalent string path.
    if isinstance(relevant.get("artifacts_path"), PathLike):
        relevant["artifacts_path"] = fsdecode(relevant["artifacts_path"])
    # A VLM server URL can embed credentials; the parse cache persists its
    # identity, so it keys on a digest instead of the URL itself.
    if isinstance(relevant.get("vlm_url"), str) and relevant["vlm_url"]:
        digest = hashlib.sha256(relevant["vlm_url"].encode("utf-8")).hexdigest()
        relevant["vlm_url"] = f"sha256:{digest}"
    return relevant
