"""
自动打标服务 — 基于文本语义分析为新资源推荐能力标签。

流程:
1. 对资源内容进行向量化
2. 计算与已有标签的语义相似度
3. 返回 Top 3-5 推荐标签
"""

import logging
from typing import Optional

from .models import CapabilityTag, TagTree

logger = logging.getLogger(__name__)


class AutoTagger:
    """自动标签推荐器。

    为知识库中的新资源自动推荐最相关的能力标签。
    """

    def __init__(self, tag_tree: TagTree,
                 embedding_client=None,
                 similarity_threshold: float = 0.6):
        """初始化打标器。

        Args:
            tag_tree: 能力标签树
            embedding_client: 向量化客户端 (用于语义相似度计算)
            similarity_threshold: 相似度阈值，低于此值不推荐
        """
        self.tag_tree = tag_tree
        self.embedding_client = embedding_client
        self.similarity_threshold = similarity_threshold

    def recommend_tags(self, content: str,
                       top_k: int = 5) -> list[dict]:
        """为给定内容推荐最匹配的能力标签。

        Args:
            content: 资源文本内容
            top_k: 返回的推荐标签数量

        Returns:
            [{"tag_id": str, "tag_name": str, "score": float}, ...]
        """
        recommendations = []

        if self.embedding_client:
            recommendations = self._semantic_recommend(content, top_k)
        else:
            recommendations = self._keyword_recommend(content, top_k)

        # 过滤低于阈值的推荐
        recommendations = [
            r for r in recommendations
            if r["score"] >= self.similarity_threshold
        ]

        return recommendations[:top_k]

    def batch_recommend(self, content_list: list[dict]) -> list[dict]:
        """批量为多个资源推荐标签。

        Args:
            content_list: [{"id": str, "content": str}, ...]

        Returns:
            [{"id": str, "tags": [...], "content": str}, ...]
        """
        results = []
        for item in content_list:
            tags = self.recommend_tags(item["content"])
            results.append({
                "id": item["id"],
                "tags": tags,
                "content": item["content"],
            })
        return results

    def confirm_tags(self, resource_id: str,
                     selected_tag_ids: list[str]) -> bool:
        """人工确认推荐的标签。

        Args:
            resource_id: 资源 ID
            selected_tag_ids: 用户选择的标签 ID 列表

        Returns:
            是否成功
        """
        # 验证所有标签 ID 存在
        for tag_id in selected_tag_ids:
            if not self.tag_tree.get_tag(tag_id):
                logger.warning(f"标签 {tag_id} 不存在")
                return False
        logger.info(f"资源 {resource_id} 确认标签: {selected_tag_ids}")
        return True

    # --- 私有方法 ---

    def _semantic_recommend(self, content: str, top_k: int) -> list[dict]:
        """基于向量语义相似度推荐标签。"""
        try:
            # 获取内容向量
            content_vec = self.embedding_client.embed(content)

            recommendations = []
            all_tags = self.tag_tree.get_all_tags()

            for tag in all_tags:
                # 构建标签的描述文本
                tag_text = f"{tag.name} {tag.description} {' '.join(tag.keywords)}"
                tag_vec = self.embedding_client.embed(tag_text)

                # 余弦相似度
                score = self._cosine_similarity(content_vec, tag_vec)

                if score >= self.similarity_threshold:
                    recommendations.append({
                        "tag_id": tag.id,
                        "tag_name": tag.name,
                        "score": round(score, 4),
                        "category": tag.category,
                        "level": tag.level,
                    })

            recommendations.sort(key=lambda x: x["score"], reverse=True)
            return recommendations[:top_k]

        except Exception as e:
            logger.warning(f"语义推荐失败，降级到关键词方案: {e}")
            return self._keyword_recommend(content, top_k)

    def _keyword_recommend(self, content: str, top_k: int) -> list[dict]:
        """基于关键词匹配的降级推荐方案。"""
        content_lower = content.lower()
        recommendations = []
        all_tags = self.tag_tree.get_all_tags()

        for tag in all_tags:
            # 计算关键词命中率
            if not tag.keywords:
                continue

            hits = sum(
                1 for kw in tag.keywords
                if kw.lower() in content_lower
            )
            if hits > 0:
                score = min(hits / len(tag.keywords), 1.0)
                recommendations.append({
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                    "score": round(score, 4),
                    "category": tag.category,
                    "level": tag.level,
                })

        recommendations.sort(key=lambda x: x["score"], reverse=True)
        return recommendations[:top_k]

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """计算余弦相似度。"""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a ** 2 for a in vec_a) ** 0.5
        norm_b = sum(b ** 2 for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
