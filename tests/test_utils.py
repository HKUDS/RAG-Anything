import base64

from raganything.utils import encode_image_to_base64


def test_encode_image_to_base64_rejects_non_image_extension(tmp_path):
    path = tmp_path / "payload.txt"
    path.write_bytes(b"not an image")

    assert encode_image_to_base64(str(path)) == ""


def test_encode_image_to_base64_accepts_valid_image_extension(tmp_path):
    path = tmp_path / "pixel.png"
    path.write_bytes(b"png bytes")

    assert encode_image_to_base64(str(path)) == base64.b64encode(b"png bytes").decode("utf-8")
