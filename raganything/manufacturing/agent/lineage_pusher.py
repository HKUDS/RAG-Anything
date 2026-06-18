"""
知识谱系关联推送 — 查询时自动计算前置知识和后续进阶路径。
"""

import logging
from typing import Optional

from ..knowledge_graph.graph_api import KnowledgeGraphAPI

logger = logging.getLogger(__name__)


class LineagePusher:
    """知识谱系推送引擎。"""

    def __init__(self, graph_api: Optional[KnowledgeGraphAPI] = None):
        self.graph_api = graph_api or KnowledgeGraphAPI()

    def get_lineage_for_query(self, query_node_ids: list[str],
                              upstream_depth: int = 2,
                              downstream_depth: int = 2) -> dict:
        """为查询涉及的知识节点获取完整谱系。

        Args:
            query_node_ids: 查询涉及的知识节点 ID 列表
            upstream_depth: 前置追溯深度
            downstream_depth: 后续追溯深度

        Returns:
            {"nodes": [...], "tree": {...}, "learning_path": [...]}
        """
        all_lineages = []
        all_nodes = set()

        for node_id in query_node_ids:
            lineage = self.graph_api.get_lineage(
                node_id, upstream_depth, downstream_depth
            )
            if lineage:
                all_lineages.append(lineage)
                all_nodes.add(node_id)
                for prereq in lineage["prerequisites"]:
                    all_nodes.add(prereq["id"])
                for adv in lineage["advancements"]:
                    all_nodes.add(adv["id"])

        return {
            "nodes": list(all_nodes),
            "lineages": all_lineages,
            "learning_path": self._build_learning_path(all_lineages),
        }

    def get_prerequisites(self, node_id: str) -> dict:
        """获取前置知识（你应该先学什么）。

        Returns:
            {"node": dict, "prerequisites": [...], "ready_to_learn": bool}
        """
        lineage = self.graph_api.get_lineage(node_id, upstream_depth=3, downstream_depth=0)
        if not lineage:
            return {"node": {}, "prerequisites": [], "ready_to_learn": True}

        return {
            "node": lineage["node"],
            "prerequisites": lineage["prerequisites"],
            "prerequisite_count": lineage["prerequisite_count"],
            "ready_to_learn": lineage["prerequisite_count"] == 0,
        }

    def get_advancements(self, node_id: str) -> dict:
        """获取后续进阶（接下来可以学什么）。

        Returns:
            {"node": dict, "advancements": [...], "next_steps": [...]}
        """
        lineage = self.graph_api.get_lineage(node_id, upstream_depth=0, downstream_depth=3)
        if not lineage:
            return {"node": {}, "advancements": [], "next_steps": []}

        # 按难度排序推荐下一步
        next_steps = sorted(
            lineage["advancements"],
            key=lambda x: x.get("difficulty_level", 1),
        )

        return {
            "node": lineage["node"],
            "advancements": lineage["advancements"],
            "advancement_count": lineage["advancement_count"],
            "next_steps": next_steps[:3],
        }

    def build_skill_roadmap(self, root_tag_id: str) -> dict:
        """基于能力标签构建学习路线图。

        Args:
            root_tag_id: 根能力标签 ID

        Returns:
            从根标签开始的完整学习树
        """
        tag = self.graph_api.tag_tree.get_tag(root_tag_id)
        if not tag:
            return {"error": f"标签 {root_tag_id} 不存在"}

        return {
            "root": self._tag_to_tree(tag),
            "total_skills": len(self.graph_api.tag_tree.get_descendants(root_tag_id)) + 1,
            "max_depth": self._get_max_depth(tag),
        }

    def _build_learning_path(self, lineages: list[dict]) -> list[dict]:
        """从多节点谱系中构建综合学习路径。"""
        all_prereqs = []
        all_targets = []
        all_advs = []

        for lin in lineages:
            all_prereqs.extend(lin.get("prerequisites", []))
            all_targets.append(lin.get("node", {}))
            all_advs.extend(lin.get("advancements", []))

        return [
            {"phase": "prerequisites", "label": "前置知识", "nodes": all_prereqs},
            {"phase": "current", "label": "当前知识点", "nodes": all_targets},
            {"phase": "advancements", "label": "后续进阶", "nodes": all_advs},
        ]

    def _tag_to_tree(self, tag) -> dict:
        return {
            "id": tag.id,
            "name": tag.name,
            "level": tag.level,
            "children": [self._tag_to_tree(c) for c in tag.children],
        }

    def _get_max_depth(self, tag) -> int:
        if not tag.children:
            return tag.level
        return max(self._get_max_depth(c) for c in tag.children)
