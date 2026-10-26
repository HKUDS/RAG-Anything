"""Retrieved image paths must be found in the prompt LightRAG really builds.

LightRAG 1.4.x json.dumps every retrieved chunk into the prompt, so the
newline after ``Image Path: <path>`` reaches RAG-Anything as the two
characters backslash and ``n``, not as a line break. Hand-written prompts
with real newlines hide that, so these tests build the prompt with
LightRAG's own context builders: ``naive_query`` for naive mode and
``_build_context_str`` for the knowledge-graph modes such as mix. Chunk
content uses RAG-Anything's own ``image_chunk`` template.
"""

import base64
import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from lightrag.base import QueryParam
from lightrag.operate import _build_context_str, naive_query
from lightrag.utils import Tokenizer

import raganything.query as query_module
from raganything.prompt import PROMPTS
from raganything.query import QueryMixin

Image = pytest.importorskip("PIL.Image")

QUESTION = "What does the figure show?"
MODES = ["naive", "mix"]


class _CharTokenizer:
    """One token per character, enough for LightRAG's token budgeting."""

    def encode(self, content):
        return [ord(char) for char in content]

    def decode(self, tokens):
        return "".join(chr(token) for token in tokens)


def _unused_llm(*args, **kwargs):
    raise AssertionError("building the prompt must not call the LLM")


class _ChunksVDB:
    cosine_better_than_threshold = 0.2

    def __init__(self, contents):
        self._contents = contents

    async def query(self, query, top_k, query_embedding=None):
        return [
            {"id": f"chunk-{i}", "content": content, "file_path": "report.pdf"}
            for i, content in enumerate(self._contents)
        ]


async def _lightrag_prompt(mode, contents):
    """Return the retrieval prompt or context LightRAG builds for ``contents``."""
    global_config = {
        "tokenizer": Tokenizer("char", _CharTokenizer()),
        "llm_model_func": _unused_llm,
        "max_total_tokens": 1_000_000,
    }
    param = QueryParam(
        mode=mode,
        only_need_prompt=True,
        enable_rerank=False,
        max_total_tokens=1_000_000,
    )
    if mode == "naive":
        result = await naive_query(QUESTION, _ChunksVDB(contents), param, global_config)
        return result.content
    chunks = [
        {"content": content, "file_path": "report.pdf", "chunk_id": f"chunk-{i}"}
        for i, content in enumerate(contents)
    ]
    entities = [
        {
            "entity": "Quarterly revenue chart",
            "type": "image",
            "description": "Bar chart of revenue per quarter.",
            "file_path": "report.pdf",
        }
    ]
    context, _ = await _build_context_str(
        entities, [], chunks, QUESTION, param, global_config
    )
    return context


def _image_chunk(image_path):
    return PROMPTS["image_chunk"].format(
        section_path="Results",
        neighbor_text="Revenue grew in the third quarter.",
        image_path=image_path,
        captions="Figure 1: Quarterly revenue",
        footnotes="None",
        enhanced_caption="A bar chart of revenue per quarter.",
    )


def _save_png(path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), color).save(path, format="PNG")
    return path.read_bytes()


def _make_query(tmp_path, prompt):
    query = QueryMixin()
    query.logger = logging.getLogger(__name__)
    query.config = SimpleNamespace(
        working_dir=str(tmp_path), parser_output_dir=str(tmp_path)
    )
    query._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    query.lightrag = SimpleNamespace(
        aquery=AsyncMock(side_effect=[prompt, "text answer"])
    )
    query.vision_model_func = AsyncMock(return_value="vision answer")
    return query


def _sent_images(query):
    """Decoded bytes of every image part passed to the vision model."""
    if not query.vision_model_func.await_count:
        return []
    messages = query.vision_model_func.await_args.kwargs["messages"]
    return [
        base64.b64decode(part["image_url"]["url"].split(",", 1)[1], validate=True)
        for part in messages[1]["content"]
        if part["type"] == "image_url"
    ]


