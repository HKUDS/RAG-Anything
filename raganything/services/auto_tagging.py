"""Local, deterministic keyword planning for uploaded knowledge documents."""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import jieba.analyse

from raganything.services.kb_tag_repo import MAX_TAG_NAME_LENGTH, MAX_TAGS_PER_CHUNK

_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_CHINESE_WORD = re.compile(r"[\u4e00-\u9fff]{2,}")
_TRIM_CHARS = " .,:;!?，。！？、()[]{}<>《》【】'\"`~@#$%^&*+=|\\/"
_COMMON_TERMS = {
    "一个", "一些", "我们", "你们", "他们", "以及", "通过", "进行", "相关", "内容",
    "部分", "使用", "可以", "需要", "包括", "由于", "为了", "其中", "本文", "本章",
    "文件", "文档", "报告", "图片", "表格", "图像", "分析", "问题", "方法", "系统",
    "this", "that", "these", "those", "with", "from", "into", "will", "would", "should",
    "about", "which", "where", "there", "their", "your", "have", "been", "were", "the",
    "and", "for", "are", "was", "not", "but", "its", "our", "you", "can", "use",
    "idx", "index", "offset", "row", "rows", "col", "cols", "column", "columns",
    "header", "headers", "character", "characters", "start", "end", "text", "content",
    "image", "images", "none", "true", "false", "null", "nan", "page", "pages",
    "page_idx", "metadata", "document", "documents", "chunk", "chunks", "file", "path",
    "filepath", "full_doc_id", "tokens",
}


@dataclass(frozen=True)
class AutomaticTagPlan:
    """Generated tag names, kept separate so storage writes remain testable."""

    document_tags: tuple[str, ...]
    chunk_tags: dict[str, tuple[str, ...]]


def automatic_tagging_enabled() -> bool:
    return os.getenv("AUTOMATIC_TAGGING_ENABLED", "true").strip().lower() not in {
        "0", "false", "no", "off",
    }


def build_automatic_tag_plan(
    chunks: Iterable[dict[str, Any]],
    *,
    filename: str = "",
    document_tag_limit: int = 3,
    chunk_tag_limit: int = 3,
) -> AutomaticTagPlan:
    """Build document-wide and chunk-local keyword tags without an LLM call."""
    document_limit = max(0, min(int(document_tag_limit), MAX_TAGS_PER_CHUNK))
    local_limit = max(0, min(int(chunk_tag_limit), MAX_TAGS_PER_CHUNK))
    chunk_ids: list[str] = []
    usable: list[tuple[str, str]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or chunk.get("__id__") or "")
        content = str(chunk.get("content") or "").strip()
        if not chunk_id:
            continue
        chunk_ids.append(chunk_id)
        if content:
            usable.append((chunk_id, content))
    if not usable:
        return AutomaticTagPlan((), {chunk_id: () for chunk_id in chunk_ids})

    title = _filename_keywords(filename)
    document_text = "\n".join(content for _, content in usable)
    document_candidates = _extract_keywords(
        f"{title}\n{title}\n{document_text}", max(12, document_limit * 5)
    )
    document_tags = tuple(document_candidates[:document_limit])
    document_norms = {_normalized(tag) for tag in document_tags}

    candidates_by_chunk = {
        chunk_id: _extract_keywords(content, max(12, local_limit * 5))
        for chunk_id, content in usable
    }
    document_frequency = Counter(
        normalized
        for candidates in candidates_by_chunk.values()
        for normalized in {_normalized(value) for value in candidates}
    )
    chunk_tags: dict[str, tuple[str, ...]] = {chunk_id: () for chunk_id in chunk_ids}
    for chunk_id, candidates in candidates_by_chunk.items():
        selected: list[str] = []
        selected_norms: set[str] = set()
        for candidate in candidates:
            normalized = _normalized(candidate)
            if normalized in document_norms or document_frequency[normalized] > max(1, len(usable) // 2):
                continue
            if normalized in selected_norms:
                continue
            selected.append(candidate)
            selected_norms.add(normalized)
            if len(selected) >= local_limit:
                break
        chunk_tags[chunk_id] = tuple(selected)
    return AutomaticTagPlan(document_tags, chunk_tags)


def _filename_keywords(filename: str) -> str:
    stem = Path(str(filename or "")).stem
    return re.sub(r"[_-]+", " ", stem)


def _extract_keywords(text: str, limit: int) -> list[str]:
    if not text or limit <= 0:
        return []
    text = text[:160_000]
    candidates: list[str] = []
    try:
        candidates.extend(
            str(value)
            for value in jieba.analyse.extract_tags(text, topK=max(12, limit * 4))
        )
    except Exception:
        pass
    candidates.extend(_CHINESE_WORD.findall(text))
    candidates.extend(_ASCII_WORD.findall(text))

    selected: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = _clean_keyword(candidate)
        normalized = _normalized(cleaned)
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(cleaned)
        if len(selected) >= limit:
            break
    return selected


def _clean_keyword(value: object) -> str:
    keyword = unicodedata.normalize("NFKC", str(value or "")).strip(_TRIM_CHARS)
    keyword = re.sub(r"\s+", " ", keyword)
    if not keyword or len(keyword) > MAX_TAG_NAME_LENGTH or keyword.isdigit():
        return ""
    normalized = _normalized(keyword)
    if normalized in _COMMON_TERMS:
        return ""
    if not (_CHINESE_WORD.fullmatch(keyword) or _ASCII_WORD.fullmatch(keyword)):
        return ""
    return keyword


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
