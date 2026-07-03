"""
视频片段定位 — 集成视频帧时间戳索引，查询时返回匹配片段的起止时间。

依赖 RAG-Anything 已有的视频帧提取能力 (video-frame-extraction spec)。
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class VideoLocator:
    """视频片段定位器。"""

    def __init__(self, frame_index=None, embedding_client=None,
                 frame_window: int = 3, min_segment_duration: float = 5.0):
        """
        Args:
            frame_index: 视频帧索引存储 (含时间戳)
            embedding_client: 向量化客户端
            frame_window: 匹配帧的前后窗口大小
            min_segment_duration: 返回片段的最小时长 (秒)
        """
        self.frame_index = frame_index or {}
        self.embedding_client = embedding_client
        self.frame_window = frame_window
        self.min_segment_duration = min_segment_duration
        self._embed_adapter = self._resolve_embed_adapter(embedding_client)

    @staticmethod
    def _resolve_embed_adapter(client) -> Optional[Callable]:
        """解析 Embedding 客户端接口，返回统一的 `embed(text) -> list[float]` 可调用对象。"""
        if client is None:
            return None
        # OpenAI SDK: client.embeddings.create(...)
        if hasattr(client, 'embeddings') and hasattr(client.embeddings, 'create'):
            def adapter(text: str) -> list[float]:
                resp = client.embeddings.create(
                    input=text,
                    model=getattr(client, 'embedding_model', 'text-embedding-3-small'),
                )
                return resp.data[0].embedding
            return adapter
        # SentenceTransformers / HuggingFace: model.encode(...)
        if hasattr(client, 'encode'):
            def adapter(text: str) -> list[float]:
                import numpy as np
                vec = client.encode(text, convert_to_numpy=True)
                return vec.tolist() if isinstance(vec, np.ndarray) else list(vec)
            return adapter
        # Generic: has embed method
        if hasattr(client, 'embed') and callable(client.embed):
            def adapter(text: str) -> list[float]:
                return list(client.embed(text))
            return adapter
        # Generic: callable itself
        if callable(client):
            def adapter(text: str) -> list[float]:
                return list(client(text))
            return adapter
        raise TypeError(
            f"embedding_client 类型 {type(client)} 不支持。"
            "请传入 OpenAI SDK、SentenceTransformer、或实现了 embed(text) -> list[float] 的对象"
        )

    def locate(self, query: str, video_filter: Optional[str] = None,
               top_k: int = 5) -> list[dict]:
        """根据查询定位相关视频片段。

        Args:
            query: 用户查询（如"如何对刀"）
            video_filter: 限定视频名称 (可选)
            top_k: 返回片段数量

        Returns:
            [{"video_name", "start_ts", "end_ts", "start_frame",
              "end_frame", "score", "keyframe_preview"}, ...]
        """
        # Step 1: 匹配最相关的帧
        matched_frames = self._match_frames(query, video_filter)

        # Step 2: 将帧扩展为片段
        segments = self._frames_to_segments(matched_frames)

        # Step 3: 合并相邻片段，去重
        merged = self._merge_overlapping_segments(segments)

        return merged[:top_k]

    def get_video_info(self, video_name: str) -> Optional[dict]:
        """获取视频的基本信息。"""
        for vid, info in self.frame_index.items():
            if info.get("name") == video_name or vid == video_name:
                return {
                    "name": info.get("name", video_name),
                    "duration": info.get("duration", 0),
                    "fps": info.get("fps", 0),
                    "total_frames": info.get("total_frames", 0),
                    "resolution": info.get("resolution", ""),
                }
        return None

    def list_videos(self) -> list[dict]:
        """列出索引中的所有视频。"""
        return [
            {"id": vid, "name": info.get("name", vid),
             "duration": info.get("duration", 0)}
            for vid, info in self.frame_index.items()
        ]

    def _match_frames(self, query: str,
                      video_filter: Optional[str] = None) -> list[dict]:
        """向量匹配最相关的帧。"""
        if not self._embed_adapter:
            return []

        try:
            query_vec = self._embed_adapter(query)
            scored_frames = []

            for video_id, video_info in self.frame_index.items():
                if video_filter and video_info.get("name") != video_filter:
                    continue

                frames = video_info.get("frames", [])
                for frame in frames:
                    if "embedding" in frame:
                        score = self._cosine(query_vec, frame["embedding"])
                        if score > 0.5:
                            scored_frames.append({
                                "video_name": video_info.get("name", video_id),
                                "video_id": video_id,
                                "frame_number": frame.get("frame_number", 0),
                                "timestamp": frame.get("timestamp", 0.0),
                                "score": score,
                            })

            scored_frames.sort(key=lambda x: x["score"], reverse=True)
            return scored_frames
        except Exception as e:
            logger.error(f"帧匹配失败: {e}")
            return []

    def _frames_to_segments(self, frames: list[dict]) -> list[dict]:
        """将匹配帧扩展为时间片段。"""
        segments = []
        for frame in frames:
            video_info = self.frame_index.get(frame["video_id"], {})
            fps = video_info.get("fps", 30)
            frame_duration = 1.0 / fps if fps > 0 else 0.033

            start_frame = max(0, frame["frame_number"] - self.frame_window)
            end_frame = frame["frame_number"] + self.frame_window
            start_ts = max(0, frame["timestamp"] - self.frame_window * frame_duration)
            end_ts = frame["timestamp"] + self.frame_window * frame_duration

            # 确保满足最小时长
            if end_ts - start_ts < self.min_segment_duration:
                padding = (self.min_segment_duration - (end_ts - start_ts)) / 2
                start_ts = max(0, start_ts - padding)
                end_ts = min(
                    video_info.get("duration", float("inf")),
                    end_ts + padding,
                )

            segments.append({
                "video_name": frame["video_name"],
                "start_ts": round(start_ts, 2),
                "end_ts": round(end_ts, 2),
                "start_frame": start_frame,
                "end_frame": end_frame,
                "score": round(frame["score"], 4),
                "matched_frame": frame["frame_number"],
                "matched_ts": frame["timestamp"],
            })

        return segments

    def _merge_overlapping_segments(self, segments: list[dict]) -> list[dict]:
        """合并重叠的相邻片段。"""
        if not segments:
            return []

        # 按 score 降序排列
        segments.sort(key=lambda x: x["score"], reverse=True)

        merged = []
        for seg in segments:
            # 检查是否与已有片段重叠
            overlap = False
            for m in merged:
                if (seg["video_name"] == m["video_name"] and
                        seg["start_ts"] <= m["end_ts"] and
                        seg["end_ts"] >= m["start_ts"]):
                    # 合并：扩展区间
                    m["start_ts"] = min(m["start_ts"], seg["start_ts"])
                    m["end_ts"] = max(m["end_ts"], seg["end_ts"])
                    m["score"] = max(m["score"], seg["score"])
                    overlap = True
                    break

            if not overlap:
                merged.append(seg)

        merged.sort(key=lambda x: x["score"], reverse=True)
        return merged

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x ** 2 for x in a) ** 0.5
        nb = sum(y ** 2 for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
