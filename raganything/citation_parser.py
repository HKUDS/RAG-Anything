"""
通用引用解析模块 — 从 LLM 回答中提取结构化引用列表。

支持格式:
- 内联标记: [来源 文档名]
- 引用来源块: 📚 参考来源\n[来源 文档名] — "原文摘录..."
- 旧格式兼容: [来源 N]

该模块从 autorepair/agent/source_tracer.py 提炼而来，
为通用 RAG 管线提供统一的引用解析能力。
"""

import re
import logging
from typing import List, Dict, Optional

from raganything.utils import display_document_name

logger = logging.getLogger(__name__)

# 来源引用标记模式 — 匹配 [来源 文档名]（文档名引用）或 [来源 N]（数字兼容）
CITATION_PATTERN = re.compile(r"\[来源\s*([^\]]+?)\]")

# 英文变体 [Source N]
CITATION_PATTERN_EN = re.compile(r"\[Source\s*(\d+)\]", re.IGNORECASE)

# 引用来源块标记 — 兼容新旧两种格式
CITATION_BLOCK_HEADER = re.compile(r"(?:【?引用来源】?|📚\s*参考来源)")

# 引用来源块中的条目解析
# 旧格式: [来源 1] 源文档：xxx.pdf | 原文："..."
# 或:     [来源 1] 源文档: xxx.pdf | 原文: "..."
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

# New v5 format: [来源 文档名] — "原文摘录..."
CITATION_ENTRY_V5 = re.compile(
    r"\[来源\s*([^\]]+?)\]\s*[—\-]\s*['\"“](.+?)['\"”]"
)

# ── Entity relation citation patterns ──────────────────────────

# Entity relation block header: 【关联实体】 or 关联实体
ENTITY_RELATION_BLOCK_HEADER = re.compile(r"【?关联实体】?")

# Entity relation line with type annotations (old format):
#   - 实体A（类型A）→[关系]→ 实体B（类型B）
ENTITY_RELATION_PATTERN = re.compile(
    r"[-•]\s*"
    r"(.+?)（(.+?)）\s*"
    r"([→←])\s*\[(.+?)\]\s*[→←]\s*"
    r"(.+?)（(.+?)）"
)

# Entity relation line without type annotations (old format):
#   - 实体A →[关系]→ 实体B
ENTITY_RELATION_SIMPLE = re.compile(
    r"[-•]\s*"
    r"(.+?)\s*"
    r"([→←])\s*\[(.+?)\]\s*[→←]\s*"
    r"(.+)"
)

# New v4 clean entity relation format:
#   - 实体A → 实体B（关系类型）
#   - 实体A — 实体B（关系类型）
ENTITY_RELATION_CLEAN = re.compile(
    r"[-•]\s*"
    r"(.+?)\s*"
    r"[→—\-]\s*"
    r"(.+?)"
    r"(?:\s*[（(]\s*(.+?)\s*[）)])?\s*$",
    re.MULTILINE,
)


def has_citations(text: str) -> bool:
    """检测文本中是否包含引用标记。

    Args:
        text: 待检测的文本

    Returns:
        True 如果文本包含 [来源 N]、[Source N] 标记或 📚 参考来源 块
    """
    if not text:
        return False
    return bool(
        CITATION_PATTERN.search(text)
        or CITATION_PATTERN_EN.search(text)
        or CITATION_BLOCK_HEADER.search(text)
    )


def extract_citation_names(text: str) -> List[str]:
    """提取文本中所有引用来源名称（去重排序）。

    支持两种格式：
    - [来源 文档名] — 返回文档名
    - [来源 N] — 返回数字字符串（旧格式兼容）

    Args:
        text: 包含 [来源 xxx] 标记的文本

    Returns:
        排序去重后的引用来源名称列表
    """
    names = set()
    for m in CITATION_PATTERN.finditer(text):
        name = display_document_name(m.group(1).strip())
        if name:
            names.add(name)
    for m in CITATION_PATTERN_EN.finditer(text):
        names.add(f"Source-{m.group(1)}")
    return sorted(names)


# Backward-compatible alias
def extract_citation_indices(text: str) -> List[int]:
    """提取文本中所有数字引用编号（旧格式兼容）。

    Args:
        text: 包含 [来源 N] 标记的文本（N 为数字）

    Returns:
        排序去重后的引用编号列表
    """
    indices = set()
    for m in CITATION_PATTERN.finditer(text):
        name = display_document_name(m.group(1).strip())
        if name.isdigit():
            indices.add(int(name))
    for m in CITATION_PATTERN_EN.finditer(text):
        indices.add(int(m.group(1)))
    return sorted(indices)


