"""
赛项知识图谱与能力标签体系。

功能：
- 赛题解析器：PDF/Word 赛题结构化提取
- 能力标签树：3+ 层级标签 CRUD
- 自动打标服务：语义分析推荐标签
- 知识图谱 API：节点/边 JSON 输出
"""

from .models import KnowledgeNode, KnowledgeEdge, CapabilityTag
from .parser import ExamParser
from .tagger import AutoTagger
from .graph_api import KnowledgeGraphAPI

__all__ = [
    "KnowledgeNode",
    "KnowledgeEdge",
    "CapabilityTag",
    "ExamParser",
    "AutoTagger",
    "KnowledgeGraphAPI",
]