@pytest.fixture
def validated_paths(monkeypatch):
    """Record every captured path handed to the real validate_image_file."""
    seen = []
    real_validate = query_module.validate_image_file

    def recording_validate(image_path, *args, **kwargs):
        seen.append(image_path)
        return real_validate(image_path, *args, **kwargs)

    monkeypatch.setattr(query_module, "validate_image_file", recording_validate)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_lightrag_prompt_escapes_newline_after_image_path(tmp_path, mode):
    image_path = tmp_path / "figure.png"
    prompt = await _lightrag_prompt(mode, [_image_chunk(str(image_path))])

    assert f"Image Path: {image_path}\\nCaptions:" in prompt
    assert f"Image Path: {image_path}\n" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["aquery", "aquery_vlm_enhanced"])
@pytest.mark.parametrize("mode", MODES)
async def test_lowercase_image_path_reaches_vision_model(
    tmp_path, validated_paths, mode, entrypoint
):
    image_path = tmp_path / "figure.png"
    original = _save_png(image_path)
    prompt = await _lightrag_prompt(mode, [_image_chunk(str(image_path))])
    query = _make_query(tmp_path, prompt)

    assert await getattr(query, entrypoint)(QUESTION, mode=mode) == "vision answer"
    assert _sent_images(query) == [original]
    assert validated_paths == [str(image_path)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_uppercase_extension_reaches_vision_model(
    tmp_path, validated_paths, mode
):
    image_path = tmp_path / "Figure.PNG"
    original = _save_png(image_path)
    prompt = await _lightrag_prompt(mode, [_image_chunk(str(image_path))])
    query = _make_query(tmp_path, prompt)

    assert await query.aquery(QUESTION, mode=mode) == "vision answer"
    assert _sent_images(query) == [original]
    assert validated_paths == [str(image_path)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_backup_suffix_is_not_shortened_to_existing_image(
    tmp_path, validated_paths, mode
):
    prefix = tmp_path / "figure.png"
    _save_png(prefix, "red")
    other = tmp_path / "other.png"
    other_bytes = _save_png(other, "blue")
    prompt = await _lightrag_prompt(
        mode, [_image_chunk(f"{prefix}.backup"), _image_chunk(str(other))]
    )
    query = _make_query(tmp_path, prompt)

    assert await query.aquery(QUESTION, mode=mode) == "vision answer"
    assert _sent_images(query) == [other_bytes]
    assert str(prefix) not in validated_paths
    assert validated_paths == [str(other)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_path_with_spaces_and_parentheses_reaches_vision_model(
    tmp_path, validated_paths, mode
):
    image_path = tmp_path / "Q3 report (final)" / "chart (1) v2.png"
    original = _save_png(image_path)
    prompt = await _lightrag_prompt(mode, [_image_chunk(str(image_path))])
    query = _make_query(tmp_path, prompt)

    assert await query.aquery(QUESTION, mode=mode) == "vision answer"
    assert _sent_images(query) == [original]
    assert validated_paths == [str(image_path)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_captured_path_outside_safe_dirs_is_still_blocked(
    tmp_path, tmp_path_factory, monkeypatch, validated_paths, mode
):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path_factory.mktemp("outside") / "secret.png"
    _save_png(outside)
    prompt = await _lightrag_prompt(mode, [_image_chunk(str(outside))])
    query = _make_query(tmp_path, prompt)

    assert await query.aquery(QUESTION, mode=mode) == "text answer"
    assert _sent_images(query) == []
    assert validated_paths == [str(outside)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "following",
    [
        "\nCaptions: x",
        "\r\nCaptions: x",
        "\tCaptions: x",
        " (see caption)",
        "",
        '" said the caption',
        "\fx",
        "\x0bx",
        "\x1fx",
        ". Next sentence",
        ", next",
        "; next",
        ": next",
        ") next",
        "]\nCaptions: x",
        ".",
    ],
    ids=[
        "newline",
        "crlf",
        "tab",
        "space",
        "end-of-content",
        "quote",
        "form-feed",
        "vertical-tab",
        "unit-separator",
        "period-space",
        "comma",
        "semicolon",
        "colon",
        "close-paren",
        "close-bracket-newline",
        "period-end-of-content",
    ],
)
async def test_capture_stops_at_delimiter(tmp_path, validated_paths, mode, following):
    image_path = tmp_path / "figure.png"
    _save_png(image_path)
    content = f"Image Path: {image_path}{following}"
    prompt = await _lightrag_prompt(mode, [content])
    query = _make_query(tmp_path, prompt)

    enhanced, count = await query._process_image_paths_for_vlm(prompt)

    assert count == 1
    assert validated_paths == [str(image_path)]
    # Everything after the path (any punctuation, then the JSON escape or
    # closing quote) is kept right after the image marker.
    escaped_rest = prompt.split(f"Image Path: {image_path}", 1)[1]
    assert escaped_rest.startswith(json.dumps(following)[1:-1] + '"')
    assert f"Image Path: {image_path}\n[VLM_IMAGE_1]{escaped_rest}" in enhanced


def _table_chunk(table_img_path):
    return PROMPTS["table_chunk"].format(
        table_img_path=table_img_path,
        table_caption="Table 1",
        table_body="| quarter | revenue |",
        table_footnote="None",
        enhanced_caption="A table of revenue per quarter.",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "invalid_first",
    [
        lambda tmp_path: _image_chunk(str(tmp_path / "diagram.svg")),
        lambda tmp_path: _table_chunk(""),
        lambda tmp_path: _image_chunk(f"{tmp_path / 'figure.png'}.backup"),
    ],
    ids=["svg", "empty-table-path", "png-backup"],
)
async def test_invalid_path_does_not_hide_valid_image_in_same_chunk(
    tmp_path, validated_paths, mode, invalid_first
):
    _save_png(tmp_path / "figure.png", "red")
    valid = tmp_path / "valid.png"
    valid_bytes = _save_png(valid, "blue")
    content = invalid_first(tmp_path) + "\n" + _image_chunk(str(valid))
    prompt = await _lightrag_prompt(mode, [content])
    query = _make_query(tmp_path, prompt)

    assert await query.aquery(QUESTION, mode=mode) == "vision answer"
    assert _sent_images(query) == [valid_bytes]
    assert validated_paths == [str(valid)]


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", ["x", "x.pngx"])
async def test_long_run_of_spaces_after_label_is_linear(tmp_path, tail):
    # The earlier pattern re-scanned the rest of the line once per space:
    # 20k spaces took about 4 s, and 100k (one default-size chunk) about
    # 110 s, blocking the event loop.
    content = "Image Path:" + " " * 20_000 + tail
    prompt = await _lightrag_prompt("naive", [content])
    query = _make_query(tmp_path, prompt)

    start = time.perf_counter()
    enhanced, count = await query._process_image_paths_for_vlm(prompt)

    assert time.perf_counter() - start < 1.0
    assert count == 0
    assert enhanced == prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "suffix",
    [".backup", "x", "~", "_old", "\\x", "..", ".x", ").x", ";x"],
    ids=[
        "dot-backup",
        "letter",
        "tilde",
        "underscore",
        "backslash",
        "two-dots",
        "dot-letter",
        "paren-letter",
        "semicolon-letter",
    ],
)
async def test_existing_prefix_is_not_captured_without_delimiter(
    tmp_path, validated_paths, mode, suffix
):
    prefix = tmp_path / "figure.png"
    _save_png(prefix)
    content = f"Image Path: {prefix}{suffix}\nCaptions: x"
    prompt = await _lightrag_prompt(mode, [content])
    query = _make_query(tmp_path, prompt)

    enhanced, count = await query._process_image_paths_for_vlm(prompt)

    assert count == 0
    assert enhanced == prompt
    assert str(prefix) not in validated_paths


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known limitation: whitespace is a delimiter, so for 'chart.png v2.png' "
        "the capture stops at an existing 'chart.png' and sends that image. "
        "Main does the same; the fix would be to try image-suffixed prefixes "
        "of the whole field from longest to shortest."
    ),
)
@pytest.mark.asyncio
async def test_filename_with_space_after_image_suffix_sends_that_file(
    tmp_path, validated_paths
):
    _save_png(tmp_path / "chart.png", "red")
    spaced = tmp_path / "chart.png v2.png"
    spaced_bytes = _save_png(spaced, "blue")
    prompt = await _lightrag_prompt("naive", [_image_chunk(str(spaced))])
    query = _make_query(tmp_path, prompt)

    assert await query.aquery(QUESTION, mode="naive") == "vision answer"
    assert _sent_images(query) == [spaced_bytes]
