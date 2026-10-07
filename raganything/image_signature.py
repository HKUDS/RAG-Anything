"""Recognise image files by their content.

Image files are base64-encoded and sent to the vision model, so a path that
names some other file (``![x](/etc/hosts)`` in an ingested Markdown file, a
stale parse-cache entry, an ``Image Path:`` line in retrieved text) must
never be sent. Kept free of heavy imports because ``parser`` uses it.
"""

# Leading bytes of the formats in Parser.IMAGE_FORMATS; WebP and BMP are
# checked separately below.
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),  # TIFF, little-endian
    (b"MM\x00*", "image/tiff"),  # TIFF, big-endian
    (b"II+\x00", "image/tiff"),  # BigTIFF, little-endian
    (b"MM\x00+", "image/tiff"),  # BigTIFF, big-endian
)
# Sizes of the known BMP DIB headers ("BM" alone is too weak a signature).
_BMP_DIB_HEADER_SIZES = {12, 40, 52, 56, 64, 108, 124}

# How many leading bytes looks_like_image() needs.
SIGNATURE_BYTES = 18


def image_mime_type(head: bytes) -> str | None:
    """Identify the media type from the first SIGNATURE_BYTES of image data."""
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:2] == b"BM":
        if (
            len(head) >= 18
            and int.from_bytes(head[14:18], "little") in _BMP_DIB_HEADER_SIZES
        ):
            return "image/bmp"
        return None
    for signature, mime_type in _SIGNATURES:
        if head.startswith(signature):
            return mime_type
    return None


def looks_like_image(head: bytes) -> bool:
    """Whether ``head`` starts a supported image format."""
    return image_mime_type(head) is not None
