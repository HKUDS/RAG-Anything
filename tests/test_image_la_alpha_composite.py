"""LA (greyscale+alpha) images must composite onto white using the alpha mask."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _load_mineru_parser_class():
    module_path = Path(__file__).resolve().parents[1] / "raganything" / "parser.py"
    spec = importlib.util.spec_from_file_location("_raganything_parser_la", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.MineruParser


MineruParser = _load_mineru_parser_class()


def test_la_semi_transparent_black_composites_to_gray():
    img = Image.new("LA", (1, 1), (0, 128))
    composited = MineruParser._prepare_image_for_mineru(img)
    assert composited.mode == "RGB"
    assert composited.getpixel((0, 0)) == (127, 127, 127)


def test_rgba_semi_transparent_black_still_composites_to_gray():
    img = Image.new("RGBA", (1, 1), (0, 0, 0, 128))
    composited = MineruParser._prepare_image_for_mineru(img)
    assert composited.getpixel((0, 0)) == (127, 127, 127)


def test_opaque_rgb_passthrough():
    img = Image.new("RGB", (1, 1), (10, 20, 30))
    out = MineruParser._prepare_image_for_mineru(img)
    assert out.getpixel((0, 0)) == (10, 20, 30)
