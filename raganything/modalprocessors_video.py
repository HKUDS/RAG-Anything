"""
Video Modal Processor for RAG-Anything

Processes video files (MP4, MOV, WebM, AVI, MKV) with dual-channel analysis:
- Visual channel: scene detection + keyframe extraction + VLM description
- Audio channel: audio track extraction + faster-whisper transcription

Results are merged by timestamp, producing rich text descriptions like:
    [0:00-0:30] 画面：展示Q3营收图表 | 语音：本季度同比增长23%...

Long videos are split into multiple ordered chunks ("windows") so that no scene
or audio is silently dropped (see ``generate_chunk_sections``).

Supports:
- Meeting recordings (screen share + voice)
- Lectures/tutorials (slides + narration)
- Product demos (UI operations + voiceover)
- Surveillance/inspection (visual scenes, often no audio)
- Podcasts with video (talking heads + speech)

Dependencies:
    pip install raganything[video]
    # or: pip install scenedetect[opencv] moviepy faster-whisper opencv-python
"""

import asyncio
import base64
import importlib.util
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lightrag.utils import compute_mdhash_id

from .modalprocessors import BaseModalProcessor
from .modalprocessors_audio import AudioModalProcessor
from .prompt import PROMPTS

logger = logging.getLogger(__name__)

# Supported video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".flv", ".wmv", ".m4v"}


def _load_cv2():
    """Lazily import OpenCV so that importing this module does not require it."""
    try:
        import cv2
    except ImportError as e:
        raise ImportError(
            "opencv-python is required for video processing. "
            "Install it with: pip install raganything[video] "
            "or: pip install opencv-python"
        ) from e
    return cv2


def is_video_file(file_path: str) -> bool:
    """Check if a file is a supported video format."""
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS


def video_deps_available() -> bool:
    """Return True if all optional video dependencies are importable."""
    return all(
        importlib.util.find_spec(mod) is not None
        for mod in ("cv2", "scenedetect", "moviepy", "faster_whisper")
    )


