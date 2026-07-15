"""
Video Modal Processor for RAG-Anything

Processes video files (MP4, MOV, WebM, AVI, MKV) with dual-channel analysis:
- Visual channel: scene detection + keyframe extraction + VLM description
- Audio channel: audio track extraction + faster-whisper transcription

Results are merged by timestamp, producing rich text descriptions like:
    [0:00-0:30] 画面：展示Q3营收图表 | 语音：本季度同比增长23%...

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

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
from lightrag.utils import compute_mdhash_id

from .modalprocessors import BaseModalProcessor
from .modalprocessors_audio import AudioModalProcessor

logger = logging.getLogger(__name__)

# Supported video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".flv", ".wmv", ".m4v"}


def is_video_file(file_path: str) -> bool:
    """Check if a file is a supported video format."""
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS


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
            max_scenes: Maximum number of scenes to process
            scene_threshold: ContentDetector threshold (lower = more sensitive)
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

        # Lazy-loaded audio processor (shares whisper model config)
        self._audio_processor = None

    @property
    def audio_processor(self) -> AudioModalProcessor:
        """Get or create audio processor for transcription."""
        if self._audio_processor is None:
            self._audio_processor = AudioModalProcessor(
                lightrag=self.lightrag,
                modal_caption_func=self.modal_caption_func,
                whisper_model=self.whisper_model_name,
                whisper_device=self.whisper_device,
                whisper_compute_type=self.whisper_compute_type,
                language=self.language,
                segment_min_length=10,
            )
        return self._audio_processor

    def _detect_scenes(self, video_path: str) -> List[Tuple[float, float]]:
        """Detect scene boundaries using SceneDetect.

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
            cap = cv2.VideoCapture(video_path)
            total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            if fps > 0:
                total_duration = total_frames / fps
                scenes = [(0, total_duration)]

        # Limit number of scenes
        return scenes[: self.max_scenes]

    def _extract_frame_at(self, video_path: str, timestamp: float) -> Optional[str]:
        """Extract a single frame at the given timestamp.

        Args:
            video_path: Path to video file
            timestamp: Time in seconds

        Returns:
            Path to saved frame image, or None on failure
        """
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

        # Save to temp file
        frame_path = os.path.join(
            tempfile.gettempdir(),
            f"raganything_vframe_{os.getpid()}_{timestamp:.1f}.jpg",
        )
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

        audio_path = os.path.join(
            tempfile.gettempdir(),
            f"raganything_vaudio_{os.getpid()}.wav",
        )

        try:
            clip = VideoFileClip(video_path)
            if clip.audio is None:
                clip.close()
                return None
            clip.audio.write_audiofile(audio_path, logger=None)
            clip.close()
            return audio_path
        except Exception as e:
            logger.warning(f"Failed to extract audio from {video_path}: {e}")
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
        """Generate VLM descriptions for each scene.

        Args:
            video_path: Path to video file
            scenes: List of (start, end) tuples

        Returns:
            List of scene dicts with start, end, visual description
        """
        results = []
        for start, end in scenes:
            # Extract frame from middle of scene
            mid_time = (start + end) / 2
            frame_path = self._extract_frame_at(video_path, mid_time)

            visual_desc = ""
            if frame_path:
                try:
                    # Encode frame to base64 for VLM
                    import base64

                    with open(frame_path, "rb") as f:
                        image_base64 = base64.b64encode(f.read()).decode("utf-8")

                    prompt = (
                        f"Describe this video frame in detail. "
                        f"This is from a video at approximately "
                        f"{self._format_timestamp(mid_time)}. "
                        f"Include: what is shown, any text/UI visible, "
                        f"people/objects present, and the overall context."
                    )
                    visual_desc = await self.modal_caption_func(
                        prompt, image_data=image_base64
                    )
                except Exception as e:
                    logger.warning(f"Failed to describe frame at {mid_time:.1f}s: {e}")
                finally:
                    if os.path.exists(frame_path):
                        os.remove(frame_path)

            results.append({"start": start, "end": end, "visual": visual_desc})

        return results

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

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate video description using dual-channel analysis.

        Args:
            modal_content: Video content dict with 'video_path' key
            content_type: Type of modal content ("video")
            item_info: Item information for context
            entity_name: Optional predefined entity name

        Returns:
            Tuple of (merged_description, entity_info)
        """
        try:
            # Parse video content
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"video_path": modal_content}
            else:
                content_data = modal_content

            video_path = content_data.get("video_path") or content_data.get("img_path")
            if not video_path:
                raise ValueError(
                    f"No video path provided in modal_content: {modal_content}"
                )

            if not Path(video_path).exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            logger.info(f"Processing video: {video_path}")

            # Step 1: Detect scenes
            scenes = self._detect_scenes(video_path)
            logger.info(f"Detected {len(scenes)} scenes")

            # Step 2: Visual channel - describe each scene
            visual_segments = await self._describe_scenes(video_path, scenes)

            # Step 3: Audio channel - extract and transcribe
            audio_segments = []
            audio_path = self._extract_audio_track(video_path)
            if audio_path:
                try:
                    audio_segments = self.audio_processor.transcribe(audio_path)
                except Exception as e:
                    logger.warning(f"Audio transcription failed: {e}")
                finally:
                    if os.path.exists(audio_path):
                        os.remove(audio_path)

            # Step 4: Merge by timestamp
            merged_description = self._merge_channels(visual_segments, audio_segments)

            if not merged_description:
                merged_description = f"Video file: {Path(video_path).name}"

            # Generate entity info
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
    ) -> Tuple[str, Dict[str, Any]]:
        """Process video content: analyze and insert into knowledge graph.

        Args:
            modal_content: Video content dict with 'video_path' key
            content_type: Type of modal content ("video")
            file_path: Source file path for attribution
            entity_name: Optional entity name
            item_info: Item info for context
            batch_mode: Whether in batch processing mode
            doc_id: Document ID
            chunk_order_index: Chunk ordering index

        Returns:
            Tuple of (chunk_text, entity_info)
        """
        try:
            # Generate description using dual-channel analysis
            description, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            # Parse video path
            if isinstance(modal_content, str):
                try:
                    content_data = json.loads(modal_content)
                except json.JSONDecodeError:
                    content_data = {"video_path": modal_content}
            else:
                content_data = modal_content

            video_path = content_data.get("video_path") or content_data.get(
                "img_path", ""
            )

            # Build video chunk text
            modal_chunk = (
                f"[Video Content]\n"
                f"Source: {video_path}\n"
                f"Entity: {entity_info['entity_name']}\n"
                f"Analysis:\n{description}"
            )

            return await self._create_entity_and_chunk(
                modal_chunk,
                entity_info,
                file_path,
                batch_mode,
                doc_id,
                chunk_order_index,
            )

        except Exception as e:
            logger.error(f"Error processing video content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity
