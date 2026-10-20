"""Documented vision_model_func examples must send the image's real media type.

Ingested images may be PNG, GIF, WebP, ...; labelling every one image/jpeg
makes strict providers (e.g. Anthropic models via OpenRouter) reject them.
"""

import base64
import importlib.util
import io
import re
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTED = [ROOT / "README.md", ROOT / "README_zh.md"] + sorted(
    (ROOT / "examples").glob("*.py")
)


@pytest.mark.parametrize("path", DOCUMENTED, ids=lambda path: path.name)
def test_examples_do_not_hard_code_jpeg_data_urls(path):
    assert "data:image/jpeg;base64," not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("readme", ["README.md", "README_zh.md"])
def test_readme_vision_snippets_compile(readme):
    text = (ROOT / readme).read_text(encoding="utf-8")
    snippets = [
        block
        for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        if "image_mime_type" in block
    ]
    assert len(snippets) == 4
    for snippet in snippets:
        compile(snippet, readme, "exec")


def _load_modalprocessors_example(monkeypatch):
    path = ROOT / "examples" / "modalprocessors_example.py"
    spec = importlib.util.spec_from_file_location("modalprocessors_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(
        module, "openai_complete_if_cache", lambda *a, **kw: calls.append(kw)
    )
    return module, calls


@pytest.mark.parametrize(
    "image_format,media_type",
    [
        ("PNG", "image/png"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
        ("JPEG", "image/jpeg"),
    ],
)
def test_vision_example_labels_image_with_its_media_type(
    monkeypatch, image_format, media_type
):
    module, calls = _load_modalprocessors_example(monkeypatch)
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format=image_format)
    image_data = base64.b64encode(buffer.getvalue()).decode()

    module.get_vision_model_func("key")("Describe it", image_data=image_data)

    url = calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert url == f"data:{media_type};base64,{image_data}"


def test_vision_example_falls_back_to_jpeg_for_unknown_data(monkeypatch):
    module, calls = _load_modalprocessors_example(monkeypatch)
    image_data = base64.b64encode(b"\x00" * 32).decode()

    module.get_vision_model_func("key")("Describe it", image_data=image_data)

    url = calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert url == f"data:image/jpeg;base64,{image_data}"