class VideoModalProcessor(BaseModalProcessor):
    """Processor for video content with visual + audio dual-channel analysis.

    Combines:
    - SceneDetect for intelligent scene boundary detection
    - OpenCV for keyframe extraction
    - VLM (via modal_caption_func) for visual description
    - faster-whisper for audio transcription
    - Timestamp-aligned merging of both channels

    Suitable for:
    - Meeting recordings (screen share + discussion)
    - Lectures and tutorials (slides + narration)
    - Product demos (UI + voiceover)
    - Surveillance / inspection videos (visual only)
    - Podcasts with video component

    Example:
        >>> processor = VideoModalProcessor(
        ...     lightrag=rag_instance,
        ...     modal_caption_func=caption_func,
        ...     whisper_model="large-v3",
        ... )
        >>> result = await processor.process_multimodal_content(
        ...     modal_content={"video_path": "/path/to/meeting.mp4"},
        ...     content_type="video",
        ... )
    """

    def __init__(
        self,
        lightrag,
        modal_caption_func,
        context_extractor=None,
        whisper_model: str = None,
        whisper_device: str = "auto",
        whisper_compute_type: str = "auto",
        language: str = None,
        min_scene_duration: float = 5.0,
        max_scenes: int = 50,
        scene_threshold: float = 27.0,
        max_windows: int = 100,
        audio_processor: "AudioModalProcessor" = None,
    ):
        """Initialize video processor.

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating visual descriptions
            context_extractor: Context extractor instance
            whisper_model: Whisper model size (tiny/base/small/medium/large-v3)
            whisper_device: Device for inference ("auto", "cpu", "cuda")
            whisper_compute_type: Compute type ("auto", "float16", "int8")
            language: Language code for ASR (None for auto-detect)
            min_scene_duration: Minimum scene duration in seconds to keep
            max_scenes: Maximum scenes per window (controls chunk size, not a hard
                cap on the whole video — extra scenes spill into further windows)
            scene_threshold: ContentDetector threshold (lower = more sensitive)
            max_windows: Safety cap on the number of chunks produced for one video;
                if exceeded, scenes are redistributed into this many windows.
            audio_processor: Optional shared AudioModalProcessor to reuse a single
                whisper model when both audio and video processing are enabled.
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)

        self.whisper_model_name = whisper_model or os.environ.get(
            "WHISPER_MODEL", "base"
        )
        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        self.language = language or os.environ.get("WHISPER_LANGUAGE", None)
        self.min_scene_duration = min_scene_duration
        self.max_scenes = max_scenes
        self.scene_threshold = scene_threshold
        self.max_windows = max_windows

        # Reuse a shared audio processor when provided, otherwise lazily create one.
        self._audio_processor = audio_processor

    @property
    def audio_processor(self) -> AudioModalProcessor:
        """Get or create audio processor for transcription (shares whisper model)."""
        if self._audio_processor is None:
            self._audio_processor = AudioModalProcessor(
                lightrag=self.lightrag,
                modal_caption_func=self.modal_caption_func,
                whisper_model=self.whisper_model_name,
                whisper_device=self.whisper_device,
                whisper_compute_type=self.whisper_compute_type,
                language=self.language,
                segment_min_length=0,
            )
        return self._audio_processor

    @staticmethod
    def _resolve_video_path(modal_content) -> str:
        """Extract the video path from dict/JSON/string modal content."""
        if isinstance(modal_content, str):
            try:
                content_data = json.loads(modal_content)
            except json.JSONDecodeError:
                return modal_content
        else:
            content_data = modal_content
        return content_data.get("video_path") or content_data.get("img_path") or ""

    def _detect_scenes(self, video_path: str) -> List[Tuple[float, float]]:
        """Detect scene boundaries using SceneDetect.

        Returns ALL scenes (no hard cap); window planning bounds the per-chunk
        scene count later. This is a blocking call; async callers wrap it with
        ``asyncio.to_thread``.

        Args:
            video_path: Path to video file

        Returns:
            List of (start_seconds, end_seconds) tuples
        """
        try:
            from scenedetect import detect, ContentDetector
        except ImportError:
            raise ImportError(
                "scenedetect is required for video processing. "
                "Install it with: pip install raganything[video] "
                "or: pip install scenedetect[opencv]"
            )

        scene_list = detect(
            video_path,
            ContentDetector(threshold=self.scene_threshold),
        )

        scenes = []
        for scene in scene_list:
            start = scene[0].get_seconds()
            end = scene[1].get_seconds()
            duration = end - start
            if duration >= self.min_scene_duration:
                scenes.append((start, end))

        # If no scenes detected (e.g. static video), treat as single scene
        if not scenes:
            cv2 = _load_cv2()
            cap = cv2.VideoCapture(video_path)
            total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            if fps > 0:
                total_duration = total_frames / fps
                scenes = [(0, total_duration)]

        return scenes

    def _extract_frame_at(self, video_path: str, timestamp: float) -> Optional[str]:
        """Extract a single frame at the given timestamp.

        Note: ``CAP_PROP_POS_FRAMES`` seeking snaps to the nearest keyframe for
        many codecs, so the captured frame may be slightly off ``timestamp``.
        This is an acceptable approximation for scene-level description.

        Args:
            video_path: Path to video file
            timestamp: Time in seconds

        Returns:
            Path to saved frame image, or None on failure
        """
        cv2 = _load_cv2()
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            cap.release()
            return None

        frame_num = int(timestamp * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            return None

        # Unique temp name so concurrent extractions never collide
        fd, frame_path = tempfile.mkstemp(suffix=".jpg", prefix="raganything_vframe_")
        os.close(fd)
        cv2.imwrite(frame_path, frame)
        return frame_path

    def _extract_audio_track(self, video_path: str) -> Optional[str]:
        """Extract audio track from video file.

        Args:
            video_path: Path to video file

        Returns:
            Path to extracted audio WAV file, or None if no audio
        """
        try:
            from moviepy import VideoFileClip
        except ImportError:
            raise ImportError(
                "moviepy is required for video audio extraction. "
                "Install it with: pip install raganything[video] "
                "or: pip install moviepy"
            )

        # Unique temp name so concurrent video processing never overwrites it
        fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="raganything_vaudio_")
        os.close(fd)

        try:
            clip = VideoFileClip(video_path)
            if clip.audio is None:
                clip.close()
                os.remove(audio_path)
                return None
            clip.audio.write_audiofile(audio_path, logger=None)
            clip.close()
            return audio_path
        except Exception as e:
            logger.warning(f"Failed to extract audio from {video_path}: {e}")
            if os.path.exists(audio_path):
                os.remove(audio_path)
            return None

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS or MM:SS."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _get_transcript_in_range(
        self,
        transcript: List[Dict[str, Any]],
        start: float,
        end: float,
    ) -> str:
        """Get transcript text that falls within a time range."""
        texts = []
        for seg in transcript:
            # Include segment if it overlaps with the range
            if seg["end"] > start and seg["start"] < end:
                texts.append(seg["text"])
        return " ".join(texts).strip()

    async def _describe_scenes(
        self, video_path: str, scenes: List[Tuple[float, float]]
    ) -> List[Dict[str, Any]]:
        """Generate VLM descriptions for each scene with bounded concurrency.

        Args:
            video_path: Path to video file
            scenes: List of (start, end) tuples

        Returns:
            List of scene dicts with start, end, visual description (ordered)
        """
        concurrency = max(1, getattr(self.lightrag, "max_parallel_insert", 2))
        semaphore = asyncio.Semaphore(concurrency)

        async def describe_one(start: float, end: float) -> Dict[str, Any]:
            async with semaphore:
                mid_time = (start + end) / 2
                frame_path = await asyncio.to_thread(
                    self._extract_frame_at, video_path, mid_time
                )

                visual_desc = ""
                if frame_path:
                    try:
                        with open(frame_path, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("utf-8")

                        prompt = (
                            f"Describe this video frame in detail. "
                            f"This is from a video at approximately "
                            f"{self._format_timestamp(mid_time)}. "
                            f"Include: what is shown, any text/UI visible, "
                            f"people/objects present, and the overall context. "
                            f"If the frame is a solid color or otherwise minimal, "
                            f"still describe what is visible (e.g. the dominant color)."
                        )
                        visual_desc = await self.modal_caption_func(
                            prompt,
                            image_data=image_base64,
                            system_prompt=PROMPTS["IMAGE_ANALYSIS_SYSTEM"],
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to describe frame at {mid_time:.1f}s: {e}"
                        )
                    finally:
                        if os.path.exists(frame_path):
                            os.remove(frame_path)

                return {"start": start, "end": end, "visual": visual_desc}

        results = await asyncio.gather(
            *(describe_one(start, end) for start, end in scenes),
            return_exceptions=True,
        )

        scene_segments = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Scene description task failed: {result}")
                continue
            scene_segments.append(result)
        return scene_segments

    async def _transcribe_audio_track(self, video_path: str) -> List[Dict[str, Any]]:
        """Extract and transcribe the audio track once (off the event loop)."""
        audio_path = await asyncio.to_thread(self._extract_audio_track, video_path)
        if not audio_path:
            return []
        try:
            return await asyncio.to_thread(self.audio_processor.transcribe, audio_path)
        except Exception as e:
            logger.warning(f"Audio transcription failed: {e}")
            return []
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)

    def _merge_channels(
        self,
        visual_segments: List[Dict[str, Any]],
        audio_segments: List[Dict[str, Any]],
    ) -> str:
        """Merge visual and audio channels by timestamp alignment.

        Args:
            visual_segments: Scene descriptions with start/end/visual
            audio_segments: Transcription segments with start/end/text

        Returns:
            Formatted text with aligned visual + audio per scene
        """
        lines = []
        for vs in visual_segments:
            start_str = self._format_timestamp(vs["start"])
            end_str = self._format_timestamp(vs["end"])

            # Find audio transcript in this time range
            audio_text = self._get_transcript_in_range(
                audio_segments, vs["start"], vs["end"]
            )

            line = f"[{start_str}-{end_str}]"
            if vs.get("visual"):
                line += f" 画面：{vs['visual']}"
            if audio_text:
                line += f" | 语音：{audio_text}"

            # Only add if we have at least one channel
            if vs.get("visual") or audio_text:
                lines.append(line)

        return "\n\n".join(lines)

    def _plan_windows(
        self, visual_segments: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Group ordered scene descriptions into windows.

        A window is bounded by both ``max_scenes`` (scene count) and the chunk
        token budget. If the number of windows would exceed ``max_windows``, the
        scenes are redistributed evenly into ``max_windows`` groups so the chunk
        count stays bounded without dropping any scene.
        """
        if not visual_segments:
            return []

        budget = self._chunk_token_budget()
        windows: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_tokens = 0

        for seg in visual_segments:
            seg_tokens = self._count_tokens(seg.get("visual", "") or "")
            too_many = len(current) >= self.max_scenes
            too_big = bool(current) and current_tokens + seg_tokens > budget
            if current and (too_many or too_big):
                windows.append(current)
                current = []
                current_tokens = 0
            current.append(seg)
            current_tokens += seg_tokens

        if current:
            windows.append(current)

        if self.max_windows and len(windows) > self.max_windows:
            logger.warning(
                f"Video produced {len(windows)} windows, exceeding max_windows="
                f"{self.max_windows}; redistributing {len(visual_segments)} scenes "
                f"into {self.max_windows} windows."
            )
            windows = self._redistribute(visual_segments, self.max_windows)

        return windows

    @staticmethod
    def _redistribute(
        items: List[Dict[str, Any]], groups: int
    ) -> List[List[Dict[str, Any]]]:
        """Split items into at most ``groups`` near-equal, order-preserving groups."""
        n = len(items)
        size = (n + groups - 1) // groups  # ceil
        return [items[i : i + size] for i in range(0, n, size)]

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate a single merged description for the whole video.

        For long videos the batch pipeline uses :meth:`generate_chunk_sections`
        instead, which splits the analysis into multiple ordered chunks.

        Returns:
            Tuple of (merged_description, entity_info)
        """
        try:
            video_path = self._resolve_video_path(modal_content)
            if not video_path:
                raise ValueError(
                    f"No video path provided in modal_content: {modal_content}"
                )
            if not Path(video_path).exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            logger.info(f"Processing video: {video_path}")

            scenes = await asyncio.to_thread(self._detect_scenes, video_path)
            logger.info(f"Detected {len(scenes)} scenes")

            visual_segments = await self._describe_scenes(video_path, scenes)
            audio_segments = await self._transcribe_audio_track(video_path)

            merged_description = self._merge_channels(visual_segments, audio_segments)
            if not merged_description:
                merged_description = f"Video file: {Path(video_path).name}"

            filename = Path(video_path).stem
            total_duration = scenes[-1][1] if scenes else 0
            entity_info = {
                "entity_name": entity_name if entity_name else f"video_{filename}",
                "entity_type": "video",
                "summary": (
                    f"Video ({self._format_timestamp(total_duration)} duration, "
                    f"{len(scenes)} scenes). "
                    f"{merged_description[:150]}..."
                ),
            }

            return merged_description, entity_info

        except Exception as e:
            logger.error(f"Error generating video description: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    @staticmethod
    def _section_entity_name(
        entity_name: str, filename: str, part: int, total: int
    ) -> str:
        """Build a unique entity name per section."""
        base = entity_name if entity_name else f"video_{filename}"
        return base if total == 1 else f"{base}_part{part}"

    async def generate_chunk_sections(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> List[Dict[str, Any]]:
        """Analyze the video and split it into one or more ordered sections.

        Scene detection and audio transcription run once for the whole video;
        scenes are then grouped into windows (bounded by ``max_scenes`` and the
        token budget). Audio that extends past the last scene is appended to the
        final window as an audio-only row so nothing is dropped.
        """
        try:
            video_path = self._resolve_video_path(modal_content)
            if not video_path:
                raise ValueError(
                    f"No video path provided in modal_content: {modal_content}"
                )
            if not Path(video_path).exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            logger.info(f"Processing video: {video_path}")

            scenes = await asyncio.to_thread(self._detect_scenes, video_path)
            if not scenes:
                raise RuntimeError(f"No scenes detected in video: {video_path}")
            logger.info(f"Detected {len(scenes)} scenes")

            visual_segments = await self._describe_scenes(video_path, scenes)
            audio_segments = await self._transcribe_audio_track(video_path)

            # Capture audio beyond the last visual scene as a trailing audio-only row
            if visual_segments and audio_segments:
                last_end = visual_segments[-1]["end"]
                tail = [a for a in audio_segments if a["start"] >= last_end]
                if tail:
                    visual_segments.append(
                        {"start": last_end, "end": tail[-1]["end"], "visual": ""}
                    )

            windows = self._plan_windows(visual_segments)
            total = len(windows)
            filename = Path(video_path).stem

            sections: List[Dict[str, Any]] = []
            for k, window in enumerate(windows, start=1):
                win_start = window[0]["start"]
                win_end = window[-1]["end"]
                text = self._merge_channels(window, audio_segments)
                if not text:
                    text = (
                        f"Video file: {Path(video_path).name} "
                        f"({self._format_timestamp(win_start)}-"
                        f"{self._format_timestamp(win_end)})"
                    )
                name = self._section_entity_name(entity_name, filename, k, total)
                part_label = "" if total == 1 else f" part {k}/{total}"
                entity_info = {
                    "entity_name": name,
                    "entity_type": "video",
                    "summary": (
                        f"Video{part_label} "
                        f"({self._format_timestamp(win_start)}-"
                        f"{self._format_timestamp(win_end)}, {len(window)} scenes). "
                        f"{text[:150]}..."
                    ),
                }
                window_meta = (
                    None
                    if total == 1
                    else {
                        "start": win_start,
                        "end": win_end,
                        "part": k,
                        "total": total,
                    }
                )
                sections.append(
                    {
                        "description": text,
                        "entity_info": entity_info,
                        "window_meta": window_meta,
                    }
                )

            return sections

        except Exception as e:
            logger.error(f"Error generating video sections: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
            }
            return [
                {
                    "description": str(modal_content),
                    "entity_info": fallback_entity,
                    "window_meta": None,
                }
            ]

    @staticmethod
    def _build_video_chunk(video_path: str, section: Dict[str, Any]) -> str:
        """Format a single video section into chunk text."""
        meta = section.get("window_meta")
        header = "[Video Content]"
        if meta:
            header += f" — part {meta['part']}/{meta['total']}"
        return (
            f"{header}\n"
            f"Source: {video_path}\n"
            f"Entity: {section['entity_info']['entity_name']}\n"
            f"Analysis:\n{section['description']}"
        )

    async def process_multimodal_content(
        self,
        modal_content,
        content_type: str,
        file_path: str = "manual_creation",
        entity_name: str = None,
        item_info: Dict[str, Any] = None,
        batch_mode: bool = False,
        doc_id: str = None,
        chunk_order_index: int = 0,
    ) -> Tuple[str, Dict[str, Any], List[Any]]:
        """Process video content: analyze and insert into knowledge graph.

        Long videos produce multiple ordered chunks; each section is stored with a
        sequential ``chunk_order_index`` starting at the supplied value.

        Returns:
            Tuple of (primary_summary, primary_entity_info, all_chunk_results)
        """
        try:
            sections = await self.generate_chunk_sections(
                modal_content, content_type, item_info, entity_name
            )
            video_path = self._resolve_video_path(modal_content)

            all_chunk_results: List[Any] = []
            section_chunk_ids: List[str] = []
            primary_summary = None
            primary_entity = None

            for offset, section in enumerate(sections):
                modal_chunk = self._build_video_chunk(video_path, section)
                (
                    summary,
                    entity_ret,
                    chunk_results,
                ) = await self._create_entity_and_chunk(
                    modal_chunk,
                    section["entity_info"],
                    file_path,
                    batch_mode,
                    doc_id,
                    chunk_order_index + offset,
                )
                all_chunk_results.extend(chunk_results)
                if entity_ret.get("chunk_id"):
                    section_chunk_ids.append(entity_ret["chunk_id"])
                if primary_summary is None:
                    primary_summary = summary
                    primary_entity = entity_ret

            # Expose every section's chunk id so the caller can register them all
            if primary_entity is not None:
                primary_entity["chunk_ids"] = section_chunk_ids

            return primary_summary, primary_entity, all_chunk_results

        except Exception as e:
            logger.error(f"Error processing video content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity, []
