"""Documented vision_model_func examples must send the image's real media type.

Ingested images may be PNG, GIF, WebP, ...; labelling every one image/jpeg
makes strict providers (e.g. Anthropic models via OpenRouter) reject them.
"""

import ast
import base64
import importlib.util
import io
import re
from pathlib import Path

import pytest

from raganything.image_signature import image_mime_type

Image = pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTED = (
    [ROOT / "README.md", ROOT / "README_zh.md"]
    + sorted((ROOT / "examples").glob("*.py"))
    + sorted((ROOT / "reproduce").glob("*.py"))
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


def _image_base64(image_format):
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode()


def _data_url_sources():
    """Every documented Python source (file or README snippet) that builds an
    image data URL, with its data URL f-strings and mime_type expressions."""
    sources = []
    for path in DOCUMENTED:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".md":
            blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        else:
            blocks = [text]
        for index, block in enumerate(blocks):
            if "data:" not in block:
                continue
            tree = ast.parse(block)
            urls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.JoinedStr)
                and node.values
                and isinstance(node.values[0], ast.Constant)
                and str(node.values[0].value).startswith("data:")
            ]
            mime_types = [
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "mime_type"
                    for target in node.targets
                )
            ]
            if urls:
                name = f"{path.name}-{index}" if path.suffix == ".md" else path.name
                sources.append(pytest.param(path.name, urls, mime_types, id=name))
    return sources


DATA_URL_SOURCES = _data_url_sources()


def test_every_documented_vision_function_is_checked():
    names = [param.values[0] for param in DATA_URL_SOURCES]
    assert names.count("README.md") == 4
    assert names.count("README_zh.md") == 4
    assert {
        "raganything_example.py",
        "modalprocessors_example.py",
        "insert_content_list_example.py",
        "index.py",
        "query.py",
    } <= set(names)


@pytest.mark.parametrize("name,urls,mime_types", DATA_URL_SOURCES)
def test_documented_data_urls_use_the_detected_media_type(name, urls, mime_types):
    for url in urls:
        assert ast.unparse(url) == "f'data:{mime_type};base64,{image_data}'", name
    assert mime_types, name
    images = [
        (_image_base64(image_format), media_type)
        for image_format, media_type in [
            ("PNG", "image/png"),
            ("GIF", "image/gif"),
            ("WEBP", "image/webp"),
            ("JPEG", "image/jpeg"),
        ]
    ] + [(base64.b64encode(b"\x00" * 32).decode(), "image/jpeg")]
    for expression in mime_types:
        code = compile(ast.Expression(expression), "<mime_type>", "eval")
        for image_data, media_type in images:
            namespace = {
                "base64": base64,
                "image_mime_type": image_mime_type,
                "image_data": image_data,
            }
            assert eval(code, namespace) == media_type, name


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
    image_data = _image_base64(image_format)

    module.get_vision_model_func("key")("Describe it", image_data=image_data)

    url = calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert url == f"data:{media_type};base64,{image_data}"


def test_vision_example_falls_back_to_jpeg_for_unknown_data(monkeypatch):
    module, calls = _load_modalprocessors_example(monkeypatch)
    image_data = base64.b64encode(b"\x00" * 32).decode()

    module.get_vision_model_func("key")("Describe it", image_data=image_data)

    url = calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert url == f"data:image/jpeg;base64,{image_data}"
