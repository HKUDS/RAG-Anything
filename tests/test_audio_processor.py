"""Tests for the AudioModalProcessor."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from raganything.modalprocessors_audio import (
    AudioModalProcessor,
    audio_deps_available,
    is_audio_file,
)


@dataclass
class _FakeLightRAG:
    """Minimal dataclass stand-in for a LightRAG instance.

    ``BaseModalProcessor.__init__`` calls ``dataclasses.asdict`` on the lightrag
    object, which requires a real dataclass instance (a plain ``MagicMock``
    raises ``TypeError``). Only attribute access is exercised by these tests.
    """

    text_chunks: object = None
    chunks_vdb: object = None
    entities_vdb: object = None
    relationships_vdb: object = None
    chunk_entity_relation_graph: object = None
    embedding_func: object = None
    llm_model_func: object = None
    llm_response_cache: object = None
    tokenizer: object = None
    chunk_token_size: int = 1200


class TestIsAudioFile:
    """Test audio file detection."""

    def test_supported_extensions(self):
        assert is_audio_file("meeting.mp3")
        assert is_audio_file("recording.wav")
        assert is_audio_file("podcast.flac")
        assert is_audio_file("voice.m4a")
        assert is_audio_file("music.ogg")
        assert is_audio_file("/path/to/file.WAV")  # case insensitive
        assert is_audio_file("call.aac")
        assert is_audio_file("audio.opus")

    def test_unsupported_extensions(self):
        assert not is_audio_file("document.pdf")
        assert not is_audio_file("image.png")
        assert not is_audio_file("video.mp4")
        assert not is_audio_file("text.txt")
        assert not is_audio_file("no_extension")


class TestAudioModalProcessorInit:
    """Test AudioModalProcessor initialization."""

    def test_default_init(self):
        lightrag = _FakeLightRAG()
        caption_func = AsyncMock()

        processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=caption_func,
        )
        assert processor.whisper_model_name == "base"
        assert processor.whisper_device == "auto"
        assert processor.language is None

    def test_custom_model(self):
        lightrag = _FakeLightRAG()
        caption_func = AsyncMock()

        processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=caption_func,
            whisper_model="large-v3",
            language="zh",
        )
        assert processor.whisper_model_name == "large-v3"
        assert processor.language == "zh"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        monkeypatch.setenv("WHISPER_LANGUAGE", "en")

        lightrag = _FakeLightRAG()
        caption_func = AsyncMock()

        processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=caption_func,
        )
        assert processor.whisper_model_name == "medium"
        assert processor.language == "en"


class TestFormatTimestamp:
    """Test timestamp formatting."""

    def setup_method(self):
        lightrag = _FakeLightRAG()
        self.processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

    def test_seconds_only(self):
        assert self.processor._format_timestamp(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert self.processor._format_timestamp(125) == "2:05"

    def test_hours(self):
        assert self.processor._format_timestamp(3661) == "1:01:01"

    def test_zero(self):
        assert self.processor._format_timestamp(0) == "0:00"


class TestSegmentsToText:
    """Test segment formatting."""

    def setup_method(self):
        lightrag = _FakeLightRAG()
        self.processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

    def test_single_segment(self):
        segments = [{"start": 0, "end": 30, "text": "Hello world"}]
        result = self.processor._segments_to_text(segments)
        assert result == "[0:00-0:30] Hello world"

    def test_multiple_segments(self):
        segments = [
            {"start": 0, "end": 30, "text": "First segment"},
            {"start": 30, "end": 65, "text": "Second segment"},
        ]
        result = self.processor._segments_to_text(segments)
        assert "[0:00-0:30] First segment" in result
        assert "[0:30-1:05] Second segment" in result

    def test_empty_segments(self):
        result = self.processor._segments_to_text([])
        assert result == ""


@pytest.mark.asyncio
class TestGenerateDescriptionOnly:
    """Test the generate_description_only method."""

    async def test_file_not_found(self):
        lightrag = _FakeLightRAG()
        processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

        # Should return fallback on missing file
        result, entity_info = await processor.generate_description_only(
            {"audio_path": "/nonexistent/file.mp3"},
            "audio",
        )
        assert entity_info["entity_type"] == "audio"

    async def test_with_dict_content(self):
        lightrag = _FakeLightRAG()
        processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

        # Mock transcribe to avoid needing actual audio
        mock_segments = [
            {"start": 0, "end": 10, "text": "This is a test transcription"},
            {"start": 10, "end": 20, "text": "Second part of the audio"},
        ]
        processor.transcribe = MagicMock(return_value=mock_segments)

        result, entity_info = await processor.generate_description_only(
            {"audio_path": "/tmp/test.mp3"},
            "audio",
        )

        assert "[0:00-0:10] This is a test transcription" in result
        assert "[0:10-0:20] Second part of the audio" in result
        assert entity_info["entity_type"] == "audio"
        assert "audio_test" in entity_info["entity_name"]

    async def test_with_string_content(self):
        lightrag = _FakeLightRAG()
        processor = AudioModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

        mock_segments = [{"start": 0, "end": 5, "text": "Hello"}]
        processor.transcribe = MagicMock(return_value=mock_segments)

        # Pass path as string directly
        result, entity_info = await processor.generate_description_only(
            "/tmp/test.mp3",
            "audio",
        )
        assert "[0:00-0:05] Hello" in result


class TestGroupSegmentsByTokens:
    """Test token-bounded grouping of transcription segments."""

    def _processor(self, chunk_token_size=1200):
        lightrag = _FakeLightRAG(chunk_token_size=chunk_token_size)
        return AudioModalProcessor(lightrag=lightrag, modal_caption_func=AsyncMock())

    def test_empty(self):
        assert self._processor()._group_segments_by_tokens([]) == []

    def test_single_window_under_budget(self):
        processor = self._processor(chunk_token_size=1000)
        segs = [
            {"start": 0, "end": 5, "text": "short one"},
            {"start": 5, "end": 10, "text": "short two"},
        ]
        windows = processor._group_segments_by_tokens(segs)
        assert len(windows) == 1
        assert len(windows[0]) == 2

    def test_splits_when_over_budget(self):
        # No tokenizer -> ~len/4 tokens; ~200 chars => ~50 tokens each.
        processor = self._processor(chunk_token_size=50)
        long_text = "word " * 40  # 200 chars
        segs = [{"start": i, "end": i + 1, "text": long_text} for i in range(4)]
        windows = processor._group_segments_by_tokens(segs)
        assert len(windows) == 4  # each segment lands in its own window

    def test_oversized_single_segment_is_its_own_window(self):
        processor = self._processor(chunk_token_size=10)
        segs = [{"start": 0, "end": 5, "text": "x" * 400}]
        windows = processor._group_segments_by_tokens(segs)
        assert len(windows) == 1


@pytest.mark.asyncio
class TestAudioChunkSections:
    """Test the 1->N generate_chunk_sections for audio."""

    async def test_short_audio_single_section(self):
        processor = AudioModalProcessor(
            lightrag=_FakeLightRAG(), modal_caption_func=AsyncMock()
        )
        processor.transcribe = MagicMock(
            return_value=[{"start": 0, "end": 5, "text": "Hello world"}]
        )
        sections = await processor.generate_chunk_sections({"audio_path": "a.mp3"}, "audio")
        assert len(sections) == 1
        assert sections[0]["window_meta"] is None
        assert sections[0]["entity_info"]["entity_name"] == "audio_a"

    async def test_long_audio_multiple_sections(self):
        processor = AudioModalProcessor(
            lightrag=_FakeLightRAG(chunk_token_size=50),
            modal_caption_func=AsyncMock(),
        )
        long_text = "word " * 40
        processor.transcribe = MagicMock(
            return_value=[
                {"start": i * 10, "end": i * 10 + 9, "text": long_text}
                for i in range(3)
            ]
        )
        sections = await processor.generate_chunk_sections(
            {"audio_path": "meeting.mp3"}, "audio"
        )
        assert len(sections) == 3
        # Ordered part metadata + unique entity names
        assert [s["window_meta"]["part"] for s in sections] == [1, 2, 3]
        assert all(s["window_meta"]["total"] == 3 for s in sections)
        names = [s["entity_info"]["entity_name"] for s in sections]
        assert names == ["audio_meeting_part1", "audio_meeting_part2", "audio_meeting_part3"]


class TestAudioDepsAvailable:
    """Test optional-dependency detection."""

    def test_returns_false_when_missing(self, monkeypatch):
        monkeypatch.setattr(
            "raganything.modalprocessors_audio.importlib.util.find_spec",
            lambda name: None,
        )
        assert audio_deps_available() is False

    def test_returns_true_when_present(self, monkeypatch):
        monkeypatch.setattr(
            "raganything.modalprocessors_audio.importlib.util.find_spec",
            lambda name: object(),
        )
        assert audio_deps_available() is True
