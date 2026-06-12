"""
资源溯源模块 — 为智能体回答附加来源元数据。

溯源维度:
- 来源文档名称
- 页码/段落号
- 入库时间
- 可靠度级别
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 来源引用模式
CITATION_PATTERN = re.compile(r"\[来源\s*(\d+)\]")


class SourceTracer:
    """回答溯源追踪器。"""

    def __init__(self):
        self._citation_cache: dict[str, list[dict]] = {}

    def extract_citations(self, answer: str,
                          source_docs: list[dict]) -> list[dict]:
        """从 LLM 回答中提取来源引用，并关联到检索文档。

        Args:
            answer: LLM 生成的回答文本
            source_docs: 检索到的源文档列表

        Returns:
            引用列表 [{"source_title", "page", "excerpt", "reliability", "url"}, ...]
        """
        citations = []

        # 查找 [来源 N] 引用标记
        refs = CITATION_PATTERN.findall(answer)
        seen = set()

        for ref in refs:
            idx = int(ref) - 1
            if idx < 0 or idx >= len(source_docs):
                continue

            doc = source_docs[idx]
            doc_id = doc.get("id", doc.get("title", str(idx)))

            if doc_id in seen:
                continue
            seen.add(doc_id)

            citation = {
                "source_title": doc.get("title", doc.get("source", f"来源 {ref}")),
                "page": doc.get("page", doc.get("page_number")),
                "section": doc.get("section", doc.get("section_title", "")),
                "excerpt": (doc.get("content", doc.get("text", "")) or "")[:200],
                "reliability": self._assess_reliability(doc),
                "url": doc.get("url", doc.get("file_path", "")),
                "ingested_at": doc.get("ingested_at", doc.get("created_at", "")),
            }
            citations.append(citation)

        return citations

    def trace_fact(self, statement: str,
                   knowledge_base: list[dict]) -> list[dict]:
        """追溯单个事实陈述的所有可能来源。

        Args:
            statement: 要追溯的事实陈述
            knowledge_base: 知识库文档列表

        Returns:
            匹配的来源列表 (可能有多个)
        """
        sources = []
        statement_lower = statement.lower()

        for doc in knowledge_base:
            content = doc.get("content", doc.get("text", ""))
            if not content:
                continue

            # 简单的关键词共现检测
            words = set(statement_lower.split())
            content_lower = content.lower()
            matches = sum(1 for w in words if w in content_lower)

            if matches >= len(words) * 0.5:  # 至少 50% 关键词命中
                sources.append({
                    "source_title": doc.get("title", ""),
                    "page": doc.get("page"),
                    "match_score": matches / len(words),
                    "excerpt": content[:300],
                    "reliability": self._assess_reliability(doc),
                })

        sources.sort(key=lambda x: x["match_score"], reverse=True)
        return sources

    def verify_citations(self, answer: str,
                         citations: list[dict]) -> dict:
        """验证引用信息的完整性。

        Returns:
            {"valid": bool, "issues": list[str], "completeness": float}
        """
        issues = []

        for i, cit in enumerate(citations):
            if not cit.get("source_title"):
                issues.append(f"引用 {i+1} 缺少来源标题")
            if not cit.get("excerpt"):
                issues.append(f"引用 {i+1} 缺少摘录内容")

        completeness = (
            len([c for c in citations if c.get("source_title") and c.get("excerpt")])
            / len(citations) if citations else 1.0
        )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "completeness": round(completeness, 2),
            "total_citations": len(citations),
        }

    def _assess_reliability(self, doc: dict) -> str:
        """评估文档可靠度级别。"""
        # 根据元数据判断可靠度
        copyright_status = doc.get("copyright_status", "")
        quality_score = doc.get("quality_score", 0)

        if copyright_status == "authorized" and quality_score >= 80:
            return "high"
        elif quality_score >= 60:
            return "medium"
        else:
            return "low"
