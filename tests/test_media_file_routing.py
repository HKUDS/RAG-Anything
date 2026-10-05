"""Audio/video files route through parse_document as media content items.

SUPPORTED_FILE_EXTENSIONS has advertised media extensions since the
audio/video modalities landed, but parse_document previously fell through
to the document parser for them (MinerU cannot parse an .mp3), so
process_document_complete("meeting.mp3") and folder batches picking up
media files crashed. A media file now becomes a single audio/video content
item — no document parser involved — and flows to the modal processors
via the normal multimodal path.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from raganything.processor import ProcessorMixin
from raganything.utils import separate_content


class _Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _MemoryCache:
    def __init__(self):
        self.entries = {}

    async def get_by_id(self, key):
        return self.entries.get(key)

    async def upsert(self, entries):
        self.entries.update(entries)

    async def index_done_callback(self):
        pass


class _ExplodingParser:
    """Any call proves media routing regressed to the document parser."""

    def __getattr__(self, name):
        raise AssertionError(f"document parser must not be touched (got .{name})")


class _Processor(ProcessorMixin):
    pass


def _make_processor(tmp_path):
    processor = _Processor()
    processor.config = SimpleNamespace(
        parser="test",
        parser_output_dir=str(tmp_path / "output"),
        parse_method="auto",
        display_content_stats=False,
        use_full_path=False,
    )
    processor.logger = _Logger()
    processor.parse_cache = _MemoryCache()
    processor.doc_parser = _ExplodingParser()
    return processor


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", [".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"])
async def test_audio_file_becomes_single_audio_item(tmp_path, ext):
    processor = _make_processor(tmp_path)
    media = tmp_path / f"talk{ext}"
    media.write_bytes(b"fake-audio-bytes")

    content_list, doc_id = await processor.parse_document(str(media))

    assert len(content_list) == 1
    item = content_list[0]
    assert item["type"] == "audio"
    assert item["audio_path"] == str(media.absolute())
    assert item["audio_caption"] == []
    assert item["page_idx"] == 0
    assert len(item["media_sha256"]) == 64
    assert doc_id


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", [".mp4", ".mov", ".webm", ".mkv", ".avi"])
async def test_video_file_becomes_single_video_item(tmp_path, ext):
    processor = _make_processor(tmp_path)
    media = tmp_path / f"demo{ext}"
    media.write_bytes(b"fake-video-bytes")

    content_list, _ = await processor.parse_document(str(media))

    assert len(content_list) == 1
    assert content_list[0]["type"] == "video"
    assert content_list[0]["video_path"] == str(media.absolute())


@pytest.mark.asyncio
async def test_media_items_classify_as_multimodal(tmp_path):
    processor = _make_processor(tmp_path)
    media = tmp_path / "talk.wav"
    media.write_bytes(b"fake")

    content_list, _ = await processor.parse_document(str(media))
    text_content, multimodal = separate_content(content_list)

    assert text_content.strip() == ""
    assert [m["type"] for m in multimodal] == ["audio"]


@pytest.mark.asyncio
async def test_replacing_media_bytes_changes_doc_id(tmp_path):
    processor = _make_processor(tmp_path)
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"version-one")
    stat = media.stat()

    _, first_id = await processor.parse_document(str(media))

    media.write_bytes(b"version-two")
    os.utime(media, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    _, second_id = await processor.parse_document(str(media))

    assert first_id != second_id


@pytest.mark.asyncio
async def test_media_parse_is_cached(tmp_path):
    processor = _make_processor(tmp_path)
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"bytes")

    first = await processor.parse_document(str(media))
    second = await processor.parse_document(str(media))

    assert second == first
    assert len(processor.parse_cache.entries) == 1


@pytest.mark.asyncio
async def test_non_media_files_still_use_the_parser(tmp_path):
    processor = _make_processor(tmp_path)

    class _TextParser:
        def parse_document(self, file_path, **kwargs):
            return [{"type": "text", "text": Path(file_path).read_text()}]

    processor.doc_parser = _TextParser()
    doc = tmp_path / "notes.rst"
    doc.write_text("hello", encoding="utf-8")

    content_list, _ = await processor.parse_document(str(doc))
    assert content_list == [{"type": "text", "text": "hello"}]
