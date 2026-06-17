"""
通用引用解析模块 — 从 LLM 回答中提取结构化引用列表。

支持格式:
- 内联标记: [来源 N]
- 引用来源块: 【引用来源】\n[来源 1] 源文档：xxx | 原文："..."
- 英文变体: [Source N]

该模块从 manufacturing/agent/source_tracer.py 提炼而来，
为通用 RAG 管线提供统一的引用解析能力。
"""

import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 来源引用标记模式 — 匹配 [来源 N] 或 [来源N]
CITATION_PATTERN = re.compile(r"\[来源\s*(\d+)\]")

# 英文变体 [Source N]
CITATION_PATTERN_EN = re.compile(r"\[Source\s*(\d+)\]", re.IGNORECASE)

# 引用来源块标记
CITATION_BLOCK_HEADER = re.compile(r"【?引用来源】?")

# 引用来源块中的条目解析
# 格式: [来源 1] 源文档：xxx.pdf | 原文："..."
# 或:   [来源 1] 源文档: xxx.pdf | 原文: "..."
CITATION_ENTRY_PATTERN = re.compile(
    r"\[来源\s*(\d+)\]\s*"
    r"源文档[：:]\s*([^|]+?)\s*"
    r"\|\s*原文[：:]\s*['“‘](.+?)['”’]"
)

# Simplified entry pattern (without quotes)
CITATION_ENTRY_SIMPLE = re.compile(
    r"\[来源\s*(\d+)\]\s*"
    r"源文档[：:]\s*([^|]+?)\s*"
    r"\|\s*原文[：:]\s*(.+)"
)


def has_citations(text: str) -> bool:
    """检测文本中是否包含引用标记。

    Args:
        text: 待检测的文本

    Returns:
        True 如果文本包含 [来源 N] 或 [Source N] 标记
    """
    if not text:
        return False
    return bool(CITATION_PATTERN.search(text) or CITATION_PATTERN_EN.search(text))


def extract_citation_indices(text: str) -> List[int]:
    """提取文本中所有引用编号（去重排序）。

    Args:
        text: 包含 [来源 N] 标记的文本

    Returns:
        排序去重后的引用编号列表
    """
    indices = set()
    for m in CITATION_PATTERN.finditer(text):
        indices.add(int(m.group(1)))
    for m in CITATION_PATTERN_EN.finditer(text):
        indices.add(int(m.group(1)))
    return sorted(indices)


def parse_citation_block(text: str) -> List[Dict[str, any]]:
    """解析回答末尾的【引用来源】块，提取结构化引用条目。

    支持的格式:
        [来源 1] 源文档：xxx.pdf | 原文："被引用的原文内容..."
        [来源 2] 源文档：yyy.docx | 原文：被引用的原文内容...

    Args:
        text: 包含【引用来源】块的完整回答文本

    Returns:
        引用条目列表，每项包含:
        - index: int, 来源编号
        - document_name: str, 源文档名称
        - excerpt: str, 原文摘录
    """
    citations = []

    # Find the citation block
    block_match = CITATION_BLOCK_HEADER.search(text)
    if not block_match:
        return citations

    block_text = text[block_match.end():]

    # Try full format first (with quotes)
    for m in CITATION_ENTRY_PATTERN.finditer(block_text):
        citations.append({
            "index": int(m.group(1)),
            "document_name": m.group(2).strip(),
            "excerpt": m.group(3).strip(),
        })

    # If no full-format entries found, try simplified format
    if not citations:
        for m in CITATION_ENTRY_SIMPLE.finditer(block_text):
            excerpt = m.group(3).strip()
            # Strip trailing punctuation
            excerpt = re.sub(r'[\s,，。.!！?？;；]+$', '', excerpt)
            citations.append({
                "index": int(m.group(1)),
                "document_name": m.group(2).strip(),
                "excerpt": excerpt,
            })

    return citations


def extract_citations(
    answer: str,
    source_docs: Optional[List[Dict]] = None,
    chunk_texts: Optional[Dict[int, str]] = None,
) -> List[Dict]:
    """从 LLM 回答中提取结构化引用列表。

    解析策略（按优先级）：
    1. 优先解析【引用来源】块（LLM 主动提供的结构化引用）
    2. 提取内联 [来源 N] 标记，从 source_docs 或 chunk_texts 补充信息
    3. 如果以上都没有，返回提取到的索引编号

    Args:
        answer: LLM 生成的回答文本
        source_docs: 检索到的源文档列表（可选），用于补充引用信息
        chunk_texts: chunk序号 → chunk文本的映射（可选），用于自动提取摘录

    Returns:
        引用列表，每项包含:
        - index: int, 来源编号
        - document_name: str, 源文档名称
        - excerpt: str, 原文摘录
        - file_path: str | None, 源文件路径
    """
    if not answer:
        return []

    # Strategy 1: Parse citation block
    block_citations = parse_citation_block(answer)
    if block_citations:
        # Enrich with file_path from source_docs if available
        if source_docs:
            for cit in block_citations:
                idx = cit["index"] - 1
                if 0 <= idx < len(source_docs):
                    cit["file_path"] = source_docs[idx].get("file_path")
                else:
                    cit["file_path"] = None
        return block_citations

    # Strategy 2: Extract inline [来源 N] markers, build from source_docs
    indices = extract_citation_indices(answer)
    citations = []
    seen = set()

    for ref_idx in indices:
        if ref_idx in seen:
            continue
        seen.add(ref_idx)

        doc_idx = ref_idx - 1
        citation = {
            "index": ref_idx,
            "document_name": None,
            "excerpt": None,
            "file_path": None,
        }

        if source_docs and 0 <= doc_idx < len(source_docs):
            doc = source_docs[doc_idx]
            citation["document_name"] = doc.get(
                "document_name",
                doc.get("title", doc.get("source", f"来源 {ref_idx}")),
            )
            citation["file_path"] = doc.get("file_path")
            # Use chunk content as excerpt
            excerpt = doc.get("content", doc.get("text", ""))
            if excerpt:
                citation["excerpt"] = excerpt[:200]

        elif chunk_texts and ref_idx in chunk_texts:
            citation["excerpt"] = chunk_texts[ref_idx][:200]
            citation["document_name"] = f"来源 {ref_idx}"

        else:
            citation["document_name"] = f"来源 {ref_idx}"

        citations.append(citation)

    return citations


# Backward compatibility alias matching the manufacturing module's API
extract_citations_from_answer = extract_citations
