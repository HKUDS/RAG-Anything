"""Retrieved image data URLs must describe the bytes passed to the VLM."""

import base64
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from raganything.query import QueryMixin

Image = pytest.importorskip("PIL.Image")


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["aquery", "aquery_vlm_enhanced"])
@pytest.mark.parametrize(
    "image_format,extension,media_type",
    [
        ("JPEG", "jpg", "image/jpeg"),
        ("PNG", "png", "image/png"),
        ("GIF", "gif", "image/gif"),
        ("WEBP", "webp", "image/webp"),
        ("BMP", "bmp", "image/bmp"),
        ("TIFF", "tiff", "image/tiff"),
        ("PNG", "jpg", "image/png"),
    ],
)
async def test_retrieved_image_media_type_matches_unchanged_bytes(
    tmp_path, entrypoint, image_format, extension, media_type
):
    image_path = tmp_path / f"figure.{extension}"
    Image.new("RGB", (2, 2), "red").save(image_path, format=image_format)
    original = image_path.read_bytes()
    query = QueryMixin()
    query.logger = logging.getLogger(__name__)
    query.config = SimpleNamespace(
        working_dir=str(tmp_path), parser_output_dir=str(tmp_path)
    )
    query._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    query.lightrag = SimpleNamespace(
        aquery=AsyncMock(return_value=f"Context\nImage Path: {image_path}\nCaption")
    )
    query.vision_model_func = AsyncMock(return_value="vision answer")

    assert await getattr(query, entrypoint)("Describe it") == "vision answer"
    messages = query.vision_model_func.await_args.kwargs["messages"]
    image_parts = [p for p in messages[1]["content"] if p["type"] == "image_url"]
    assert len(image_parts) == 1
    header, encoded = image_parts[0]["image_url"]["url"].split(",", 1)
    assert header == f"data:{media_type};base64"
    decoded = base64.b64decode(encoded, validate=True)
    assert decoded == original
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.format == image_format
