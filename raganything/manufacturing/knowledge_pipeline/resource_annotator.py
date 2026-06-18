"""
多模态资源标注引擎 — 自动识别模态类型，统一标注接口。

标注维度:
- 模态类型 (text/image/video/code/document/cad_model)
- 能力标签 (关联 CapabilityTag)
- 知识图谱节点 (关联 KnowledgeNode)
- 版权状态 (CopyrightStatus)
"""

import logging
from pathlib import Path
from datetime import datetime

from ..knowledge_graph.models import (
    ResourceMetadata, ModalityType, CopyrightStatus,
)

logger = logging.getLogger(__name__)

# 文件扩展名 → 模态类型映射
EXT_TO_MODALITY = {
    # Text
    ".txt": ModalityType.TEXT, ".md": ModalityType.TEXT,
    ".pdf": ModalityType.DOCUMENT,
    ".doc": ModalityType.DOCUMENT, ".docx": ModalityType.DOCUMENT,
    # Image
    ".png": ModalityType.IMAGE, ".jpg": ModalityType.IMAGE,
    ".jpeg": ModalityType.IMAGE, ".bmp": ModalityType.IMAGE,
    ".gif": ModalityType.IMAGE,
    # Video
    ".mp4": ModalityType.VIDEO, ".avi": ModalityType.VIDEO,
    ".mov": ModalityType.VIDEO, ".mkv": ModalityType.VIDEO,
    # Code
    ".py": ModalityType.CODE, ".cpp": ModalityType.CODE,
    ".c": ModalityType.CODE, ".gcode": ModalityType.CODE,
    ".nc": ModalityType.CODE, ".stl": ModalityType.CAD_MODEL,
    # CAD
    ".step": ModalityType.CAD_MODEL, ".stp": ModalityType.CAD_MODEL,
    ".igs": ModalityType.CAD_MODEL, ".dwg": ModalityType.CAD_MODEL,
}


class ResourceAnnotator:
    """多模态资源统一标注引擎。"""

    def __init__(self, tagger=None, graph_api=None):
        self.tagger = tagger
        self.graph_api = graph_api

    def annotate(self, file_path: str | Path,
                 copyright_owner: str = "",
                 license_info: str = "") -> ResourceMetadata:
        """标注单个资源文件。

        Args:
            file_path: 资源文件路径
            copyright_owner: 版权归属
            license_info: 授权信息

        Returns:
            ResourceMetadata with auto-detected fields
        """
        file_path = Path(file_path)
        modality = self._detect_modality(file_path)

        metadata = ResourceMetadata(
            id=f"res_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_path.stem}",
            title=file_path.stem,
            modality=modality,
            file_path=str(file_path.absolute()),
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            mime_type=self._guess_mime(file_path),
            copyright_status=CopyrightStatus.PENDING,
            copyright_owner=copyright_owner,
            license_info=license_info,
        )

        # 自动打标
        if self.tagger and modality in (ModalityType.TEXT, ModalityType.DOCUMENT):
            try:
                content = file_path.read_text(encoding="utf-8")[:4000]
                tags = self.tagger.recommend_tags(content, top_k=5)
                metadata.tags = [t["tag_id"] for t in tags]
            except Exception as e:
                logger.warning(f"自动打标失败: {e}")

        return metadata

    def batch_annotate(self, file_paths: list[str | Path],
                       copyright_owner: str = "",
                       license_info: str = "") -> list[ResourceMetadata]:
        """批量标注资源文件。"""
        results = []
        for fp in file_paths:
            try:
                metadata = self.annotate(fp, copyright_owner, license_info)
                results.append(metadata)
            except Exception as e:
                logger.error(f"标注失败 {fp}: {e}")
        return results

    def get_annotations_summary(self, annotations: list[ResourceMetadata]) -> dict:
        """生成标注汇总统计。"""
        modality_counts: dict[str, int] = {}
        copyright_counts: dict[str, int] = {}

        for a in annotations:
            mod = a.modality.value if hasattr(a.modality, "value") else str(a.modality)
            modality_counts[mod] = modality_counts.get(mod, 0) + 1
            cs = a.copyright_status.value if hasattr(a.copyright_status, "value") else str(a.copyright_status)
            copyright_counts[cs] = copyright_counts.get(cs, 0) + 1

        return {
            "total_resources": len(annotations),
            "modality_distribution": modality_counts,
            "copyright_status_distribution": copyright_counts,
            "tagged_count": sum(1 for a in annotations if a.tags),
        }

    @staticmethod
    def _detect_modality(file_path: Path) -> ModalityType:
        suffix = file_path.suffix.lower()
        return EXT_TO_MODALITY.get(suffix, ModalityType.TEXT)

    @staticmethod
    def _guess_mime(file_path: Path) -> str:
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain", ".md": "text/markdown",
            ".png": "image/png", ".jpg": "image/jpeg",
            ".mp4": "video/mp4",
            ".py": "text/x-python", ".gcode": "text/x-gcode",
        }
        return mime_map.get(file_path.suffix.lower(), "application/octet-stream")