def parse_entity_relations(text: str) -> List[Dict[str, any]]:
    """Parse the 【关联实体】 block from LLM answers to extract entity relations.

    Supports formats:
        - 实体A（类型A）→[关系]→ 实体B（类型B）
        - 实体A（类型A）←[关系]← 实体B（类型B）
        - 实体A →[关系]→ 实体B（without type annotations）

    Args:
        text: Full LLM answer text potentially containing 【关联实体】 block.

    Returns:
        List of entity relation dicts, each with:
        - entity_a: str, source entity name
        - entity_type_a: str or None, source entity type
        - relation: str, relationship name
        - entity_b: str, target entity name
        - entity_type_b: str or None, target entity type
        - direction: str, "forward" (→→) or "backward" (←←)
    """
    relations = []

    if not text:
        return relations

    # Locate the 【关联实体】 block
    block_match = ENTITY_RELATION_BLOCK_HEADER.search(text)
    if not block_match:
        return relations

    block_text = text[block_match.end():]
    # Stop at next section marker if any
    next_section = re.search(r'\n(?:【|\[来源|##)', block_text)
    if next_section:
        block_text = block_text[:next_section.start()]

    # Strategy 1: Full format with type annotations
    typed_matches = list(ENTITY_RELATION_PATTERN.finditer(block_text))
    typed_indices = set()
    for m in typed_matches:
        typed_indices.add(m.start())
        a_name = m.group(1).strip()
        a_type = m.group(2).strip()
        dir_symbol = m.group(3)
        rel_name = m.group(4).strip()
        b_name = m.group(5).strip()
        b_type = m.group(6).strip()
        relations.append({
            "entity_a": a_name,
            "entity_type_a": a_type,
            "relation": rel_name,
            "entity_b": b_name,
            "entity_type_b": b_type,
            "direction": "forward" if dir_symbol == "→" else "backward",
        })

    # Strategy 2: Simple format (no type annotations) — only for lines
    # that weren't already matched by the typed pattern (avoids duplicates
    # and handles mixed-format blocks correctly).
    for m in ENTITY_RELATION_SIMPLE.finditer(block_text):
        if m.start() in typed_indices:
            continue  # Already captured by typed pattern
        a_name = m.group(1).strip()
        dir_symbol = m.group(2)
        rel_name = m.group(3).strip()
        b_name = m.group(4).strip()
        relations.append({
            "entity_a": a_name,
            "entity_type_a": None,
            "relation": rel_name,
            "entity_b": b_name,
            "entity_type_b": None,
            "direction": "forward" if dir_symbol == "→" else "backward",
        })
        typed_indices.add(m.start())

    # Strategy 3: New v4 clean format (no arrow brackets):
    #   - 实体A → 实体B（关系类型）
    #   - 实体A — 实体B（关系类型）
    for m in ENTITY_RELATION_CLEAN.finditer(block_text):
        if m.start() in typed_indices:
            continue  # Already captured by previous patterns
        a_name = m.group(1).strip()
        b_name = m.group(2).strip()
        rel_name = (m.group(3) or "关联").strip()
        relations.append({
            "entity_a": a_name,
            "entity_type_a": None,
            "relation": rel_name,
            "entity_b": b_name,
            "entity_type_b": None,
            "direction": "forward",
        })

    return relations


def parse_citation_block(text: str) -> List[Dict[str, any]]:
    """解析回答末尾的引用来源块，提取结构化引用条目。

    支持的格式:
        新格式: [来源 文档名] — "被引用的原文内容..."
        旧格式: [来源 1] 源文档：xxx.pdf | 原文："被引用的原文内容..."
        旧格式: [来源 2] 源文档：yyy.docx | 原文：被引用的原文内容...

    Args:
        text: 包含引用来源块的完整回答文本

    Returns:
        引用条目列表，每项包含:
        - index: int|str, 来源标识（数字编号或文档名）
        - document_name: str, 源文档名称
        - excerpt: str, 原文摘录
    """
    citations = []

    # Find the citation block
    block_match = CITATION_BLOCK_HEADER.search(text)
    if not block_match:
        return citations

    block_text = text[block_match.end():]

    # Strategy 1: New v5 format — [来源 文档名] — "原文..."
    for m in CITATION_ENTRY_V5.finditer(block_text):
        name = display_document_name(m.group(1).strip())
        citations.append({
            "index": name,
            "document_name": name,
            "excerpt": m.group(2).strip(),
        })

    # Strategy 2: Try full format (with quotes) — [来源 N] 源文档：xxx | 原文："..."
    if not citations:
        for m in CITATION_ENTRY_PATTERN.finditer(block_text):
            citations.append({
                "index": int(m.group(1)),
                "document_name": display_document_name(m.group(2).strip()),
                "excerpt": m.group(3).strip(),
            })

    # Strategy 3: Try simplified format (without quotes)
    if not citations:
        for m in CITATION_ENTRY_SIMPLE.finditer(block_text):
            excerpt = m.group(3).strip()
            # Strip trailing punctuation
            excerpt = re.sub(r'[\s,，。.!！?？;；]+$', '', excerpt)
            citations.append({
                "index": int(m.group(1)),
                "document_name": display_document_name(m.group(2).strip()),
                "excerpt": excerpt,
            })

    return citations


