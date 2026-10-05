"""The parse cache and the incremental batch manifest share one definition."""

from raganything import parse_options
from raganything.processor import _PARSER_CACHE_KWARGS, ProcessorMixin


def test_processor_uses_the_shared_whitelist():
    assert _PARSER_CACHE_KWARGS is parse_options.PARSER_CACHE_KWARGS


def test_processor_normalisation_delegates_to_shared_helper():
    kwargs = {"lang": "en", "include_layout_blocks": False, "unrelated": 1}
    assert ProcessorMixin._relevant_parser_kwargs(kwargs) == {"lang": "en"}
    assert parse_options.relevant_parser_kwargs(kwargs) == {"lang": "en"}
