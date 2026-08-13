"""
TwelveLabs video modality processor for RAGAnything.

Adds a "video" modality backed by the TwelveLabs platform:

- **Pegasus** (``analyze``) generates a rich textual description / transcript of
  the video. This text feeds the existing knowledge-graph / chunk pipeline just
  like any other modality.
- **Marengo** (``embed``) produces a 512-dim multimodal embedding for the video
  (or a text query). The embedding is returned on the modal item's ``entity_info``
  (key ``tl_video_embedding``) so callers can index it for semantic video
  retrieval; pair it with :meth:`embed_text` to score a text query in the same
  512-dim space.

The processor mirrors :class:`raganything.modalprocessors.GenericModalProcessor`
and reuses :meth:`BaseModalProcessor._create_entity_and_chunk`, so video content
flows through the same entity/relationship extraction machinery as images,
tables and equations.

This is an **opt-in** modality: it is only registered when
``enable_video_processing`` is True (env ``ENABLE_VIDEO_PROCESSING``) and the
``twelvelabs`` package is installed. Existing behaviour is unchanged when it is
disabled.

A "video" multimodal item looks like::

    {"type": "video", "video_url": "https://.../clip.mp4", "video_caption": ["..."]}
    {"type": "video", "video_path": "/abs/path/clip.mp4"}
    {"type": "video", "video_id": "<indexed-video-id>"}

Get a free API key at https://twelvelabs.io (generous free tier).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lightrag.utils import compute_mdhash_id, logger
from lightrag.lightrag import LightRAG

from raganything.modalprocessors import BaseModalProcessor, ContextExtractor
from raganything.prompt import PROMPTS

# Default model identifiers. Overridable via env so users can pin a version
# without code changes (TwelveLabs occasionally retires model aliases).
DEFAULT_PEGASUS_MODEL = os.getenv("TWELVELABS_PEGASUS_MODEL", "pegasus1.5")
DEFAULT_MARENGO_MODEL = os.getenv("TWELVELABS_MARENGO_MODEL", "marengo3.0")

# Register prompts the same way the other modalities do.
PROMPTS["VIDEO_ANALYSIS_SYSTEM"] = (
    "You are an expert video analyst. Describe video content accurately and in detail."
)
PROMPTS[
    "video_analysis_prompt"
] = """Watch this video and produce a detailed, factual description suitable for retrieval.
Cover, where present: the setting/scene, people and objects, on-screen text,
spoken content / narration, actions and events over time, and any notable
visual or audio details. Be specific and avoid pronouns where a name applies.

{context_block}Captions provided by the source document: {captions}
"""
PROMPTS["video_chunk"] = """Video Content Analysis
Source: {video_ref}
Captions: {captions}

