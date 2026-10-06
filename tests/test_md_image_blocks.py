"""Markdown image references become MinerU-shaped image blocks.

The old .md -> ReportLab -> PDF -> MinerU round trip was meant to carry
images into the pipeline but never did: ReportLab rendered ``![alt](path)``
as literal text and embedded nothing. The direct parser now emits an image
block shaped exactly like MinerU's for every reference that resolves to a
local image file, so markdown images flow into the same multimodal pipeline
as images extracted from PDFs. An image block's file is sent to the vision
model, so only real images (extension and content) qualify.
"""

from pathlib import Path

import pytest

from raganything.parser import Parser


@pytest.fixture()
def md_dir(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "arch.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (tmp_path / "root.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return tmp_path


def parse(md_dir: Path, text: str):
    md = md_dir / "doc.md"
    md.write_text(text, encoding="utf-8")
    return Parser().parse_text_file(md)


def blocks_of(blocks, type_):
    return [b for b in blocks if b["type"] == type_]


def test_standalone_image_becomes_mineru_shaped_block(md_dir):
    blocks = parse(md_dir, "Intro.\n\n![system diagram](images/arch.png)\n\nOutro.\n")
    images = blocks_of(blocks, "image")
    assert len(images) == 1
    img = images[0]
    assert img["img_path"] == str((md_dir / "images" / "arch.png").resolve())
    assert img["img_caption"] == ["system diagram"]
    assert img["img_footnote"] == []
    assert img["page_idx"] == 0
    texts = [b["text"] for b in blocks_of(blocks, "text")]
    assert texts == ["Intro.", "Outro."]


def test_empty_alt_gives_empty_caption(md_dir):
    blocks = parse(md_dir, "![](images/arch.png)\n")
    assert blocks_of(blocks, "image")[0]["img_caption"] == []


def test_title_joins_captions(md_dir):
    blocks = parse(md_dir, '![alt text](images/arch.png "The Title")\n')
    assert blocks_of(blocks, "image")[0]["img_caption"] == ["alt text", "The Title"]


def test_angle_bracket_target_with_spaces(md_dir):
    (md_dir / "my image.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    blocks = parse(md_dir, "![alt](<my image.png>)\n")
    assert blocks_of(blocks, "image")[0]["img_path"] == str(
        (md_dir / "my image.png").resolve()
    )


def test_absolute_path_resolves(md_dir):
    target = (md_dir / "root.png").resolve()
    blocks = parse(md_dir, f"![abs]({target})\n")
    assert blocks_of(blocks, "image")[0]["img_path"] == str(target)


def test_missing_file_stays_literal_text(md_dir):
    blocks = parse(md_dir, "![gone](images/missing.png)\n")
    assert blocks_of(blocks, "image") == []
    assert blocks_of(blocks, "text")[0]["text"] == "![gone](images/missing.png)"


def test_url_stays_literal_text(md_dir):
    src = "![remote](https://example.com/a.png)"
    blocks = parse(md_dir, src + "\n")
    assert blocks_of(blocks, "image") == []
    assert blocks_of(blocks, "text")[0]["text"] == src


def test_inline_reference_keeps_sentence_and_emits_block_after(md_dir):
    blocks = parse(
        md_dir, "As shown in ![the diagram](images/arch.png), data flows east.\n"
    )
    assert [b["type"] for b in blocks] == ["text", "image"]
    assert blocks[0]["text"] == "As shown in the diagram, data flows east."
    assert blocks[1]["img_caption"] == ["the diagram"]


def test_multiple_standalone_images_on_one_line(md_dir):
    blocks = parse(md_dir, "![a](images/arch.png) ![b](root.png)\n")
    images = blocks_of(blocks, "image")
    assert [i["img_caption"] for i in images] == [["a"], ["b"]]
    assert blocks_of(blocks, "text") == []


def test_mixed_good_and_bad_refs_on_standalone_line(md_dir):
    blocks = parse(md_dir, "![ok](images/arch.png) ![bad](nope.png)\n")
    assert len(blocks_of(blocks, "image")) == 1
    assert "![bad](nope.png)" in blocks_of(blocks, "text")[0]["text"]


def test_fenced_code_is_never_interpreted(md_dir):
    text = (
        "Before.\n\n"
        "```\n"
        "![not an image](images/arch.png)\n"
        "# not a heading\n"
        "```\n\n"
        "After.\n"
    )
    blocks = parse(md_dir, text)
    assert blocks_of(blocks, "image") == []
    assert all("text_level" not in b for b in blocks)
    fenced = [b for b in blocks_of(blocks, "text") if "```" in b["text"]]
    assert len(fenced) == 1
    assert "![not an image](images/arch.png)" in fenced[0]["text"]
    assert "# not a heading" in fenced[0]["text"]


def test_tilde_fence_also_suppresses(md_dir):
    blocks = parse(md_dir, "~~~\n![x](images/arch.png)\n~~~\n")
    assert blocks_of(blocks, "image") == []


def test_cjk_alt_text(md_dir):
    blocks = parse(md_dir, "![系统架构图](images/arch.png)\n")
    assert blocks_of(blocks, "image")[0]["img_caption"] == ["系统架构图"]


def test_txt_files_are_untouched(md_dir):
    txt = md_dir / "doc.txt"
    txt.write_text("![alt](images/arch.png)\n", encoding="utf-8")
    blocks = Parser().parse_text_file(txt)
    assert blocks_of(blocks, "image") == []
    assert blocks[0]["text"] == "![alt](images/arch.png)"


def test_raw_string_without_source_dir_keeps_literal():
    blocks = Parser._text_to_content_blocks("![a](rel.png)\n", is_markdown=True)
    assert [b["type"] for b in blocks] == ["text"]


# --------------------------------------------------------------------------
# only real image files become image blocks: an image block's file is
# base64-encoded and sent to the vision model
# --------------------------------------------------------------------------

SIGNATURES = {
    "a.png": b"\x89PNG\r\n\x1a\n",
    "b.jpg": b"\xff\xd8\xff\xe0",
    "c.jpeg": b"\xff\xd8\xff\xdb",
    "d.gif": b"GIF89a",
    "e.gif": b"GIF87a",
    "f.bmp": b"BM" + b"\x00" * 12 + (40).to_bytes(4, "little"),
    "g.tif": b"II*\x00",
    "h.tiff": b"MM\x00*",
    "h2.tif": b"II+\x00",  # BigTIFF
    "h3.tiff": b"MM\x00+",
    "i.webp": b"RIFF\x00\x00\x00\x00WEBPVP8 ",
    "J.PNG": b"\x89PNG\r\n\x1a\n",
    # a mislabelled image is still an image
    "k.jpg": b"\x89PNG\r\n\x1a\n",
}


@pytest.mark.parametrize("name", sorted(SIGNATURES))
def test_every_supported_image_format_becomes_a_block(md_dir, name):
    (md_dir / name).write_bytes(SIGNATURES[name] + b"rest")

    blocks = parse(md_dir, f"![x]({name})\n")

    assert [b["img_path"] for b in blocks_of(blocks, "image")] == [
        str((md_dir / name).resolve())
    ]


@pytest.mark.parametrize(
    "name,content",
    [
        ("hosts", b"127.0.0.1 localhost\n"),  # no extension
        ("notes.txt", b"secret-token-123\n"),
        ("id_rsa.png", b"-----BEGIN OPENSSH PRIVATE KEY-----\n"),  # renamed key
        ("empty.png", b""),
        ("tiny.png", b"\x89P"),  # truncated signature
        ("notes.bmp", b"BMW service notes, VIN 123\n"),  # "BM" alone is not BMP
        ("riff.webp", b"RIFF\x00\x00\x00\x00WAVE"),  # RIFF but not WebP
        ("vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("photo.heic", b"\x89PNG\r\n\x1a\n"),  # extension not supported
    ],
)
def test_non_image_files_stay_literal_text(md_dir, name, content):
    (md_dir / name).write_bytes(content)
    src = f"![x]({name})"

    blocks = parse(md_dir, src + "\n")

    assert blocks_of(blocks, "image") == []
    assert blocks_of(blocks, "text")[0]["text"] == src


def test_absolute_and_encoded_references_to_other_files_stay_text(md_dir, tmp_path):
    secret = tmp_path / "outside" / "config.yaml"
    secret.parent.mkdir()
    secret.write_text("api_key: abc\n")
    refs = [
        f"![a]({secret})",
        "![b](../outside/config.yaml)",
        "![c](../outside/config%2Eyaml)",
    ]
    nested = md_dir / "docs"
    nested.mkdir()

    blocks = parse(nested, "\n\n".join(refs) + "\n")

    assert blocks_of(blocks, "image") == []
    assert [b["text"] for b in blocks_of(blocks, "text")] == refs


def test_encoders_refuse_non_image_content(md_dir):
    """The read-time check covers paths that bypassed the parser: parse-cache
    entries written before this check existed, content lists, files swapped
    after parsing, and query-time image paths."""
    from raganything.modalprocessors import ImageModalProcessor
    from raganything.utils import encode_image_to_base64

    fake = md_dir / "cached.png"
    fake.write_text("api_key: secret\n")
    real = md_dir / "images" / "arch.png"

    assert encode_image_to_base64(str(fake)) == ""
    assert encode_image_to_base64(str(real)) != ""
    processor = ImageModalProcessor.__new__(ImageModalProcessor)
    assert processor._encode_image_to_base64(str(fake)) == ""
    assert processor._encode_image_to_base64(str(real)) != ""
