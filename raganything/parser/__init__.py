"""
RAG-Anything Parser Sub-Package.

Provides document parsing engines: MinerU, Docling, Marker, PaddleOCR.
Public API: get_parser(), register_parser(), SUPPORTED_PARSERS, Parser base class.
"""

# ── Re-exports from sub-modules ─────────────────────────────────────
from .base import (
    _IS_WINDOWS,
    MineruExecutionError,
    Parser,
)
from .pdf_parser import MineruParser
from .office_parser import DoclingParser
from .markdown_parser import MarkerParser
from .image_parser import PaddleOCRParser

# ── Parser registry ──────────────────────────────────────────────────

_CUSTOM_PARSERS: dict = {}

SUPPORTED_PARSERS = ("mineru", "docling", "paddleocr", "marker", "opendataloader")

# Lazy imports for optional-dependency parsers — the wrapped getter
# returns a fresh instance per call so config (timeout / heap / limits)
# is never accidentally shared across documents.
_ODL_PARSER_CLASS = None


def _get_odl_parser():
    """Return an OpenDataLoaderParser instance (lazy import)."""
    global _ODL_PARSER_CLASS
    if _ODL_PARSER_CLASS is None:
        from raganything.parser.opendataloader_parser import OpenDataLoaderParser
        _ODL_PARSER_CLASS = OpenDataLoaderParser
    return _ODL_PARSER_CLASS()


def _normalize_parser_name(name: str) -> str:
    """Normalize and validate a parser name for registry APIs."""
    if not isinstance(name, str):
        raise TypeError(
            f"parser name must be a non-empty string, got {type(name).__name__}"
        )
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("parser name must be a non-empty string")
    return normalized


def register_parser(name: str, parser_class: type) -> None:
    """Register a custom parser class for use with RAGAnything.

    This enables the Bring-Your-Own-Parser pattern: users can integrate
    any document parser (e.g., Marker, Unstructured, Surya) by subclassing
    ``Parser`` and registering it here.

    Args:
        name: Unique identifier for the parser (e.g., "marker", "surya").
              Must not collide with built-in names ("mineru", "docling", "paddleocr").
        parser_class: A subclass of ``Parser`` that implements at least
                      ``parse_document``, ``check_installation``, and
                      optionally ``parse_pdf``, ``parse_image``, ``parse_office_doc``.

    Raises:
        TypeError: If *parser_class* is not a subclass of ``Parser``.
        ValueError: If *name* collides with a built-in parser name.

    Example::

        from raganything.parser import Parser, register_parser

        class MarkerParser(Parser):
            def check_installation(self) -> bool:
                try:
                    import marker
                    return True
                except ImportError:
                    return False

            def parse_pdf(self, pdf_path, output_dir="./output", method="auto", **kw):
                import marker
                # ... your implementation ...
                return content_list

            def parse_document(self, file_path, output_dir="./output", method="auto", **kw):
                return self.parse_pdf(pdf_path=file_path, output_dir=output_dir, method=method, **kw)

        register_parser("marker", MarkerParser)
    """
    normalized_name = _normalize_parser_name(name)
    if not isinstance(parser_class, type) or not issubclass(parser_class, Parser):
        raise TypeError(
            f"parser_class must be a subclass of Parser, got {parser_class!r}"
        )
    _BUILTIN_NAMES = {"mineru", "docling", "paddleocr", "marker"}
    if normalized_name in _BUILTIN_NAMES:
        raise ValueError(
            f"Cannot override built-in parser '{normalized_name}'. "
            f"Choose a different name for your custom parser."
        )
    _CUSTOM_PARSERS[normalized_name] = parser_class
    Parser.logger.info(
        "Registered custom parser: '%s' -> %s", normalized_name, parser_class.__name__
    )


def unregister_parser(name: str) -> None:
    """Remove a previously registered custom parser.

    Args:
        name: The parser name to remove.

    Raises:
        TypeError: If *name* is not a string.
        ValueError: If *name* is empty or only whitespace.
        KeyError: If no custom parser with that name is registered.
    """
    normalized_name = _normalize_parser_name(name)
    if normalized_name not in _CUSTOM_PARSERS:
        raise KeyError(f"No custom parser registered with name '{normalized_name}'")
    del _CUSTOM_PARSERS[normalized_name]
    Parser.logger.info("Unregistered custom parser: '%s'", normalized_name)


def list_parsers() -> dict:
    """Return a dict mapping every available parser name to its class name."""
    result = {}
    for name in SUPPORTED_PARSERS:
        try:
            p = get_parser(name)
            result[name] = type(p).__name__
        except Exception:
            result[name] = "unknown"
    for name, cls in _CUSTOM_PARSERS.items():
        result[name] = cls.__name__
    return result


def get_supported_parsers() -> tuple:
    """Return a tuple of all supported parser names (built-in + custom)."""
    return tuple(list(SUPPORTED_PARSERS) + list(_CUSTOM_PARSERS.keys()))


def get_parser(parser_type: str) -> Parser:
    """Factory: return a parser instance by name.

    Args:
        parser_type: One of ``"mineru"``, ``"docling"``, ``"paddleocr"``,
            ``"marker"``, or a custom registered name.

    Returns:
        A :class:`Parser` instance.

    Raises:
        ValueError: If *parser_type* is not a recognised parser name.
    """
    pt = parser_type.strip().lower()
    if pt == "mineru":
        return MineruParser()
    if pt == "docling":
        return DoclingParser()
    if pt == "paddleocr":
        return PaddleOCRParser()
    if pt == "marker":
        return MarkerParser()
    if pt == "opendataloader":
        return _get_odl_parser()
    if pt in _CUSTOM_PARSERS:
        return _CUSTOM_PARSERS[pt]()
    raise ValueError(
        f"Unsupported parser type: {parser_type}. Supported: "
        + ", ".join(get_supported_parsers())
    )


# ── CLI entry point ──────────────────────────────────────────────────


def main():
    """Run a parser from the command line.

    Usage::

        python -m raganything.parser <file_path> [--parser mineru]
    """
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(
        description="RAG-Anything document parser CLI"
    )
    ap.add_argument(
        "file_path", help="Path to the document file to parse"
    )
    ap.add_argument(
        "--parser",
        default="docling",
        help="Parser engine to use (default: docling)",
    )
    args = ap.parse_args()

    if hasattr(args, "list_parsers") and args.list_parsers:
        print("Available parsers:")
        for name, cls_name in list_parsers().items():
            print(f"  {name:<20} → {cls_name}")
        return 0

    try:
        parser = get_parser(args.parser)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    import asyncio

    if not asyncio.iscoroutinefunction(parser.parse_document):
        result = parser.parse_document(args.file_path, output_dir=".")
    else:
        result = asyncio.run(parser.parse_document(args.file_path, output_dir="."))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    import json
    sys.exit(main())
