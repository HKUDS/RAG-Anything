#!/usr/bin/env python3
"""
raganything.enhanced_markdown must import without a usable WeasyPrint.

WeasyPrint loads Pango/GObject through cffi when it is imported. If the
package is installed but those system libraries are missing, the import
raises OSError rather than ImportError, which the module's optional-import
guard did not catch, so importing the module failed outright.

The module is executed under a private name with ``import weasyprint``
failing, so the real ``raganything.enhanced_markdown`` in sys.modules is left
untouched for other tests.

Usage:
    pytest tests/test_enhanced_markdown_import_guard.py
"""

import builtins
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "raganything" / "enhanced_markdown.py"
)

# What WeasyPrint raises when GObject cannot be loaded (cffi dlopen failure).
GOBJECT_MISSING = OSError(
    "cannot load library 'gobject-2.0-0': gobject-2.0-0: cannot open shared "
    "object file: No such file or directory"
)


def _load_with_failing_weasyprint(monkeypatch, error):
    real_import = builtins.__import__

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "weasyprint" or name.startswith("weasyprint."):
            raise error
        return real_import(name, globals, locals, fromlist, level)

    spec = importlib.util.spec_from_file_location(
        "_enhanced_markdown_import_guard_probe", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", failing_import)
        spec.loader.exec_module(module)
    return module


def test_module_imports_when_weasyprint_system_libraries_are_missing(
    monkeypatch, tmp_path
):
    module = _load_with_failing_weasyprint(monkeypatch, GOBJECT_MISSING)

    assert module.WEASYPRINT_AVAILABLE is False
    converter = module.EnhancedMarkdownConverter()
    assert converter.available_backends["weasyprint"] is False

    with pytest.raises(RuntimeError) as excinfo:
        converter.convert_with_weasyprint("# Title", str(tmp_path / "out.pdf"))
    message = str(excinfo.value)
    assert "could not load its system libraries" in message
    assert "gobject-2.0-0" in message

    # The public entry point reports failure instead of raising.
    assert (
        converter.convert_markdown_to_pdf(
            "# Title", str(tmp_path / "out.pdf"), method="weasyprint"
        )
        is False
    )


def test_missing_weasyprint_package_keeps_the_install_hint(monkeypatch, tmp_path):
    module = _load_with_failing_weasyprint(
        monkeypatch, ImportError("No module named 'weasyprint'")
    )

    assert module.WEASYPRINT_AVAILABLE is False
    with pytest.raises(RuntimeError) as excinfo:
        module.EnhancedMarkdownConverter().convert_with_weasyprint(
            "# Title", str(tmp_path / "out.pdf")
        )
    assert str(excinfo.value) == (
        "WeasyPrint not available. Install with: pip install weasyprint"
    )
