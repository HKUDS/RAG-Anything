"""
Audio Modal Processor for RAG-Anything

Processes audio files (MP3, WAV, FLAC, M4A, OGG) by transcribing speech to text
using faster-whisper, then feeding the transcribed text into LightRAG's knowledge graph.

Supports:
- Speech-to-text transcription with timestamps
- Meeting recordings, phone calls, podcasts, lectures
- Multiple languages (auto-detect or specify)
- Long recordings are split into multiple token-bounded chunks (see
  ``generate_chunk_sections``)

Dependencies:
    pip install raganything[audio]
    # or: pip install faster-whisper "av<19"
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import inspect
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.request
import uuid

from lightrag.utils import compute_mdhash_id

from .modalprocessors import BaseModalProcessor

logger = logging.getLogger(__name__)

# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".opus"}

# Supported ASR architecture modes
SUPPORTED_ASR_MODES = {"local", "online", "custom"}


def is_audio_file(file_path: str) -> bool:
    """Check if a file is a supported audio format."""
    return Path(file_path).suffix.lower() in AUDIO_EXTENSIONS


def _resolve_asr_mode(
    asr_mode: Optional[str] = None,
    asr_func: Optional[Callable] = None,
) -> str:
    """Resolve effective ASR mode from explicit argument, custom callable, or env."""
    if asr_mode is not None and str(asr_mode).strip():
        return str(asr_mode).strip().lower()
    if asr_func is not None:
        return "custom"
    env_mode = os.environ.get("ASR_MODE", "").strip().lower()
    return env_mode if env_mode else "local"


def audio_deps_available(
    asr_mode: Optional[str] = None,
    asr_func: Optional[Callable] = None,
) -> bool:
    """Return True if the required dependencies for the configured ASR mode are available.

    - ``local`` mode requires ``faster_whisper``.
    - ``online`` mode uses standard library HTTP/multipart or an OpenAI-compatible
      endpoint and does not require ``faster_whisper``.
    - ``custom`` mode delegates to a user-provided ``asr_func`` and does not
      require ``faster_whisper``.
    """
    mode = _resolve_asr_mode(asr_mode=asr_mode, asr_func=asr_func)
    if mode == "online":
        return True
    if mode == "custom":
        return asr_func is not None or asr_mode is not None
    return importlib.util.find_spec("faster_whisper") is not None


class AudioModalProcessor(BaseModalProcessor):
    """Processor for audio content supporting multiple ASR architecture modes.

    Supported ASR modes (``asr_mode``):
    - ``"local"`` (default): Uses local ``faster-whisper`` model inference.
    - ``"online"``: Calls an OpenAI-compatible ``/audio/transcriptions`` HTTP API
      (e.g., OpenAI Whisper API, Groq, vLLM, DashScope/SiliconFlow compatible endpoints).
    - ``"custom"``: Invokes a user-supplied ``asr_func`` callable (sync or async).

    Transcribes audio files into timestamped text segments, then processes
    them through LightRAG for knowledge graph construction and retrieval.

    Suitable for:
    - Meeting recordings
    - Phone call recordings
    - Podcasts and interviews
    - Lectures and presentations
    - Voice memos

    Example:
        >>> processor = AudioModalProcessor(
        ...     lightrag=rag_instance,
        ...     modal_caption_func=caption_func,
        ...     whisper_model="large-v3",
        ... )
        >>> result = await processor.process_multimodal_content(
        ...     modal_content={"audio_path": "/path/to/meeting.mp3"},
        ...     content_type="audio",
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
        segment_min_length: int = 0,
        asr_mode: str = None,
        asr_model: str = None,
        asr_api_key: str = None,
        asr_base_url: str = None,
        asr_func: Optional[Callable] = None,
        asr_timeout: float = 120.0,
    ):
        """Initialize audio processor.

        Args:
            lightrag: LightRAG instance
            modal_caption_func: Function for generating descriptions
            context_extractor: Context extractor instance
            whisper_model: Whisper model size (tiny/base/small/medium/large-v3)
                          Defaults to env WHISPER_MODEL or "base"
            whisper_device: Device for inference ("auto", "cpu", "cuda")
            whisper_compute_type: Compute type ("auto", "float16", "int8")
            language: Language code (e.g., "zh", "en"). None for auto-detect.
            segment_min_length: Minimum segment length in characters to keep.
                Defaults to 0 (keep every non-empty segment); raising it drops
                short utterances such as "Yes." or "Revenue grew 23%.", so only
                increase it when you explicitly want to filter noise.
            asr_mode: ASR architecture mode ("local", "online", or "custom").
                Defaults to "custom" when ``asr_func`` is provided, otherwise
                env ``ASR_MODE`` or "local".
            asr_model: Model identifier for ASR. Defaults to ``whisper_model`` /
                ``WHISPER_MODEL`` ("base") in local mode, or "whisper-1" in online mode.
            asr_api_key: API key for online ASR endpoint (falls back to
                ``ASR_API_KEY`` or ``OPENAI_API_KEY``).
            asr_base_url: Base URL for online OpenAI-compatible ASR endpoint
                (falls back to ``ASR_BASE_URL``, ``OPENAI_BASE_URL``, or
                "https://api.openai.com/v1").
            asr_func: Custom transcription callable (sync or async) used when
                ``asr_mode="custom"``. Accepts ``audio_path`` (and optionally
                ``language`` / ``model``) and returns a list of segment dicts,
                an OpenAI-style transcription dict, or a plain string.
            asr_timeout: Request timeout in seconds for online ASR calls.
        """
        super().__init__(lightrag, modal_caption_func, context_extractor)

        resolved_mode = _resolve_asr_mode(asr_mode=asr_mode, asr_func=asr_func)
        if resolved_mode not in SUPPORTED_ASR_MODES:
            raise ValueError(
                f"Unsupported asr_mode '{asr_mode}'. "
                f"Supported modes are: {', '.join(sorted(SUPPORTED_ASR_MODES))}"
            )
        if resolved_mode == "custom" and not callable(asr_func):
            raise ValueError("asr_func must be a callable when asr_mode='custom'")

        self.asr_mode = resolved_mode
        self.asr_func = asr_func
        self.asr_timeout = asr_timeout

        env_asr_model = os.environ.get("ASR_MODEL", "").strip()
        self.whisper_model_name = (
            whisper_model
            or (asr_model if asr_model else None)
            or (env_asr_model if env_asr_model else None)
            or os.environ.get("WHISPER_MODEL", "base")
        )
        if self.asr_mode == "online":
            self.asr_model = (
                (asr_model if asr_model else None)
                or whisper_model
                or (env_asr_model if env_asr_model else None)
                or "whisper-1"
            )
        else:
            self.asr_model = self.whisper_model_name

        self.asr_api_key = (
            (asr_api_key if asr_api_key else None)
            or os.environ.get("ASR_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        raw_base_url = (
            (asr_base_url if asr_base_url else None)
            or os.environ.get("ASR_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        self.asr_base_url = raw_base_url.rstrip("/")

        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        env_lang = (
            os.environ.get("ASR_LANGUAGE") or os.environ.get("WHISPER_LANGUAGE") or None
        )
        self.language = language if language else env_lang
        self.segment_min_length = segment_min_length
        self._whisper_model = None

    @property
    def whisper(self):
        """Lazy-load whisper model on first use."""
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ImportError(
                    "faster-whisper is required for audio processing. "
                    "Install it with: pip install raganything[audio] "
                    'or: pip install faster-whisper "av<19"'
                )

            logger.info(
                f"Loading whisper model: {self.whisper_model_name} "
                f"(device={self.whisper_device})"
            )
            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type,
            )
        return self._whisper_model

    @staticmethod
    def _resolve_audio_path(modal_content) -> str:
        """Extract the audio path from dict/JSON/string modal content."""
        if isinstance(modal_content, str):
            try:
                content_data = json.loads(modal_content)
            except json.JSONDecodeError:
                return modal_content
        else:
            content_data = modal_content
        return content_data.get("audio_path") or content_data.get("img_path") or ""

    def _normalize_segments(self, raw_result: Any) -> List[Dict[str, Any]]:
        """Normalize raw ASR output into filtered ``[{"start", "end", "text"}]`` segments.

        Supports:
        - Iterables/lists of segment dicts ``{"start": ..., "end": ..., "text": ...}``
          or segment objects with ``.start``, ``.end``, ``.text`` attributes.
        - OpenAI ``verbose_json`` / ``json`` style dicts or objects containing
          ``segments`` and/or ``text`` + optional ``duration``.
        - Plain transcription strings.
        """
        if raw_result is None:
            return []

        if isinstance(raw_result, str):
            text = raw_result.strip()
            if text and len(text) >= self.segment_min_length:
                return [{"start": 0.0, "end": 0.0, "text": text}]
            return []

        if isinstance(raw_result, dict):
            if isinstance(raw_result.get("segments"), (list, tuple)):
                segments = self._normalize_segments(raw_result["segments"])
                if segments:
                    return segments
            if "text" in raw_result and "start" not in raw_result:
                text = str(raw_result.get("text") or "").strip()
                if text and len(text) >= self.segment_min_length:
                    end_val = raw_result.get("duration", raw_result.get("end", 0.0))
                    return [
                        {
                            "start": float(raw_result.get("start", 0.0) or 0.0),
                            "end": float(end_val or 0.0),
                            "text": text,
                        }
                    ]
                return []

        # Handle SDK objects (e.g., OpenAI TranscriptionVerbose / Transcription)
        if not isinstance(raw_result, (dict, list, tuple)) and (
            hasattr(raw_result, "segments") or hasattr(raw_result, "text")
        ):
            raw_segments = getattr(raw_result, "segments", None)
            if isinstance(raw_segments, (list, tuple)) and raw_segments:
                segments = self._normalize_segments(raw_segments)
                if segments:
                    return segments
            if hasattr(raw_result, "text") and not hasattr(raw_result, "start"):
                text = str(getattr(raw_result, "text", "") or "").strip()
                if text and len(text) >= self.segment_min_length:
                    duration = getattr(raw_result, "duration", 0.0) or 0.0
                    return [{"start": 0.0, "end": float(duration), "text": text}]
                return []

        segments: List[Dict[str, Any]] = []
        for item in raw_result:
            if isinstance(item, dict):
                raw_text = item.get("text", "")
                start = item.get("start", 0.0)
                end = item.get("end", start)
            else:
                raw_text = getattr(item, "text", "")
                start = getattr(item, "start", 0.0)
                end = getattr(item, "end", start)

            text = str(raw_text or "").strip()
            if text and len(text) >= self.segment_min_length:
                start_num = (
                    start if isinstance(start, (int, float)) else float(start or 0.0)
                )
                end_num = (
                    end
                    if isinstance(end, (int, float))
                    else float(end if end is not None else start_num)
                )
                segments.append(
                    {
                        "start": start_num,
                        "end": end_num,
                        "text": text,
                    }
                )
        return segments

    def _transcribe_local(self, audio_path: str) -> List[Dict[str, Any]]:
        """Transcribe audio using local faster-whisper model."""
        segments_iter, info = self.whisper.transcribe(
            audio_path,
            language=self.language,
            vad_filter=True,  # Filter out silence
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        segments = self._normalize_segments(segments_iter)
        logger.info(
            f"Transcription complete (local): {len(segments)} segments, "
            f"language={getattr(info, 'language', self.language)}, "
            f"duration={getattr(info, 'duration', 0.0):.1f}s"
        )
        return segments

    def _build_multipart_form_data(
        self,
        fields: Dict[str, str],
        file_field: str,
        filename: str,
        file_bytes: bytes,
        content_type: str,
    ) -> Tuple[bytes, str]:
        """Encode multipart/form-data body without external HTTP library dependencies."""
        boundary = f"----RAGAnythingASRBoundary{uuid.uuid4().hex}"
        body = bytearray()

        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8")
            )
            body.extend(f"{value}\r\n".encode("utf-8"))

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        return bytes(body), f"multipart/form-data; boundary={boundary}"

    def _transcribe_online(self, audio_path: str) -> List[Dict[str, Any]]:
        """Transcribe audio via an OpenAI-compatible ``/audio/transcriptions`` API."""
        if not self.asr_api_key:
            raise ValueError(
                "API key is required for online ASR mode. "
                "Provide asr_api_key or set ASR_API_KEY / OPENAI_API_KEY."
            )

        endpoint = (
            self.asr_base_url
            if self.asr_base_url.endswith("/audio/transcriptions")
            else f"{self.asr_base_url}/audio/transcriptions"
        )

        audio_file = Path(audio_path)
        mime_type, _ = mimetypes.guess_type(audio_file.name)
        content_type = mime_type or "application/octet-stream"

        fields: Dict[str, str] = {
            "model": self.asr_model,
            "response_format": "verbose_json",
        }
        if self.language:
            fields["language"] = self.language

        body, content_type_header = self._build_multipart_form_data(
            fields=fields,
            file_field="file",
            filename=audio_file.name,
            file_bytes=audio_file.read_bytes(),
            content_type=content_type,
        )

        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.asr_api_key}",
                "Content-Type": content_type_header,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.asr_timeout) as resp:
                raw_bytes = resp.read()
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"Online ASR request failed with HTTP {e.code}: {err_body or e.reason}"
            ) from e

        decoded = raw_bytes.decode("utf-8", errors="replace")
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            payload = decoded

        segments = self._normalize_segments(payload)
        logger.info(
            f"Transcription complete (online, model={self.asr_model}): "
            f"{len(segments)} segments"
        )
        return segments

    def _transcribe_custom(self, audio_path: str) -> List[Dict[str, Any]]:
        """Transcribe audio using user-provided ``asr_func`` (sync or async)."""
        if not callable(self.asr_func):
            raise ValueError("asr_func must be a callable when asr_mode='custom'")

        kwargs: Dict[str, Any] = {}
        try:
            sig = inspect.signature(self.asr_func)
            params = sig.parameters
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if "language" in params or accepts_var_kw:
                if self.language is not None:
                    kwargs["language"] = self.language
            if "model" in params or accepts_var_kw:
                if self.asr_model:
                    kwargs["model"] = self.asr_model
        except (TypeError, ValueError):
            pass

        result = self.asr_func(audio_path, **kwargs)
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(asyncio.run, result).result()
            else:
                result = asyncio.run(result)

        segments = self._normalize_segments(result)
        logger.info(f"Transcription complete (custom): {len(segments)} segments")
        return segments

    def transcribe(self, audio_path: str) -> List[Dict[str, Any]]:
        """Transcribe audio file to timestamped segments.

        Note: this is a blocking call; async callers should wrap it with
        ``asyncio.to_thread`` so it does not block the event loop.

        Args:
            audio_path: Path to the audio file

        Returns:
            List of segments with start, end (seconds) and text
        """
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Transcribing audio ({self.asr_mode}): {audio_path}")

        if self.asr_mode == "online":
            return self._transcribe_online(audio_path)
        if self.asr_mode == "custom":
            return self._transcribe_custom(audio_path)
        return self._transcribe_local(audio_path)

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS or MM:SS."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _segments_to_text(self, segments: List[Dict[str, Any]]) -> str:
        """Convert transcription segments to formatted text with timestamps."""
        lines = []
        for seg in segments:
            start_str = self._format_timestamp(seg["start"])
            end_str = self._format_timestamp(seg["end"])
            lines.append(f"[{start_str}-{end_str}] {seg['text']}")
        return "\n".join(lines)

    def _group_segments_by_tokens(
        self, segments: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Group ordered segments into windows bounded by the chunk token budget.

        Segments are never split mid-utterance, so timestamp alignment is kept.
        A single oversized segment becomes its own window.
        """
        if not segments:
            return []

        budget = self._chunk_token_budget()
        windows: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_tokens = 0

        for seg in segments:
            seg_tokens = self._count_tokens(seg["text"])
            if current and current_tokens + seg_tokens > budget:
                windows.append(current)
                current = []
                current_tokens = 0
            current.append(seg)
            current_tokens += seg_tokens

        if current:
            windows.append(current)
        return windows

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate the full audio transcription and entity info (single description).

        Returns the whole recording as one description. For long recordings the
        batch pipeline uses :meth:`generate_chunk_sections` instead, which splits
        the transcription into multiple token-bounded chunks.

        Returns:
            Tuple of (transcription_text, entity_info)
        """
        try:
            audio_path = self._resolve_audio_path(modal_content)
            if not audio_path:
                raise ValueError(
                    f"No audio path provided in modal_content: {modal_content}"
                )

            segments = await asyncio.to_thread(self.transcribe, audio_path)
            if not segments:
                raise RuntimeError(f"No speech detected in audio: {audio_path}")

            transcription = self._segments_to_text(segments)

            filename = Path(audio_path).stem
            duration = segments[-1]["end"] if segments else 0
            entity_info = {
                "entity_name": entity_name if entity_name else f"audio_{filename}",
                "entity_type": "audio",
                "summary": (
                    f"Audio recording ({self._format_timestamp(duration)} duration). "
                    f"Transcription: {segments[0]['text'][:100]}..."
                    if segments
                    else "Empty audio"
                ),
            }

            return transcription, entity_info

        except Exception as e:
            logger.error(f"Error generating audio transcription: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity

    @staticmethod
    def _section_entity_name(
        entity_name: str, filename: str, part: int, total: int
    ) -> str:
        """Build a unique entity name per section."""
        base = entity_name if entity_name else f"audio_{filename}"
        return base if total == 1 else f"{base}_part{part}"

    async def generate_chunk_sections(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> List[Dict[str, Any]]:
        """Transcribe the audio and split it into one or more token-bounded sections.

        Short recordings yield a single section (equivalent to the legacy single
        chunk). Long recordings are split into multiple ordered sections so the
        transcription is not stored as one oversized chunk.
        """
        try:
            audio_path = self._resolve_audio_path(modal_content)
            if not audio_path:
                raise ValueError(
                    f"No audio path provided in modal_content: {modal_content}"
                )

            segments = await asyncio.to_thread(self.transcribe, audio_path)
            if not segments:
                raise RuntimeError(f"No speech detected in audio: {audio_path}")

            filename = Path(audio_path).stem
            windows = self._group_segments_by_tokens(segments)
            total = len(windows)

            sections: List[Dict[str, Any]] = []
            for k, window in enumerate(windows, start=1):
                text = self._segments_to_text(window)
                start = window[0]["start"]
                end = window[-1]["end"]
                name = self._section_entity_name(entity_name, filename, k, total)
                part_label = "" if total == 1 else f" part {k}/{total}"
                entity_info = {
                    "entity_name": name,
                    "entity_type": "audio",
                    "summary": (
                        f"Audio recording{part_label} "
                        f"({self._format_timestamp(start)}-{self._format_timestamp(end)}). "
                        f"Transcription: {window[0]['text'][:100]}..."
                    ),
                }
                window_meta = (
                    None
                    if total == 1
                    else {"start": start, "end": end, "part": k, "total": total}
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
            logger.error(f"Error generating audio sections: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return [
                {
                    "description": str(modal_content),
                    "entity_info": fallback_entity,
                    "window_meta": None,
                }
            ]

    @staticmethod
    def _build_audio_chunk(audio_path: str, section: Dict[str, Any]) -> str:
        """Format a single audio section into chunk text."""
        meta = section.get("window_meta")
        header = "[Audio Content]"
        if meta:
            header += f" — part {meta['part']}/{meta['total']}"
        return (
            f"{header}\n"
            f"Source: {audio_path}\n"
            f"Entity: {section['entity_info']['entity_name']}\n"
            f"Transcription:\n{section['description']}"
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
        """Process audio content: transcribe and insert into knowledge graph.

        Long recordings produce multiple ordered chunks; each section is stored
        with a sequential ``chunk_order_index`` starting at the supplied value.

        Returns:
            Tuple of (primary_summary, primary_entity_info, all_chunk_results)
        """
        try:
            sections = await self.generate_chunk_sections(
                modal_content, content_type, item_info, entity_name
            )
            audio_path = self._resolve_audio_path(modal_content)

            all_chunk_results: List[Any] = []
            section_chunk_ids: List[str] = []
            primary_summary = None
            primary_entity = None

            for offset, section in enumerate(sections):
                modal_chunk = self._build_audio_chunk(audio_path, section)
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
            logger.error(f"Error processing audio content: {e}")
            fallback_entity = {
                "entity_name": entity_name
                if entity_name
                else f"audio_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "audio",
                "summary": f"Audio content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity, []
