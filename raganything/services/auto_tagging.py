"""Deterministic, evidence-based keyword planning for knowledge documents."""

from __future__ import annotations

import math
import os
import re
import unicodedata
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import jieba.analyse
import jieba.posseg

from raganything.services.kb_tag_repo import MAX_TAG_NAME_LENGTH, MAX_TAGS_PER_CHUNK

_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_CHINESE_WORD = re.compile(r"[\u4e00-\u9fff]{2,}")
_PAGE_MARKER = re.compile(r"(?im)^\s*[\[【]?第?\s*\d+\s*页[\]】]?\s*$")
_MEDIA_PLACEHOLDER = re.compile(
    r"(?im)^\s*(?:[\[【].*(?:图片|图像|表格|视频|image|table|video).*[\]】]|"
    r"(?:图片|图像|表格|视频|image|table|video)(?:路径|path)\s*[:：].*)\s*$"
)
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:[\\/][^\r\n\]]+")
_LONG_HASH = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_HASHED_FILENAME_PREFIX = re.compile(r"^[0-9a-fA-F]{8}_")
_ANALYSIS_HEADER = re.compile(
    r"(?im)^\s*(?:(?:image|table|video|equation|mathematical equation)"
    r"(?:\s+content)?\s+analysis|(?:图片|图像|表格|视频|数学公式|公式)(?:内容)?分析)"
    r"\s*[:：]\s*$"
)
_EVIDENCE_FIELD = re.compile(
    r"(?im)^\s*-?\s*(?:section\s+path|neighbor\s+text|captions?|footnotes?|"
    r"visual\s+analysis|comprehensive\s+video\s+analysis|analysis|transcript\s+preview|"
    r"ocr\s+text|table\s+content|context|nearby\s+heading|title|"
    r"章节路径|邻近文本|标注|标题|脚注|视觉分析|综合视频分析|分析|转录预览|"
    r"ocr文字|表格内容|上下文|邻近标题)"
    r"\s*[:：]\s*"
)
_EMPTY_EVIDENCE_FIELD = re.compile(
    r"(?im)^\s*-?\s*(?:section\s+path|neighbor\s+text|captions?|footnotes?|"
    r"visual\s+analysis|comprehensive\s+video\s+analysis|analysis|transcript\s+preview|"
    r"ocr\s+text|table\s+content|context|nearby\s+heading|title|"
    r"章节路径|邻近文本|标注|标题|脚注|视觉分析|综合视频分析|分析|转录预览|"
    r"ocr文字|表格内容|上下文|邻近标题)"
    r"\s*[:：]\s*(?:none|null|n/?a|-|无|暂无)?\s*$"
)
_DECORATIVE_EVIDENCE = re.compile(
    r"(?im)^\s*(?:(?:visual\s+analysis|视觉分析)\s*[:：]\s*)?\[?\s*"
    r"(?:(?:solid\s+)?decorative\s+(?:fill|placeholder)|"
    r"纯色装饰填充|装饰性占位图|装饰性元素|分隔线)\s*\]?\s*$"
)
_VISUAL_ANALYSIS_VALUE = re.compile(
    r"(?im)^\s*(?:visual\s+analysis|视觉分析)\s*[:：]\s*(?P<value>[^\r\n]*)\s*$"
)
_TABLE_ANALYSIS_VALUE = re.compile(
    r"(?im)^\s*(?:analysis|分析)\s*[:：]\s*(?P<value>[^\r\n]*)\s*$"
)
_PROCESSING_ERROR = re.compile(
    r"(?i)\[(?:image|video|table|equation|multimodal)?\s*processing\s*"
    r"(?:failed|error)\s*:[^\]]*\]"
)
_MEDIA_TECHNICAL_LINE = re.compile(
    r"(?im)^\s*-?\s*(?:duration|estimated\s+frames|frame\s+count|video\s+path)"
    r"\s*:\s*.*$"
)
_PERSON_METADATA = re.compile(
    r"(?i)(?:"
    r"['\"]?\s*(?:学生\s*姓名|姓\s*名|指导\s*教师|指导\s*老师|导师)"
    r"\s*['\"]?(?:\s*\((?:name|advisor|supervisor)\))?\s*(?:[:：=]|is|->|→)|"
    r"(?:student\s+name|advisor|supervisor)\s*(?:(?:[:：=]|is|->|→)\s*)?|"
    r"name\s*(?:[:：=]|is|->|→)"
    r")\s*['\"]?\s*(?P<person>[\u4e00-\u9fff]{2,4})\s*['\"]?"
)
_LOW_VALUE_VISUAL_MARKERS = (
    "decorative", "placeholder", "solid fill", "logo", "emblem",
    "cartoon", "minimalistic", "minimalist", "abstract design",
    "calligraphic", "calligraphy", "handwritten", "signature",
    "single chinese character", "displays a single",
)
_LOW_VALUE_TABLE_MARKERS = (
    "structurally empty", "no textual content", "no data rows",
    "empty table", "fillable template", "placeholder or template",
)
_GENERATED_ANALYSIS_SOURCE = re.compile(
    r"(?im)^\s*(?:(?:image|table|video|equation|mathematical equation)"
    r"(?:\s+content)?\s+analysis|(?:图片|图像|表格|视频|数学公式|公式)(?:内容)?分析)"
    r"\s*[:：]"
)
_STRUCTURAL_ASCII_KEYWORD = re.compile(
    r"(?i)^(?:(?:start|end)_)?(?:row|col)(?:_offset)?_(?:idx|index)$|"
    r"^(?:row|col)_(?:span|header)$|^(?:column|row)_header$|"
    r"^(?:content_list|section_path|neighbor_text|page)_(?:idx|index)$"
)
_TRIM_CHARS = " .,:;!?，。！？；：()[]{}<>《》【】\"'`~@#$%^&*+=|\\/"
_LOW_VALUE_PHRASE_FRAGMENTS = (
    "重新", "小心", "所指", "朝向", "处拔", "上拔", "检查", "安装", "拆卸",
    "规定", "范围", "方向", "步骤", "然后", "将其", "地将", "是油封",
)

