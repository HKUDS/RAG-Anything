"""Markdown image references become MinerU-shaped image blocks.

The old .md -> ReportLab -> PDF -> MinerU round trip was meant to carry
images into the pipeline but never did: ReportLab rendered ``![alt](path)``
as literal text and embedded nothing. The direct parser now emits an image
block shaped exactly like MinerU's for every reference that resolves to a
readable local file, so markdown images flow into the same multimodal
pipeline as images extracted from PDFs.
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
