"""Tests for the VideoModalProcessor."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from raganything.modalprocessors_video import (
    VideoModalProcessor,
    is_video_file,
    video_deps_available,
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
    max_parallel_insert: int = 2


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
        lightrag = _FakeLightRAG()
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
        lightrag = _FakeLightRAG()
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
        lightrag = _FakeLightRAG()
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
        lightrag = _FakeLightRAG()
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
        lightrag = _FakeLightRAG()
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
        lightrag = _FakeLightRAG()
        processor = VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
        )

        result, entity_info = await processor.generate_description_only(
            {"video_path": "/nonexistent/video.mp4"},
            "video",
        )
        assert entity_info["entity_type"] == "video"

    async def test_with_mocked_pipeline(self, tmp_path):
        lightrag = _FakeLightRAG()
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

        # generate_description_only checks the path exists before running the
        # (mocked) pipeline, so point it at a real, empty file.
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"")

        result, entity_info = await processor.generate_description_only(
            {"video_path": str(video_file)},
            "video",
        )

        assert "Presenter with slides" in result
        assert "Demo of product" in result
        assert entity_info["entity_type"] == "video"
        assert "video_test" in entity_info["entity_name"]


class TestPlanWindows:
    """Test scene -> window grouping and redistribution."""

    def _processor(self, max_scenes=50, max_windows=100, chunk_token_size=100000):
        lightrag = _FakeLightRAG(chunk_token_size=chunk_token_size)
        return VideoModalProcessor(
            lightrag=lightrag,
            modal_caption_func=AsyncMock(),
            max_scenes=max_scenes,
            max_windows=max_windows,
        )

    def _scenes(self, n):
        return [
            {"start": i * 10, "end": i * 10 + 10, "visual": f"scene {i}"}
            for i in range(n)
        ]

    def test_empty(self):
        assert self._processor()._plan_windows([]) == []

    def test_single_window_when_under_max_scenes(self):
        processor = self._processor(max_scenes=50)
        windows = processor._plan_windows(self._scenes(5))
        assert len(windows) == 1

    def test_splits_by_max_scenes(self):
        processor = self._processor(max_scenes=2)
        windows = processor._plan_windows(self._scenes(5))
        # 5 scenes / 2 per window -> 3 windows (2, 2, 1), no scene dropped
        assert len(windows) == 3
        assert sum(len(w) for w in windows) == 5

    def test_max_windows_redistributes(self):
        processor = self._processor(max_scenes=1, max_windows=2)
        windows = processor._plan_windows(self._scenes(6))
        # max_scenes=1 would give 6 windows, but max_windows caps to 2 groups
        assert len(windows) == 2
        assert sum(len(w) for w in windows) == 6  # all scenes preserved

    def test_redistribute_preserves_order(self):
        items = [{"i": i} for i in range(7)]
        groups = VideoModalProcessor._redistribute(items, 3)
        assert sum(len(g) for g in groups) == 7
        flat = [x["i"] for g in groups for x in g]
        assert flat == list(range(7))


@pytest.mark.asyncio
class TestVideoChunkSections:
    """Test the 1->N generate_chunk_sections for video."""

    def _processor(self, max_scenes=1):
        return VideoModalProcessor(
            lightrag=_FakeLightRAG(),
            modal_caption_func=AsyncMock(return_value="desc"),
            max_scenes=max_scenes,
        )

    async def test_multiple_windows(self, tmp_path):
        processor = self._processor(max_scenes=1)
        processor._detect_scenes = MagicMock(return_value=[(0, 30), (30, 60), (60, 90)])
        processor._describe_scenes = AsyncMock(
            return_value=[
                {"start": 0, "end": 30, "visual": "Scene A"},
                {"start": 30, "end": 60, "visual": "Scene B"},
                {"start": 60, "end": 90, "visual": "Scene C"},
            ]
        )
        processor._transcribe_audio_track = AsyncMock(return_value=[])

        video_file = tmp_path / "clip.mp4"
        video_file.write_bytes(b"")

        sections = await processor.generate_chunk_sections(
            {"video_path": str(video_file)}, "video"
        )
        assert len(sections) == 3
        assert [s["window_meta"]["part"] for s in sections] == [1, 2, 3]
        names = [s["entity_info"]["entity_name"] for s in sections]
        assert names == ["video_clip_part1", "video_clip_part2", "video_clip_part3"]
        joined = "\n".join(s["description"] for s in sections)
        for label in ("Scene A", "Scene B", "Scene C"):
            assert label in joined

    async def test_tail_audio_beyond_last_scene_is_kept(self, tmp_path):
        processor = self._processor(max_scenes=50)
        processor._detect_scenes = MagicMock(return_value=[(0, 30)])
        processor._describe_scenes = AsyncMock(
            return_value=[{"start": 0, "end": 30, "visual": "Only scene"}]
        )
        # Audio that starts after the last scene end (30s)
        processor._transcribe_audio_track = AsyncMock(
            return_value=[{"start": 35, "end": 45, "text": "trailing speech"}]
        )

        video_file = tmp_path / "clip.mp4"
        video_file.write_bytes(b"")

        sections = await processor.generate_chunk_sections(
            {"video_path": str(video_file)}, "video"
        )
        joined = "\n".join(s["description"] for s in sections)
        assert "trailing speech" in joined  # tail audio not dropped


@pytest.mark.asyncio
class TestDescribeScenesSystemPrompt:
    """Frame description must pass a system prompt (matches ImageModalProcessor)."""

    async def test_passes_system_prompt_and_image_data(self, tmp_path):
        from raganything.prompt import PROMPTS

        cap = AsyncMock(return_value="a solid red frame")
        proc = VideoModalProcessor(lightrag=_FakeLightRAG(), modal_caption_func=cap)

        # Stub frame extraction to a real (tiny) file so base64 encoding works
        # without OpenCV; _describe_scenes calls it via asyncio.to_thread.
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        proc._extract_frame_at = MagicMock(return_value=str(frame))

        out = await proc._describe_scenes("/v.mp4", [(0, 10)])
        assert out == [{"start": 0, "end": 10, "visual": "a solid red frame"}]

        assert cap.await_count == 1
        kwargs = cap.call_args.kwargs
        assert kwargs.get("system_prompt") == PROMPTS["IMAGE_ANALYSIS_SYSTEM"]
        assert kwargs.get("image_data")  # base64 of the frame was passed
        # temp frame is cleaned up afterwards
        assert not frame.exists()


class TestVideoDepsAvailable:
    """Test optional-dependency detection."""

    def test_returns_false_when_any_missing(self, monkeypatch):
        monkeypatch.setattr(
            "raganything.modalprocessors_video.importlib.util.find_spec",
            lambda name: None if name == "moviepy" else object(),
        )
        assert video_deps_available() is False

    def test_returns_true_when_all_present(self, monkeypatch):
        monkeypatch.setattr(
            "raganything.modalprocessors_video.importlib.util.find_spec",
            lambda name: object(),
        )
        assert video_deps_available() is True