_COMMON_TERMS = {
    "一个", "一些", "我们", "你们", "他们", "以及", "通过", "进行", "相关", "内容",
    "部分", "使用", "可以", "需要", "包括", "由于", "为了", "其中", "本文", "本章",
    "文件", "文档", "报告", "图片", "表格", "图像", "分析", "问题", "方法", "系统",
    "页面", "路径", "毕业设计", "论文", "设计", "结果", "研究", "数据", "功能", "模块",
    "实验", "性能", "意义", "整体", "本研究", "结果表明", "表明", "提高", "实现", "重要",
    "具有", "采用", "提出", "完成", "工作", "情况", "方面", "过程", "效果", "目的",
    "this", "that", "these", "those", "with", "from", "into", "will", "would", "should",
    "about", "which", "where", "there", "their", "your", "have", "been", "were", "the",
    "and", "for", "are", "was", "not", "but", "its", "our", "you", "can", "use",
    "idx", "index", "offset", "row", "rows", "col", "cols", "column", "columns",
    "header", "headers", "character", "characters", "start", "end", "text", "content",
    "image", "images", "none", "true", "false", "null", "nan", "page", "pages",
    "page_idx", "metadata", "document", "documents", "chunk", "chunks", "file", "path",
    "filepath", "full_doc_id", "tokens", "docx", "pdf", "png", "jpg", "jpeg", "table",
    "guide", "introduction", "overview", "chapter", "section",
    "analysis", "visual", "neighbor", "caption", "captions", "footnote", "footnotes",
    "decorative", "placeholder", "solid", "fill", "font", "fonts", "line", "lines",
    "background", "foreground", "drawing", "illustration", "diagram", "schematic",
    "technical", "overall", "style", "object", "objects", "shape", "shapes",
    "component", "components", "element", "elements", "layout", "appearance",
    "appears", "depicted", "displayed", "rendered", "representing", "likely",
    "white", "black", "gray", "grey", "red", "green", "blue", "yellow",
    "color", "colors", "colour", "colours", "plain", "bold", "uppercase",
    "lowercase", "against", "left", "right", "center", "central", "top", "bottom",
    "horizontal", "vertical", "diagonal", "curved", "circular", "round", "oval",
    "small", "large", "larger", "smaller", "simple", "minimalist", "prominently",
    "visible", "present", "additional", "multiple", "series", "various", "several",
    "logo", "logos", "picture", "pictures", "photo", "photograph", "frame",
    "emblem", "emblems", "symbol", "symbols", "auto", "manual", "handbook",
    "contain", "contains", "containing", "consist", "consists", "consisting",
    "feature", "features", "featuring", "include", "includes", "including",
    "show", "shows", "shown", "showing", "suggest", "suggests", "indicate",
    "indicates", "indicating", "create", "creates", "creating", "give", "gives",
    "giving", "extend", "extends", "extending", "resemble", "resembles",
    "resembling", "surround", "surrounding", "within", "toward", "towards",
    "across", "approximately", "primarily", "directly", "entirely", "clearly",
    "mechanical", "assembly", "assemblies", "structure", "structures", "part", "parts",
    "machine", "machines", "device", "devices", "manufacturing", "purpose", "function",
    "functions", "form", "forms", "detail", "details", "view", "views", "close-up",
    "design", "document", "current",
    "span", "row_span", "col_span", "ref", "fillable", "num", "cell", "cells",
    "column_header", "row_header", "metadata", "header", "headers", "empty",
    "institution", "university", "college", "department", "faculty", "student",
    "advisor", "supervisor", "major", "class", "name", "zhengzhou", "economics",
    "calligraphic", "calligraphy", "displays", "display", "single", "chinese",
    "english", "written", "handwritten", "centered", "ink", "stroke", "strokes",
    "signature", "ring", "formal", "traditional", "graphic", "comparative",
    "portion", "based", "context", "data", "user", "video", "transcript",
    "processing", "error", "failed", "invalid", "unknown",
    "手册", "说明书", "指南", "开题", "开题报告", "选题", "学院", "学校", "大学",
    "专业", "班级", "学号", "姓名", "学生", "教师", "导师", "指导", "指导教师",
    "本科毕业", "毕业设计", "任务书", "审批表", "记录表", "检查表", "题目", "课题",
    "方案", "思路", "能力", "条件", "层面", "核心", "技术", "流程", "质量",
    "资源", "类别", "任务", "测试", "工具", "人工", "自动", "检查", "集上",
    "深度", "移动", "严谨性", "优势", "阶段",
    "groups", "group", "title", "merged", "aligned", "sections", "section",
    "spanning", "structurally", "value", "values", "label", "labels",
    "academic", "institutional", "business", "trade", "project", "proposal",
    "thesis", "graduation", "motif", "imagery", "outermost", "below", "results",
    "result", "technology", "objective", "objectives", "goal", "goals",
    "培养目标", "路线", "文献资料", "进展", "目标", "毕业论文", "社会", "负责人",
    "意见", "时间", "解决办法", "用户", "场景", "效率", "差异", "直观", "门槛",
    "原型", "落地", "精细化", "工程化", "网膜", "郑州", "经贸",
    "structured", "bachelor", "both", "descriptive", "two", "titled",
    "guidance", "corresponding", "record", "records", "labeled", "labelled",
    "mp4", "计算机", "合理", "热点", "背景", "综合", "突破", "毕业", "初稿",
    "小组", "作品", "态度", "成绩", "老师", "计划", "职称", "名称",
    "key", "each", "administrative", "tool", "full", "field", "fields", "serves",
    "undergraduate", "supervision", "research", "fast", "rapid", "dense", "marked",
    "numerical", "grid", "validation", "价值", "范例", "覆盖范围", "管理", "记录",
    "历史记录", "指导老师", "总评", "委员会",
    "arrow", "arrows", "close", "possibly", "potentially", "texture", "textured",
    "art", "body", "detailing", "cylindrical", "surface", "surfaces", "edge", "edges",
    "direction", "pointing", "attached", "connected", "composition",
    "primary", "fallback", "engineering",
    "around", "represent", "represents", "represented", "depict", "depicts",
    "depicted", "other", "others", "本司", "序号", "编号", "个数", "数量",
    "规格", "单位", "备注", "项目", "步骤", "其他", "文字内容", "一缸", "上拔",
    "体螺", "螺管", "对准", "错误", "外观",
}

