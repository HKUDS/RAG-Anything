"""Tests for the VideoModalProcessor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raganything.modalprocessors_video import is_video_file

try:
    import cv2
    import faster_whisper

    HAS_VIDEO_DEPS = True
except ImportError:
    HAS_VIDEO_DEPS = False

from raganything.modalprocessors_video import VideoModalProcessor


class TestIsVideoFile:
    """Test video file detection."""

    def test_supported_extensions(self):
        assert is_video_file("meeting.mp4")
        assert is_video_file("recording.mov")
        assert is_video_file("demo.webm")
        assert is_video_file("clip.avi")
        assert is_video_file("video.mkv")
        assert is_video_file("/path/to/file.MP4")  # case insensitive
        assert is_video_file("stream.flv")
        assert is_video_file("screen.m4v")

    def test_unsupported_extensions(self):
        assert not is_video_file("document.pdf")
        assert not is_video_file("image.png")
        assert not is_video_file("audio.mp3")
        assert not is_video_file("text.txt")
        assert not is_video_file("no_extension")


class TestVideoModalProcessorInit:
    """Test VideoModalProcessor initialization."""

    def test_default_init(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        caption_func = AsyncMock()

        processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=caption_func,
        )
        assert processor.whisper_model_name == "base"
        assert processor.min_scene_duration == 5.0
        assert processor.max_scenes == 50
        assert processor.scene_threshold == 27.0

    def test_custom_config(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        caption_func = AsyncMock()

        processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=caption_func,
            whisper_model="large-v3",
            min_scene_duration=10.0,
            max_scenes=20,
            scene_threshold=30.0,
        )
        assert processor.whisper_model_name == "large-v3"
        assert processor.min_scene_duration == 10.0
        assert processor.max_scenes == 20
        assert processor.scene_threshold == 30.0


class TestTimestampFormatting:
    """Test timestamp formatting."""

    def setup_method(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        self.processor = VideoModalProcessor(
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


class TestGetTranscriptInRange:
    """Test transcript time-range filtering."""

    def setup_method(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        self.processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

    def test_overlapping_segments(self):
        transcript = [
            {"start": 0, "end": 10, "text": "Hello"},
            {"start": 10, "end": 20, "text": "World"},
            {"start": 20, "end": 30, "text": "Goodbye"},
        ]
        result = self.processor._get_transcript_in_range(transcript, 5, 25)
        assert "Hello" in result
        assert "World" in result
        assert "Goodbye" in result

    def test_no_overlap(self):
        transcript = [
            {"start": 0, "end": 10, "text": "Hello"},
            {"start": 50, "end": 60, "text": "Later"},
        ]
        result = self.processor._get_transcript_in_range(transcript, 20, 40)
        assert result == ""

    def test_exact_boundaries(self):
        transcript = [
            {"start": 10, "end": 20, "text": "Exact"},
        ]
        result = self.processor._get_transcript_in_range(transcript, 10, 20)
        assert "Exact" in result


class TestMergeChannels:
    """Test visual + audio channel merging."""

    def setup_method(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        self.processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

    def test_both_channels(self):
        visual = [{"start": 0, "end": 30, "visual": "PPT showing revenue chart"}]
        audio = [{"start": 5, "end": 25, "text": "Revenue grew 23%"}]

        result = self.processor._merge_channels(visual, audio)
        assert "画面：PPT showing revenue chart" in result
        assert "语音：Revenue grew 23%" in result
        assert "[0:00-0:30]" in result

    def test_visual_only(self):
        visual = [{"start": 0, "end": 30, "visual": "Surveillance footage"}]
        audio = []

        result = self.processor._merge_channels(visual, audio)
        assert "画面：Surveillance footage" in result
        assert "语音" not in result

    def test_audio_only(self):
        visual = [{"start": 0, "end": 30, "visual": ""}]
        audio = [{"start": 0, "end": 30, "text": "Just audio content"}]

        result = self.processor._merge_channels(visual, audio)
        assert "语音：Just audio content" in result

    def test_multiple_scenes(self):
        visual = [
            {"start": 0, "end": 30, "visual": "Scene 1"},
            {"start": 30, "end": 60, "visual": "Scene 2"},
        ]
        audio = [
            {"start": 5, "end": 25, "text": "First part"},
            {"start": 35, "end": 55, "text": "Second part"},
        ]

        result = self.processor._merge_channels(visual, audio)
        assert "Scene 1" in result
        assert "Scene 2" in result
        assert "First part" in result
        assert "Second part" in result

    def test_empty_both(self):
        result = self.processor._merge_channels([], [])
        assert result == ""


@pytest.mark.asyncio
class TestGenerateDescriptionOnly:
    """Test the generate_description_only method."""

    async def test_missing_file(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

        result, entity_info = await processor.generate_description_only(
            {"video_path": "/nonexistent/video.mp4"},
            "video",
        )
        assert entity_info["entity_type"] == "video"

    async def test_with_mocked_pipeline(self):
        lightrag = MagicMock()
        lightrag.tokenizer = None
        caption_func = AsyncMock(return_value="A person presenting slides")
        processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=caption_func,
        )

        # Mock internal methods
        processor._detect_scenes = MagicMock(return_value=[(0, 30), (30, 60)])
        processor._describe_scenes = AsyncMock(
            return_value=[
                {"start": 0, "end": 30, "visual": "Presenter with slides"},
                {"start": 30, "end": 60, "visual": "Demo of product"},
            ]
        )
        processor._extract_audio_track = MagicMock(return_value=None)

        result, entity_info = await processor.generate_description_only(
            {"video_path": "/tmp/test.mp4"},
            "video",
        )

        assert "Presenter with slides" in result
        assert "Demo of product" in result
        assert entity_info["entity_type"] == "video"
        assert "video_test" in entity_info["entity_name"]
