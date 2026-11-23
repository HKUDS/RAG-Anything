"""Image section enrichment must not repeatedly rescan preceding blocks."""

from copy import deepcopy
from pathlib import Path

from raganything.utils import resolve_document_images, separate_content_with_page_map


def test_section_context_keeps_hierarchy_and_existing_metadata():
    blocks = [
        {"type": "image", "img_path": "before.png"},
        {"type": "text", "text": " Chapter ", "text_level": "1", "page_idx": 0},
        {"type": "text", "text": "Detail", "text_level": 3},
        {"type": "image", "img_path": "detail.png"},
        {"type": "text", "text": "Invalid", "text_level": "bad"},
        {"type": "text", "text": " ", "text_level": 1},
        {"type": "text", "text": "Sibling", "text_level": 2},
        {"type": "image", "img_path": "sibling.png", "_section_path": "Custom"},
        {"type": "image", "img_path": "inherited.png"},
        {"type": "text", "text": "Next", "text_level": 1},
        {"type": "image", "img_path": "next.png"},
    ]
    original = deepcopy(blocks)
    text, images, pages = separate_content_with_page_map(blocks)
    assert [image["_section_path"] for image in images] == [
        "",
        "Chapter > Detail",
        "Custom",
        "Chapter > Sibling",
        "Next",
    ]
    assert text == " Chapter \n\nDetail\n\nInvalid\n\nSibling\n\nNext"
    assert pages[0] == (0, 9, 0)
    assert images[1]["_neighbor_text"] == "Chapter Detail Invalid Sibling"
    assert blocks == original


def test_image_context_inspects_blocks_linearly():
    reads = 0

    class CountedBlock(dict):
        def get(self, *args, **kwargs):
            nonlocal reads
            reads += 1
            return super().get(*args, **kwargs)

    def measure(size):
        nonlocal reads
        blocks = []
        for index in range(size):
            blocks.extend(
                [
                    CountedBlock(type="text", text=f"Chapter {index}", text_level=1),
                    CountedBlock(type="image", img_path=f"{index}.png"),
                ]
            )
        reads = 0
        _, images, _ = separate_content_with_page_map(blocks)
        assert images[-1]["_section_path"] == f"Chapter {size - 1}"
        return reads

    small = measure(100)
    large = measure(400)
    # Four times the input should not trigger sixteen times the block reads.
    assert large < small * 5


def test_relative_image_uses_its_document_and_preserves_parser_input(
    tmp_path, monkeypatch
):
    doc = tmp_path / "report"
    (doc / "images").mkdir(parents=True)
    image = doc / "images" / "chart #1.png"
    image.touch()
    elsewhere = tmp_path / "other"
    (elsewhere / "images").mkdir(parents=True)
    (elsewhere / "images" / image.name).touch()
    monkeypatch.chdir(elsewhere)
    raw = [
        {"type": "image", "img_path": "images/chart #1.png"},
        {"type": "image", "img_path": "missing/chart #1.png"},
    ]
    from raganything.processor import ProcessorMixin

    images = resolve_document_images(raw, doc / "report.pdf")
    assert images[0]["img_path"] == str(image)
    assert images[1]["img_path"] == str(doc / "missing" / image.name)
    assert not Path(images[1]["img_path"]).exists()
    assert raw[0]["img_path"] == "images/chart #1.png"

    other_images = resolve_document_images(raw, elsewhere / "report.pdf")
    processor = ProcessorMixin()
    assert processor._generate_content_based_doc_id(
        images
    ) != processor._generate_content_based_doc_id(other_images)