Description (TwelveLabs Pegasus):
{description}
"""


class TwelveLabsModalProcessor(BaseModalProcessor):
    """Process video content via TwelveLabs Pegasus (analyze) + Marengo (embed).

    Args:
        lightrag: LightRAG instance (provides storage + KG machinery).
        modal_caption_func: Unused for video (description comes from Pegasus);
            accepted for interface compatibility with the other processors.
        context_extractor: Optional context extractor.
        api_key: TwelveLabs API key. Falls back to ``TWELVELABS_API_KEY`` env.
        pegasus_model: Pegasus model id for analysis.
        marengo_model: Marengo model id for embeddings.
    """

    def __init__(
        self,
        lightrag: LightRAG,
        modal_caption_func=None,
        context_extractor: ContextExtractor = None,
        api_key: Optional[str] = None,
        pegasus_model: str = DEFAULT_PEGASUS_MODEL,
        marengo_model: str = DEFAULT_MARENGO_MODEL,
    ):
        super().__init__(lightrag, modal_caption_func, context_extractor)

        try:
            from twelvelabs import TwelveLabs
        except ImportError as e:  # pragma: no cover - guarded at registration
            raise ImportError(
                "The 'twelvelabs' package is required for video processing. "
                "Install it with: pip install 'raganything[video]' "
                "(or: pip install twelvelabs)."
            ) from e

        self.api_key = api_key or os.getenv("TWELVELABS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "TwelveLabs API key not found. Set TWELVELABS_API_KEY or pass "
                "api_key=. Get a free key at https://twelvelabs.io."
            )

        self._client = TwelveLabs(api_key=self.api_key)
        self.pegasus_model = pegasus_model
        self.marengo_model = marengo_model

    # ── TwelveLabs API helpers ───────────────────────────────────────────

    @staticmethod
    def _resolve_video_ref(content_data: Dict[str, Any]) -> Tuple[str, str]:
        """Resolve the video reference from a modal item.

        Returns a ``(kind, value)`` tuple where kind is one of
        ``"url"``, ``"video_id"`` or ``"path"``.
        """
        if content_data.get("video_url"):
            return "url", content_data["video_url"]
        if content_data.get("video_id"):
            return "video_id", content_data["video_id"]
        if content_data.get("video_path"):
            return "path", content_data["video_path"]
        raise ValueError(
            "Video modal item must provide one of: video_url, video_id, video_path. "
            f"Got keys: {sorted(content_data.keys())}"
        )

    def _analyze_video(self, kind: str, value: str, prompt: str) -> str:
        """Call Pegasus to generate a description. Returns the description text."""
        from twelvelabs.types.video_context import (
            VideoContext_AssetId,
            VideoContext_Url,
        )

        kwargs: Dict[str, Any] = {
            "model_name": self.pegasus_model,
            "prompt": prompt,
            "max_tokens": 2048,
        }
        if kind == "video_id":
            kwargs["video_id"] = value
        elif kind == "url":
            kwargs["video"] = VideoContext_Url(url=value)
        else:  # path -> upload as asset, then analyze by asset id
            asset_id = self._upload_asset(value)
            kwargs["video"] = VideoContext_AssetId(asset_id=asset_id)

        response = self._client.analyze(**kwargs)
        return (response.data or "").strip()

    def _upload_asset(self, path: str) -> str:
        """Upload a local video file as a TwelveLabs asset; return its id."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Video file not found: {path}")
        with open(p, "rb") as f:
            asset = self._client.assets.create(method="direct", file=f)
        return asset.id

    def embed_video(
        self, kind: str, value: str, timeout_sec: int = 300, poll_interval_sec: int = 5
    ) -> Optional[List[float]]:
        """Compute a Marengo embedding for a video reference (best-effort).

        Video embedding is an asynchronous task: this submits the task and polls
        until it finishes or ``timeout_sec`` elapses. Returns a 512-dim vector
        (the first/video-scope segment), or None if embedding is unavailable for
        the given reference type (e.g. a bare ``video_id``) or did not complete
        in time. Never raises -- ingestion proceeds without the embedding.
        """
        import time

        try:
            if kind == "url":
                task = self._client.embed.tasks.create(
                    model_name=self.marengo_model,
                    video_url=value,
                    video_embedding_scope=["video"],
                )
            elif kind == "path":
                with open(value, "rb") as f:
                    task = self._client.embed.tasks.create(
                        model_name=self.marengo_model,
                        video_file=f,
                        video_embedding_scope=["video"],
                    )
            else:
                return None

            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                status = self._client.embed.tasks.status(task.id)
                if status.status == "ready":
                    break
                if status.status == "failed":
                    logger.warning(f"TwelveLabs embedding task {task.id} failed")
                    return None
                time.sleep(poll_interval_sec)
            else:
                logger.warning(
                    f"TwelveLabs embedding task {task.id} timed out after {timeout_sec}s"
                )
                return None

            result = self._client.embed.tasks.retrieve(task.id)
            segments = getattr(result.video_embedding, "segments", None)
            if segments:
                return list(segments[0].float_)
        except Exception as e:  # pragma: no cover - network/availability dependent
            logger.warning(f"TwelveLabs video embedding failed: {e}")
        return None

    def embed_text(self, text: str) -> List[float]:
        """Compute a Marengo embedding for a text query (512-dim).

        Useful at retrieval time to score a text query against stored video
        embeddings in the same multimodal space.
        """
        resp = self._client.embed.create(model_name=self.marengo_model, text=text)
        return list(resp.text_embedding.segments[0].float_)

    # ── Pipeline integration (mirrors GenericModalProcessor) ─────────────

    async def generate_description_only(
        self,
        modal_content,
        content_type: str,
        item_info: Dict[str, Any] = None,
        entity_name: str = None,
    ) -> Tuple[str, Dict[str, Any]]:
        try:
            content_data = _coerce_content(modal_content)
            kind, value = self._resolve_video_ref(content_data)
            captions = content_data.get(
                "video_caption", content_data.get("caption", [])
            )

            context = ""
            if item_info:
                context = self._get_context_for_item(item_info)
            context_block = (
                f"Surrounding document context:\n{context}\n\n" if context else ""
            )

            prompt = PROMPTS["video_analysis_prompt"].format(
                context_block=context_block,
                captions=", ".join(captions) if captions else "None",
            )

            description = self._analyze_video(kind, value, prompt)
            if not description:
                raise RuntimeError("Pegasus returned an empty description")

            name = entity_name or f"video_{compute_mdhash_id(value)}"
            entity_info = {
                "entity_name": name,
                "entity_type": "video",
                "summary": description[:100]
                + ("..." if len(description) > 100 else ""),
            }
            return description, entity_info

        except Exception as e:
            logger.error(f"Error generating video description: {e}")
            fallback_entity = {
                "entity_name": entity_name
                or f"video_{compute_mdhash_id(str(modal_content))}",
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
        """Process a video item: Pegasus description + Marengo embedding."""
        try:
            description, entity_info = await self.generate_description_only(
                modal_content, content_type, item_info, entity_name
            )

            content_data = _coerce_content(modal_content)
            kind, value = self._resolve_video_ref(content_data)
            captions = content_data.get(
                "video_caption", content_data.get("caption", [])
            )

            # Best-effort Marengo embedding, returned on entity_info for callers
            # that want to index it for semantic video retrieval (pair with
            # ``embed_text`` to score a text query in the same 512-dim space).
            # Never blocks ingestion -- None on timeout/unavailable refs.
            embedding = self.embed_video(kind, value)
            if embedding is not None:
                entity_info["tl_video_embedding"] = embedding

            modal_chunk = PROMPTS["video_chunk"].format(
                video_ref=value,
                captions=", ".join(captions) if captions else "None",
                description=description,
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
                or f"video_{compute_mdhash_id(str(modal_content))}",
                "entity_type": "video",
                "summary": f"Video content: {str(modal_content)[:100]}",
            }
            return str(modal_content), fallback_entity


def _coerce_content(modal_content) -> Dict[str, Any]:
    """Accept a dict or a JSON string and return a dict."""
    if isinstance(modal_content, str):
        try:
            return json.loads(modal_content)
        except json.JSONDecodeError:
            return {"video_url": modal_content}
    return modal_content
