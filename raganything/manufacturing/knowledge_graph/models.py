"""
领域数据模型：知识图谱节点/边、能力标签、资源元数据。

使用 dataclass 定义核心领域实体，保持与 RAG-Anything 原有数据模型的兼容性。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ============================================================================
# 枚举类型
# ============================================================================

class RelationType(str, Enum):
    """知识图谱关系类型。"""
    REQUIRES = "requires"          # 前置依赖
    ADVANCES_TO = "advances_to"    # 后续进阶
    RELATED_TO = "related_to"      # 关联知识
    EVALUATES = "evaluates"        # 评分关联
    APPLIES_IN = "applies_in"      # 应用场景


class ModalityType(str, Enum):
    """资源模态类型。"""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    CODE = "code"
    DOCUMENT = "document"
    CAD_MODEL = "cad_model"


class CopyrightStatus(str, Enum):
    """版权审核状态。"""
    PENDING = "pending"        # 待确认
    IN_REVIEW = "in_review"    # 审核中
    AUTHORIZED = "authorized"  # 已授权
    REJECTED = "rejected"      # 已拒绝


class ConfidenceLevel(str, Enum):
    """置信度级别。"""
    HIGH = "high"        # ≥ 80%
    MEDIUM = "medium"    # 60-80%
    LOW = "low"          # < 60%


# ============================================================================
# 知识图谱数据模型
# ============================================================================

@dataclass
class KnowledgeNode:
    """知识图谱节点 — 表示一个知识点/概念/技能。"""
    id: str
    name: str
    description: str
    node_type: str  # "competition_topic", "skill_point", "knowledge_point", "tool", "standard"
    competition_track: Optional[str] = None  # 所属赛项 track ID
    difficulty_level: int = 1  # 难度等级 1-5
    estimated_hours: float = 0.0  # 建议学习时长
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class KnowledgeEdge:
    """知识图谱边 — 表示节点间的关系。"""
    id: str
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = 1.0  # 关系强度 (0.0 - 1.0)
    description: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


# ============================================================================
# 能力标签数据模型
# ============================================================================

@dataclass
class CapabilityTag:
    """能力标签 — 表示一项具体的技能或能力。"""
    id: str
    name: str
    parent_id: Optional[str] = None  # 父标签 ID（支持层级结构）
    level: int = 1  # 标签层级深度
    category: str = ""  # 所属根类别
    description: str = ""
    keywords: list[str] = field(default_factory=list)  # 关联关键词
    children: list["CapabilityTag"] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def is_root(self) -> bool:
        return self.parent_id is None

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def get_path(self) -> list[str]:
        """获取从根到当前节点的标签路径。"""
        return []  # 实际路径需在 TagTree 上下文中计算


@dataclass
class TagTree:
    """能力标签树 — 管理标签的层级结构。"""
    roots: list[CapabilityTag] = field(default_factory=list)
    _tag_index: dict[str, CapabilityTag] = field(default_factory=dict)

    def add_tag(self, tag: CapabilityTag) -> None:
        """添加标签到树中。"""
        self._tag_index[tag.id] = tag
        if tag.is_root():
            self.roots.append(tag)
        elif tag.parent_id and tag.parent_id in self._tag_index:
            parent = self._tag_index[tag.parent_id]
            parent.children.append(tag)

    def get_tag(self, tag_id: str) -> Optional[CapabilityTag]:
        """按 ID 获取标签。"""
        return self._tag_index.get(tag_id)

    def get_all_tags(self) -> list[CapabilityTag]:
        """获取所有标签（扁平列表）。"""
        return list(self._tag_index.values())

    def get_descendants(self, tag_id: str) -> list[CapabilityTag]:
        """获取某标签的所有后代。"""
        tag = self._tag_index.get(tag_id)
        if not tag:
            return []
        result = list(tag.children)
        for child in tag.children:
            result.extend(self.get_descendants(child.id))
        return result

    def remove_tag(self, tag_id: str) -> bool:
        """删除标签（连同子树）。"""
        tag = self._tag_index.pop(tag_id, None)
        if not tag:
            return False
        if tag.parent_id and tag.parent_id in self._tag_index:
            parent = self._tag_index[tag.parent_id]
            parent.children = [c for c in parent.children if c.id != tag_id]
        self.roots = [r for r in self.roots if r.id != tag_id]
        for child in list(tag.children):
            self.remove_tag(child.id)
        return True


# ============================================================================
# 资源元数据模型
# ============================================================================

@dataclass
class ResourceMetadata:
    """多模态资源元数据。"""
    id: str
    title: str
    modality: ModalityType
    file_path: str
    file_size_bytes: int = 0
    mime_type: str = ""

    # 标注信息
    tags: list[str] = field(default_factory=list)  # 能力标签 ID 列表
    graph_node_ids: list[str] = field(default_factory=list)  # 关联知识图谱节点

    # 版权信息
    copyright_status: CopyrightStatus = CopyrightStatus.PENDING
    copyright_owner: str = ""
    license_info: str = ""
    authorized_scope: str = ""  # 授权使用范围

    # 溯源信息
    source_document: str = ""  # 原始文档名称
    page_number: Optional[int] = None
    section_title: str = ""

    # 质量控制
    quality_score: float = 0.0  # 数据质量评分 (0-100)
    reviewer_id: str = ""
    review_notes: str = ""

    # 时间戳
    ingested_at: datetime = field(default_factory=datetime.now)
    reviewed_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.now)


# ============================================================================
# 赛题数据模型
# ============================================================================

@dataclass
class ExamQuestion:
    """结构化赛题。"""
    id: str
    competition_track: str
    question_number: str
    question_type: str  # "single_choice", "multiple_choice", "practical", "essay"
    content: str
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""

    # 关联信息
    skill_requirements: list[str] = field(default_factory=list)  # 技能要求列表
    scoring_criteria: list["ScoringRule"] = field(default_factory=list)
    difficulty: int = 1
    estimated_time_minutes: int = 10

    # 知识图谱
    knowledge_node_ids: list[str] = field(default_factory=list)
    capability_tag_ids: list[str] = field(default_factory=list)


@dataclass
class ScoringRule:
    """评分规则。"""
    id: str
    description: str  # 评分项描述
    max_score: float
    weight: float = 1.0  # 权重系数
    criteria: str = ""  # 判定条件
    deduction_rules: list[str] = field(default_factory=list)  # 扣分规则


# ============================================================================
# 故障案例数据模型
# ============================================================================

@dataclass
class FaultCase:
    """故障案例。"""
    id: str
    title: str
    equipment_type: str  # 设备类型
    fault_category: str  # 故障类别（机械/电气/控制/软件）
    phenomenon: str  # 故障现象
    root_cause: str  # 根本原因
    troubleshooting_steps: list[str] = field(default_factory=list)  # 排除步骤
    preventive_measures: list[str] = field(default_factory=list)  # 预防措施
    related_tags: list[str] = field(default_factory=list)  # 关联标签
    severity: str = "medium"  # 严重程度: low/medium/high/critical
    occurrence_count: int = 0  # 发生次数
    created_at: datetime = field(default_factory=datetime.now)


# ============================================================================
# 诊断结果数据模型
# ============================================================================

@dataclass
class DiagnosisResult:
    """故障诊断结果。"""
    possible_causes: list[dict] = field(default_factory=list)
    # 每个 cause: {"description": str, "confidence": float, "matched_cases": int}
    recommended_actions: list[str] = field(default_factory=list)
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    needs_human_review: bool = False
    dialog_context: list[dict] = field(default_factory=list)  # 多轮对话上下文


# ============================================================================
# 智能体回答数据模型
# ============================================================================

@dataclass
class AgentResponse:
    """智能体回答。"""
    query: str
    answer: str
    citations: list[dict] = field(default_factory=list)
    # 每个 citation: {"source_title": str, "page": int, "excerpt": str, "url": str}
    related_video_segments: list[dict] = field(default_factory=list)
    # 每个 segment: {"video_name": str, "start_ts": float, "end_ts": float, "score": float}
    related_images: list[dict] = field(default_factory=list)
    # 每个 image: {"data_url": str, "caption": str, "page": int, "relevance": float}
    lineage_tree: Optional[dict] = None  # 知识谱系树
    trace: list = field(default_factory=list)
    # 推理轨迹: [{"step": int, "thought": str, "action": str, "observation": str, "elapsed_ms": float}, ...]
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    needs_human_review: bool = False