def extract_citations(
    answer: str,
    source_docs: Optional[List[Dict]] = None,
    chunk_texts: Optional[Dict[int, str]] = None,
    include_entity_relations: bool = True,
) -> Dict[str, List[Dict]]:
    """从 LLM 回答中提取结构化引用列表和关联实体。

    解析策略（按优先级）：
    1. 优先解析【引用来源】块（LLM 主动提供的结构化引用）
    2. 提取内联 [来源 N] 标记，从 source_docs 或 chunk_texts 补充信息
    3. 如果以上都没有，返回提取到的索引编号
    4. 同时解析【关联实体】块（若存在）

    Args:
        answer: LLM 生成的回答文本
        source_docs: 检索到的源文档列表（可选），用于补充引用信息
        chunk_texts: chunk序号 → chunk文本的映射（可选），用于自动提取摘录
        include_entity_relations: 是否解析【关联实体】块

    Returns:
        dict with:
        - sources: 引用列表，每项包含 index, document_name, excerpt, file_path
        - entity_relations: 关联实体列表，每项包含 entity_a, entity_type_a, relation,
          entity_b, entity_type_b, direction
    """
    result: Dict[str, List[Dict]] = {
        "sources": [],
        "entity_relations": [],
    }

    if not answer:
        return result

    # Strategy 1: Parse citation block
    block_citations = parse_citation_block(answer)
    if block_citations:
        # Enrich with file_path from source_docs if available
        if source_docs:
            for cit in block_citations:
                idx = cit["index"] - 1 if isinstance(cit["index"], int) else -1
                if 0 <= idx < len(source_docs):
                    cit["file_path"] = source_docs[idx].get("file_path")
                    continue
                source_doc = next(
                    (
                        doc for doc in source_docs
                        if display_document_name(
                            doc.get("document_name")
                            or doc.get("title")
                            or doc.get("source")
                        ) == cit["document_name"]
                    ),
                    None,
                )
                cit["file_path"] = source_doc.get("file_path") if source_doc else None
        result["sources"] = block_citations
    else:
        # Strategy 2: Extract inline citations, build from context
        # Try new format first: [来源 文档名]
        names = extract_citation_names(answer)
        # Filter: only doc-name citations (non-numeric)
        doc_names = [n for n in names if not n.isdigit()]
        indices_only = [int(n) for n in names if n.isdigit()]

        sources = []
        seen = set()

        # Process doc-name citations (new format)
        for doc_name in sorted(set(doc_names)):
            citation = {
                "index": doc_name,
                "document_name": display_document_name(doc_name),
                "excerpt": None,
                "file_path": None,
            }
            # Try to find excerpt from chunk_texts by matching doc name
            if chunk_texts:
                for k, v in chunk_texts.items():
                    if doc_name in str(k) or doc_name in (v or ""):
                        citation["excerpt"] = v[:200] if v else None
                        break
            sources.append(citation)
            seen.add(doc_name)

        # Process numeric indices (old format backward compat)
        for ref_idx in sorted(indices_only):
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
                citation["document_name"] = display_document_name(
                    citation["document_name"], default=str(ref_idx)
                )
                citation["file_path"] = doc.get("file_path")
                excerpt = doc.get("content", doc.get("text", ""))
                if excerpt:
                    citation["excerpt"] = excerpt[:200]
            elif chunk_texts and ref_idx in chunk_texts:
                citation["excerpt"] = chunk_texts[ref_idx][:200]
                citation["document_name"] = f"来源 {ref_idx}"
            else:
                citation["document_name"] = f"来源 {ref_idx}"

            sources.append(citation)

        result["sources"] = sources

    # Parse entity relations block
    if include_entity_relations:
        result["entity_relations"] = parse_entity_relations(answer)

    return result


# Backward compatibility alias matching the autorepair module's API
extract_citations_from_answer = extract_citations
