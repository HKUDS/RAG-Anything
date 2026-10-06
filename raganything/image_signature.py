"""Recognise image files by their content.

Image files are base64-encoded and sent to the vision model, so a path that
names some other file (``![x](/etc/hosts)`` in an ingested Markdown file, a
stale parse-cache entry, an ``Image Path:`` line in retrieved text) must
never be sent. Kept free of heavy imports because ``parser`` uses it.
"""

# Leading bytes of the formats in Parser.IMAGE_FORMATS; WebP and BMP are
# checked separately below.
_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",
    b"GIF89a",
    b"II*\x00",  # TIFF, little-endian
    b"MM\x00*",  # TIFF, big-endian
    b"II+\x00",  # BigTIFF, little-endian
    b"MM\x00+",  # BigTIFF, big-endian
)
# Sizes of the known BMP DIB headers ("BM" alone is too weak a signature).
_BMP_DIB_HEADER_SIZES = {12, 40, 52, 56, 64, 108, 124}

# How many leading bytes looks_like_image() needs.
SIGNATURE_BYTES = 18


def looks_like_image(head: bytes) -> bool:
    """Whether ``head`` (a file's first SIGNATURE_BYTES bytes or more) starts
    a PNG, JPEG, GIF, BMP, TIFF or WebP image."""
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    if head[:2] == b"BM":
        return (
            len(head) >= 18
            and int.from_bytes(head[14:18], "little") in _BMP_DIB_HEADER_SIZES
        )
    return head.startswith(_SIGNATURES)