DEFAULT_DOCUMENT_TAG_LIMIT = 4
DEFAULT_CHUNK_TAG_LIMIT = 8
DEFAULT_RELATIVE_SCORE_FLOOR = 0.55
_BASE_TAG_TARGET = 4


@dataclass(frozen=True)
class AutomaticTagPlan:
    """Generated tag names, separated from persistence for deterministic tests."""

    document_tags: tuple[str, ...]
    document_tags_by_chunk: dict[str, tuple[str, ...]]
    chunk_tags: dict[str, tuple[str, ...]]
    eligible_chunk_ids: tuple[str, ...]
    not_applicable_chunk_ids: tuple[str, ...]
    content_fingerprint: str


def automatic_tagging_enabled() -> bool:
    return os.getenv("AUTOMATIC_TAGGING_ENABLED", "true").strip().lower() not in {
        "0", "false", "no", "off",
    }


def automatic_tagging_settings() -> dict[str, int | float]:
    def bounded_int(name: str, default: int) -> int:
        try:
            value = int(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(0, min(value, MAX_TAGS_PER_CHUNK))

    try:
        score_floor = float(
            os.getenv("AUTO_TAG_RELATIVE_SCORE_FLOOR", str(DEFAULT_RELATIVE_SCORE_FLOOR))
        )
    except (TypeError, ValueError):
        score_floor = DEFAULT_RELATIVE_SCORE_FLOOR
    return {
        "document_tag_limit": bounded_int(
            "AUTO_TAG_DOCUMENT_LIMIT", DEFAULT_DOCUMENT_TAG_LIMIT
        ),
        "chunk_tag_limit": bounded_int(
            "AUTO_TAG_CHUNK_LIMIT", DEFAULT_CHUNK_TAG_LIMIT
        ),
        "relative_score_floor": max(0.0, min(score_floor, 1.0)),
    }


def build_automatic_tag_plan(
    chunks: Iterable[dict[str, Any]],
    *,
    filename: str = "",
    document_tag_limit: int = DEFAULT_DOCUMENT_TAG_LIMIT,
    chunk_tag_limit: int = DEFAULT_CHUNK_TAG_LIMIT,
    relative_score_floor: float = DEFAULT_RELATIVE_SCORE_FLOOR,
) -> AutomaticTagPlan:
    """Select tags that are explicitly supported by title or chunk text."""
    document_limit = max(0, min(int(document_tag_limit), MAX_TAGS_PER_CHUNK))
    local_limit = max(0, min(int(chunk_tag_limit), MAX_TAGS_PER_CHUNK))
    score_floor = max(0.0, min(float(relative_score_floor), 1.0))
    chunk_ids: list[str] = []
    cleaned_by_chunk: dict[str, str] = {}
    generated_analysis_ids: set[str] = set()
    excluded_document_names: set[str] = set()
    for chunk in chunks:
        chunk_id = str(
            chunk.get("chunk_id") or chunk.get("id") or chunk.get("__id__") or ""
        )
        if not chunk_id:
            continue
        chunk_ids.append(chunk_id)
        raw_content = str(chunk.get("content") or "")
        excluded_document_names.update(
            _normalized(match.group("person"))
            for match in _PERSON_METADATA.finditer(raw_content)
        )
        if _GENERATED_ANALYSIS_SOURCE.search(raw_content):
            generated_analysis_ids.add(chunk_id)
        cleaned_by_chunk[chunk_id] = _clean_source_text(raw_content)

    usable = {key: value for key, value in cleaned_by_chunk.items() if value}
    title = _filename_keywords(filename)
    if not usable and not title:
        return AutomaticTagPlan(
            (),
            {chunk_id: () for chunk_id in chunk_ids},
            {chunk_id: () for chunk_id in chunk_ids},
            (),
            tuple(chunk_ids),
            _content_fingerprint(title, cleaned_by_chunk),
        )

    candidates_by_chunk = {
        chunk_id: [
            candidate
            for candidate in _extract_keywords(content, max(32, local_limit * 12))
            if _normalized(candidate) not in excluded_document_names
        ]
        for chunk_id, content in usable.items()
    }
    title_candidates = [
        candidate
        for candidate in _extract_keywords(title, max(12, document_limit * 6))
        if _normalized(candidate) not in excluded_document_names
    ]
    title_norms = {_normalized(value) for value in title_candidates}
    document_frequency = Counter(
        normalized
        for candidates in candidates_by_chunk.values()
        for normalized in {_normalized(value) for value in candidates}
    )
    display_by_norm: dict[str, str] = {}
    rank_by_norm: dict[str, float] = {}
    total_chunks = max(1, len(usable))
    for rank, candidate in enumerate(title_candidates):
        normalized = _normalized(candidate)
        display_by_norm.setdefault(normalized, candidate)
        rank_by_norm[normalized] = max(
            rank_by_norm.get(normalized, 0.0), 4.0 / (rank + 1)
        )
    for candidates in candidates_by_chunk.values():
        for rank, candidate in enumerate(candidates):
            normalized = _normalized(candidate)
            display_by_norm.setdefault(normalized, candidate)
            rank_by_norm[normalized] = max(
                rank_by_norm.get(normalized, 0.0), 1.0 / (rank + 1)
            )

    scored_document: list[tuple[float, str]] = []
    for normalized, display in display_by_norm.items():
        frequency = document_frequency.get(normalized, 0)
        title_supported = normalized in title_norms
        if title_norms and not title_supported:
            continue
        if not title_supported and total_chunks > 1 and frequency < 2:
            continue
        if not title_supported and not any(
            _keyword_in_text(display, content) for content in usable.values()
        ):
            continue
        coverage = frequency / total_chunks
        score = rank_by_norm.get(normalized, 0.0)
        score += 6.0 if title_supported else 0.0
        score += 2.5 * coverage + math.log1p(frequency)
        score += min(len(display), 12) / 40.0
        score += _candidate_specificity_bonus(display)
        scored_document.append((score, display))
    scored_document.sort(key=lambda value: (-value[0], _normalized(value[1])))
    document_tags = tuple(_select_diverse(scored_document, document_limit))
    document_norms = {_normalized(tag) for tag in document_tags}

    candidate_chunk_ids = tuple(
        chunk_id
        for chunk_id, content in cleaned_by_chunk.items()
        if _is_semantic_text(content) and candidates_by_chunk.get(chunk_id)
    )
    candidate_set = set(candidate_chunk_ids)
    document_tags_by_chunk = {
        chunk_id: tuple(
            tag for tag in document_tags if _keyword_in_text(tag, content)
        ) if chunk_id in candidate_set else ()
        for chunk_id, content in cleaned_by_chunk.items()
    }

    chunk_tags: dict[str, tuple[str, ...]] = {chunk_id: () for chunk_id in chunk_ids}
    for chunk_id, content in usable.items():
        if chunk_id not in candidate_set:
            continue
        scored_local: list[tuple[float, str]] = []
        for rank, candidate in enumerate(candidates_by_chunk[chunk_id]):
            normalized = _normalized(candidate)
            if normalized in document_norms or not _keyword_in_text(candidate, content):
                continue
            frequency = document_frequency.get(normalized, 1)
            if (
                chunk_id in generated_analysis_ids
                and _ASCII_WORD.fullmatch(candidate)
                and not _is_technical_identifier(candidate)
                and frequency < 2
            ):
                continue
            coverage = frequency / total_chunks
            if total_chunks > 2 and coverage > 0.75:
                continue
            occurrences = _keyword_occurrences(candidate, content)
            specificity = math.log((total_chunks + 1) / (frequency + 0.5))
            score = 2.0 / (rank + 1) + math.log1p(occurrences) + specificity
            score += min(len(candidate), 12) / 50.0
            score += _candidate_specificity_bonus(candidate)
            scored_local.append((score, candidate))
        scored_local.sort(key=lambda value: (-value[0], _normalized(value[1])))
        document_count = len(document_tags_by_chunk.get(chunk_id, ()))
        local_budget = max(0, local_limit - document_count)
        chunk_tags[chunk_id] = tuple(
            _select_adaptive_local_tags(
                scored_local,
                local_budget,
                content=content,
                document_frequency=document_frequency,
                relative_score_floor=score_floor,
            )
        )

    eligible_chunk_ids = tuple(
        chunk_id
        for chunk_id in chunk_ids
        if document_tags_by_chunk.get(chunk_id) or chunk_tags.get(chunk_id)
    )
    eligible_set = set(eligible_chunk_ids)
    not_applicable_chunk_ids = tuple(
        chunk_id for chunk_id in chunk_ids if chunk_id not in eligible_set
    )

    return AutomaticTagPlan(
        document_tags,
        document_tags_by_chunk,
        chunk_tags,
        eligible_chunk_ids,
        not_applicable_chunk_ids,
        _content_fingerprint(title, cleaned_by_chunk),
    )


def _clean_source_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _remove_low_value_analysis(text)
    text = _PROCESSING_ERROR.sub(" ", text)
    text = _MEDIA_TECHNICAL_LINE.sub(" ", text)
    text = _PERSON_METADATA.sub(" ", text)
    text = _WINDOWS_PATH.sub(" ", text)
    text = _LONG_HASH.sub(" ", text)
    text = _DECORATIVE_EVIDENCE.sub(" ", text)
    text = _EMPTY_EVIDENCE_FIELD.sub(" ", text)
    text = _ANALYSIS_HEADER.sub(" ", text)
    text = _EVIDENCE_FIELD.sub("", text)
    text = _PAGE_MARKER.sub(" ", text)
    text = _MEDIA_PLACEHOLDER.sub(" ", text)
    text = re.sub(
        r"(?im)^\s*(?:chunk_id|full_doc_id|page_idx|tokens|metadata|file_path)\s*[:=].*$",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _remove_low_value_analysis(text: str) -> str:
    """Drop decorative media and empty-table narratives before extraction."""
    if "analysis" not in text.casefold() and "分析" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        value = match.group("value").casefold()
        if any(marker in value for marker in _LOW_VALUE_VISUAL_MARKERS):
            return " "
        return match.group(0)

    text = _VISUAL_ANALYSIS_VALUE.sub(replace, text)

    def replace_table(match: re.Match[str]) -> str:
        value = match.group("value").casefold()
        if any(marker in value for marker in _LOW_VALUE_TABLE_MARKERS):
            return " "
        return match.group(0)

    return _TABLE_ANALYSIS_VALUE.sub(replace_table, text)


def _filename_keywords(filename: str) -> str:
    stem = Path(str(filename or "")).stem
    stem = _HASHED_FILENAME_PREFIX.sub("", stem)
    return _clean_source_text(re.sub(r"[_-]+", " ", stem))


def _extract_keywords(text: str, limit: int) -> list[str]:
    if not text or limit <= 0:
        return []
    text = text[:160_000]
    candidates: list[str] = []
    candidates.extend(_noun_candidates(text))
    try:
        candidates.extend(
            str(value) for value in jieba.analyse.extract_tags(
                text,
                topK=max(16, limit * 4),
                allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "eng"),
            )
        )
    except Exception:
        pass
    candidates.extend(_ASCII_WORD.findall(text))

    selected: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = _clean_keyword(candidate)
        normalized = _normalized(cleaned)
        if not cleaned or normalized in seen or not _keyword_in_text(cleaned, text):
            continue
        seen.add(normalized)
        selected.append(cleaned)
        if len(selected) >= limit:
            break
    return selected


def _clean_keyword(value: object) -> str:
    keyword = unicodedata.normalize("NFKC", str(value or "")).strip(_TRIM_CHARS)
    keyword = re.sub(r"\s+", " ", keyword)
    normalized = _normalized(keyword)
    if (
        not keyword
        or len(keyword) > MAX_TAG_NAME_LENGTH
        or keyword.isdigit()
        or normalized in _COMMON_TERMS
        or _LONG_HASH.fullmatch(keyword)
        or _STRUCTURAL_ASCII_KEYWORD.fullmatch(keyword)
        or re.fullmatch(r"(?i)rot_\d+", keyword)
        or "\\" in keyword
        or "/" in keyword
    ):
        return ""
    if _CHINESE_WORD.fullmatch(keyword):
        if any(fragment in keyword for fragment in _LOW_VALUE_PHRASE_FRAGMENTS):
            return ""
        return keyword if len(keyword) <= 16 else ""
    if _ASCII_WORD.fullmatch(keyword):
        return keyword
    return ""


def _noun_candidates(text: str) -> list[str]:
    compounds: list[str] = []
    singles: list[str] = []
    try:
        noun_run: list[str] = []
        for pair in jieba.posseg.cut(text):
            word = str(pair.word or "").strip()
            flag = str(pair.flag or "")
            if flag.startswith(("n", "vn", "eng")) and not flag.startswith("nr"):
                singles.append(word)
                if flag.startswith("n") and _CHINESE_WORD.fullmatch(word):
                    noun_run.append(word)
                    continue
            if len(noun_run) >= 2:
                compounds.extend(_compound_windows(noun_run))
            noun_run = []
        if len(noun_run) >= 2:
            compounds.extend(_compound_windows(noun_run))
    except Exception:
        return []
    return compounds + singles


def _compound_windows(words: list[str]) -> list[str]:
    values: list[str] = []
    max_width = min(4, len(words))
    for width in range(max_width, 1, -1):
        for start in range(0, len(words) - width + 1):
            value = "".join(words[start:start + width])
            if 3 <= len(value) <= 16:
                values.append(value)
    return values


def _select_adaptive_local_tags(
    scored: list[tuple[float, str]],
    limit: int,
    *,
    content: str,
    document_frequency: Counter,
    relative_score_floor: float,
) -> list[str]:
    """Select up to the hard cap without padding weak fifth-to-eighth tags."""
    if not scored or limit <= 0:
        return []
    top_score = max(scored[0][0], 0.0001)
    filtered: list[tuple[float, str]] = []
    for score, candidate in scored:
        if _is_shadowed_by_better_phrase(candidate, score, scored):
            continue
        if len(filtered) >= _BASE_TAG_TARGET:
            normalized = _normalized(candidate)
            occurrences = _keyword_occurrences(candidate, content)
            is_late_extra = len(filtered) >= 6
            medium_confidence = (
                _is_technical_identifier(candidate)
                or (_CHINESE_WORD.fullmatch(candidate) and len(candidate) >= 4)
                or (occurrences >= 2 and len(candidate) >= 3)
            )
            strong_confidence = (
                _is_technical_identifier(candidate)
                or (occurrences >= 2 and len(candidate) >= 4)
                or (document_frequency.get(normalized, 0) >= 2 and len(candidate) >= 4)
            )
            high_confidence = (
                score >= top_score * relative_score_floor
                and (strong_confidence if is_late_extra else medium_confidence)
            )
            if not high_confidence:
                continue
        filtered.append((score, candidate))
    return _select_diverse(filtered, limit)


def _candidate_specificity_bonus(candidate: str) -> float:
    if _is_technical_identifier(candidate):
        return 0.8
    if _CHINESE_WORD.fullmatch(candidate):
        if len(candidate) >= 6:
            return 1.0
        if len(candidate) >= 4:
            return 0.65
        if len(candidate) == 3:
            return 0.25
    return 0.0


def _is_shadowed_by_better_phrase(
    candidate: str,
    score: float,
    scored: list[tuple[float, str]],
) -> bool:
    normalized = _normalized(candidate)
    if len(normalized) < 2:
        return False
    for other_score, other in scored:
        other_normalized = _normalized(other)
        if (
            len(other_normalized) > len(normalized)
            and normalized in other_normalized
            and other_score >= score * 0.72
        ):
            return True
    return False


def _select_diverse(scored: list[tuple[float, str]], limit: int) -> list[str]:
    selected: list[str] = []
    selected_norms: list[str] = []
    for _score, candidate in scored:
        normalized = _normalized(candidate)
        if any(
            normalized == existing
            or (len(normalized) >= 4 and normalized in existing)
            or (len(existing) >= 4 and existing in normalized)
            for existing in selected_norms
        ):
            continue
        selected.append(candidate)
        selected_norms.append(normalized)
        if len(selected) >= limit:
            break
    return selected


def _keyword_in_text(keyword: str, text: str) -> bool:
    return _normalized(keyword) in _normalized(text)


def _keyword_occurrences(keyword: str, text: str) -> int:
    return max(1, _normalized(text).count(_normalized(keyword)))


def _is_semantic_text(text: str) -> bool:
    if len(text.strip()) < 8:
        return False
    return bool(_CHINESE_WORD.search(text) or len(_ASCII_WORD.findall(text)) >= 2)


def _is_technical_identifier(value: str) -> bool:
    if any(char.isdigit() for char in value):
        return True
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return False
    uppercase = sum(char.isupper() for char in letters)
    return uppercase >= 2 or (uppercase >= 1 and any(char.isupper() for char in letters[1:]))


def _content_fingerprint(title: str, chunks: dict[str, str]) -> str:
    digest = hashlib.sha256()
    digest.update(_normalized(title).encode("utf-8"))
    for chunk_id in sorted(chunks):
        digest.update(b"\0")
        digest.update(chunk_id.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(chunks[chunk_id].encode("utf-8", errors="replace"))
    return digest.hexdigest()


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if re.fullmatch(r"[a-z][a-z0-9_-]{3,}", normalized):
        if normalized.endswith("ies") and len(normalized) > 5:
            return normalized[:-3] + "y"
        if normalized.endswith("es") and len(normalized) > 5:
            return normalized[:-2]
        if normalized.endswith("s") and not normalized.endswith("ss") and len(normalized) > 4:
            return normalized[:-1]
    return normalized
