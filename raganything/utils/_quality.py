# -*- coding: utf-8 -*-
"""
OCR Quality Validation & Parse-Method Auto-Selection.

Layer: Core
Primary Responsibility: Validate extracted text quality from MinerU content lists,
    detect garbled/truncated output, and recommend parse-method fallbacks when
    the current method produced low-quality results.

Key Dependencies: stdlib only (no heavy imports)

Functions:
    check_ocr_quality()       — Validate extracted text quality (0.0–1.0 score)
    suggest_parse_method()     — Recommend best MinerU parse method for a file
    detect_document_language() — Heuristic language detection (zh/en/mixed)
    is_likely_scanned()        — Guess whether a PDF is scanned vs digital
"""

from __future__ import annotations

import re
import os
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# Character classification for quality scoring
# ═══════════════════════════════════════════════════════════════

# Unicode ranges for common writing systems
_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Unified Ideographs Extension A
    (0x20000, 0x2A6DF), # CJK Unified Ideographs Extension B
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
    (0x2F800, 0x2FA1F), # CJK Compatibility Ideographs Supplement
]

_JAPANESE_RANGES = [
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
]

_VALID_SYMBOL_RANGES = [
    (0x0020, 0x007E),   # ASCII printable
    (0x2000, 0x206F),   # General Punctuation
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),   # Halfwidth and Fullwidth Forms
    (0x2500, 0x257F),   # Box Drawing
    (0x2580, 0x259F),   # Block Elements
    (0x00A0, 0x00FF),   # Latin-1 Supplement
    (0x2010, 0x2027),   # Dashes and quotes
    (0x2028, 0x202F),   # Line/paragraph separators
    (0xFE30, 0xFE4F),   # CJK Compatibility Forms
]

# Common OCR garbling patterns
_GARBLING_PATTERNS = [
    re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]'),  # Control chars (except \n, \t, \r)
    re.compile(r'[�￾￿]'),            # Unicode replacement/invalid
    re.compile(r'[^\S\n\r]{10,}'),                   # 10+ consecutive non-newline whitespace
    re.compile(r'(.)\1{10,}'),                       # 10+ repeated same char
]


def _in_ranges(codepoint: int, ranges: list) -> bool:
    """Check if a Unicode codepoint falls within any of the given ranges."""
    for lo, hi in ranges:
        if lo <= codepoint <= hi:
            return True
    return False


def _is_valid_char(ch: str) -> bool:
    """Check if a character is valid (CJK, ASCII, common symbols)."""
    cp = ord(ch)
    if ch in '\n\r\t':
        return True
    if _in_ranges(cp, _CJK_RANGES):
        return True
    if _in_ranges(cp, _JAPANESE_RANGES):
        return True
    if _in_ranges(cp, _VALID_SYMBOL_RANGES):
        return True
    return False


def _is_chinese_char(ch: str) -> bool:
    """Check if a character is a CJK ideograph."""
    cp = ord(ch)
    return _in_ranges(cp, _CJK_RANGES)


def _is_english_char(ch: str) -> bool:
    """Check if a character is an ASCII letter."""
    return ch.isascii() and ch.isalpha()


# ═══════════════════════════════════════════════════════════════
# OCR Quality Check
# ═══════════════════════════════════════════════════════════════


def check_ocr_quality(
    content_list: List[Dict[str, Any]],
    *,
    min_char_validity: float = 0.70,
    min_text_density: int = 20,
) -> Tuple[float, Dict[str, Any]]:
    """Validate extracted text quality from a MinerU content list.

    Returns a quality score (0.0–1.0) and a diagnostic info dict.
    Score >= 0.8 = good, 0.5–0.8 = marginal, < 0.5 = poor.

    Args:
        content_list: MinerU content list (list of dicts with type/text/page_idx)
        min_char_validity: Minimum ratio of valid characters (default 0.70)
        min_text_density: Minimum average chars per page (default 20)

    Returns:
        (quality_score, diagnostics) where diagnostics includes:
            - char_validity_ratio: fraction of chars that are valid
            - total_chars: total character count in text blocks
            - total_pages: max page index + 1
            - chars_per_page: average chars per page
            - chinese_ratio: fraction of chars that are CJK
            - english_ratio: fraction of chars that are ASCII letters
            - garbling_count: number of garbling patterns detected
            - issues: list of human-readable issue descriptions
            - quality_label: "good" | "marginal" | "poor"
    """
    # Extract all text
    text_parts: List[str] = []
    max_page = 0
    page_texts: Dict[int, str] = {}

    for item in content_list:
        if not isinstance(item, dict):
            continue
        page_idx = item.get("page_idx", 0)
        if isinstance(page_idx, int) and page_idx > max_page:
            max_page = page_idx

        if item.get("type", "text") == "text":
            text = str(item.get("text", "") or "")
            if text.strip():
                text_parts.append(text)
                page_texts[page_idx] = page_texts.get(page_idx, "") + text

    all_text = "".join(text_parts)
    total_chars = len(all_text)
    total_pages = max_page + 1 if max_page >= 0 else 1

    diagnostics: Dict[str, Any] = {
        "total_chars": total_chars,
        "total_pages": total_pages,
        "text_blocks": len(text_parts),
    }

    # ── Empty / near-empty ──
    if total_chars < 10:
        return 0.0, {
            **diagnostics,
            "char_validity_ratio": 0.0,
            "chars_per_page": 0.0,
            "chinese_ratio": 0.0,
            "english_ratio": 0.0,
            "garbling_count": 0,
            "issues": ["No text extracted — document may be purely images or OCR failed completely"],
            "quality_label": "poor",
        }

    # ── Character validity ──
    valid_chars = sum(1 for ch in all_text if _is_valid_char(ch))
    char_validity = valid_chars / max(total_chars, 1)

    # ── Language breakdown ──
    chinese_chars = sum(1 for ch in all_text if _is_chinese_char(ch))
    english_chars = sum(1 for ch in all_text if _is_english_char(ch))
    chinese_ratio = chinese_chars / max(total_chars, 1)
    english_ratio = english_chars / max(total_chars, 1)

    # ── Garbling detection ──
    garbling_count = 0
    for pattern in _GARBLING_PATTERNS:
        garbling_count += len(pattern.findall(all_text))

    # ── Text density (chars per page) ──
    chars_per_page = total_chars / max(total_pages, 1)
    pages_with_text = len(page_texts)
    pages_without_text = max(total_pages, 1) - pages_with_text

    # ── Identify issues ──
    issues: List[str] = []
    if char_validity < min_char_validity:
        issues.append(
            f"Low character validity: {char_validity:.1%} (threshold: {min_char_validity:.1%})"
        )
    if chars_per_page < min_text_density:
        issues.append(
            f"Low text density: {chars_per_page:.0f} chars/page "
            f"(threshold: {min_text_density})"
        )
    if pages_without_text > 0:
        issues.append(
            f"{pages_without_text}/{total_pages} pages have no extractable text"
        )
    if garbling_count > max(total_chars * 0.01, 3):
        issues.append(
            f"Garbling detected: {garbling_count} suspicious patterns"
        )
    if chinese_ratio > 0.3 and char_validity < 0.6:
        issues.append(
            "Chinese text with low validity — likely OCR misread (try 'ocr' method)"
        )

    # ── Composite quality score ──
    # Weighted: 40% char validity, 30% density, 20% garbling penalty, 10% page coverage
    density_score = min(chars_per_page / max(min_text_density, 1), 1.0)
    garbling_penalty = max(0.0, 1.0 - garbling_count / max(total_chars * 0.02, 1))
    page_coverage = pages_with_text / max(total_pages, 1)

    quality_score = (
        0.40 * char_validity
        + 0.30 * density_score
        + 0.20 * garbling_penalty
        + 0.10 * page_coverage
    )
    quality_score = max(0.0, min(1.0, quality_score))

    if quality_score >= 0.8:
        quality_label = "good"
    elif quality_score >= 0.5:
        quality_label = "marginal"
    else:
        quality_label = "poor"

    return quality_score, {
        **diagnostics,
        "char_validity_ratio": round(char_validity, 4),
        "chars_per_page": round(chars_per_page, 1),
        "chinese_ratio": round(chinese_ratio, 4),
        "english_ratio": round(english_ratio, 4),
        "garbling_count": garbling_count,
        "pages_without_text": pages_without_text,
        "issues": issues,
        "quality_label": quality_label,
    }


# ═══════════════════════════════════════════════════════════════
# Language Detection
# ═══════════════════════════════════════════════════════════════


def detect_document_language(content_list: List[Dict[str, Any]]) -> str:
    """Heuristic language detection from extracted text.

    Returns one of: "zh" (Chinese-dominant), "en" (English-dominant),
    "mixed" (bilingual), or "unknown" (insufficient text).
    """
    text_parts = []
    for item in content_list:
        if isinstance(item, dict) and item.get("type", "text") == "text":
            t = str(item.get("text", "") or "").strip()
            if t:
                text_parts.append(t)

    all_text = "".join(text_parts)
    if len(all_text) < 50:
        return "unknown"

    chinese = sum(1 for ch in all_text if _is_chinese_char(ch))
    english = sum(1 for ch in all_text if _is_english_char(ch))
    total = max(chinese + english, 1)

    cn_ratio = chinese / total
    en_ratio = english / total

    if cn_ratio > 0.7:
        return "zh"
    if en_ratio > 0.7:
        return "en"
    if cn_ratio > 0.2 and en_ratio > 0.2:
        return "mixed"
    return "unknown"


# ═══════════════════════════════════════════════════════════════
# Scanned vs Digital Detection
# ═══════════════════════════════════════════════════════════════


def is_likely_scanned(content_list: List[Dict[str, Any]]) -> Tuple[bool, float, str]:
    """Guess whether a document is a scanned image-based PDF.

    Uses heuristics:
    - Low text extraction yield from 'auto' method → likely scanned
    - High image-to-text ratio → likely scanned
    - Text blocks per page (digital PDFs have many, scanned have few)

    Returns:
        (is_scanned, confidence, reason)
    """
    text_blocks = 0
    image_blocks = 0
    total_chars = 0
    pages_with_text: set = set()

    for item in content_list:
        if not isinstance(item, dict):
            continue
        t = item.get("type", "text")
        page_idx = item.get("page_idx", 0)
        if t == "text":
            text = str(item.get("text", "") or "").strip()
            if text:
                text_blocks += 1
                total_chars += len(text)
                if isinstance(page_idx, int):
                    pages_with_text.add(page_idx)
        elif t == "image":
            image_blocks += 1

    total_pages = max(
        (item.get("page_idx", 0) or 0 for item in content_list if isinstance(item, dict)),
        default=0,
    ) + 1

    # Heuristic 1: Very few text blocks per page → scanned
    text_blocks_per_page = text_blocks / max(total_pages, 1)

    # Heuristic 2: Very low char yield → OCR didn't find text
    chars_per_page = total_chars / max(total_pages, 1)

    # Heuristic 3: High image-to-text ratio → scanned image PDF
    img_text_ratio = image_blocks / max(text_blocks, 1)

    reasons: List[str] = []
    confidence = 0.0

    if text_blocks_per_page < 2 and chars_per_page < 100:
        confidence += 0.5
        reasons.append(f"Only {text_blocks_per_page:.1f} text blocks/page")

    if chars_per_page < 50:
        confidence += 0.3
        reasons.append(f"Very low text yield: {chars_per_page:.0f} chars/page")

    if img_text_ratio > 0.5:
        confidence += 0.2
        reasons.append(f"High image-to-text ratio: {img_text_ratio:.1f}")

    confidence = min(1.0, confidence)
    is_scanned = confidence >= 0.5

    reason = "; ".join(reasons) if reasons else "Document appears to be digital (text-rich)"

    return is_scanned, confidence, reason


# ═══════════════════════════════════════════════════════════════
# Parse Method Auto-Selection
# ═══════════════════════════════════════════════════════════════


def suggest_parse_method(
    content_list: List[Dict[str, Any]],
    current_method: str = "auto",
    *,
    quality_threshold: float = 0.7,
) -> Optional[Dict[str, Any]]:
    """Recommend the best MinerU parse method based on quality assessment.

    Called after a parse attempt to decide whether to retry with a different
    method. Returns None if the current result is good enough.

    Args:
        content_list: Content list from the current parse attempt
        current_method: The parse method that produced this content_list
        quality_threshold: Minimum quality score to accept (default 0.7)

    Returns:
        None if quality is acceptable, or a dict with:
            - method: recommended parse method ("ocr", "auto", "txt")
            - reason: human-readable explanation
            - quality_score: current quality score (0.0–1.0)
            - backend: optional backend suggestion
            - language: detected language (for -l flag)
    """
    quality_score, diagnostics = check_ocr_quality(content_list)

    if quality_score >= quality_threshold:
        return None  # Good enough, no need to retry

    # ── Determine what went wrong and suggest a fix ──
    char_validity = diagnostics.get("char_validity_ratio", 0.0)
    chars_per_page = diagnostics.get("chars_per_page", 0.0)
    chinese_ratio = diagnostics.get("chinese_ratio", 0.0)

    is_scanned, scan_conf, scan_reason = is_likely_scanned(content_list)
    language = detect_document_language(content_list)

    suggestion = {
        "quality_score": round(quality_score, 3),
        "language": language,
        "reason": "",
        "method": "auto",
        "backend": None,
    }

    # Case 1: Very few chars — document is likely scanned, use OCR
    if chars_per_page < 30 and is_scanned:
        suggestion["method"] = "ocr"
        suggestion["reason"] = (
            f"Document appears to be scanned ({scan_reason}). "
            f"Switching from '{current_method}' to 'ocr' for better text extraction."
        )

    # Case 2: Low char validity with Chinese — OCR with Chinese language hint
    elif char_validity < 0.5 and chinese_ratio > 0.3:
        suggestion["method"] = "ocr"
        suggestion["reason"] = (
            f"Chinese text with low validity ({char_validity:.1%}). "
            f"Retrying with 'ocr' method for better CJK recognition."
        )
        if language in ("zh", "mixed"):
            suggestion["language"] = language

    # Case 3: Moderate garbling — try OCR as fallback
    elif char_validity < 0.6:
        suggestion["method"] = "ocr"
        suggestion["reason"] = (
            f"Character validity is low ({char_validity:.1%}). "
            f"Retrying with 'ocr' method."
        )

    # Case 4: txt method produced nothing useful → try auto
    elif current_method == "txt" and chars_per_page < 20:
        suggestion["method"] = "auto"
        suggestion["reason"] = (
            f"'txt' method extracted very little text ({chars_per_page:.0f} chars/page). "
            f"Retrying with 'auto' to attempt OCR if needed."
        )

    # Case 5: auto produced nothing → explicit OCR
    elif current_method == "auto" and chars_per_page < 10:
        suggestion["method"] = "ocr"
        suggestion["reason"] = (
            f"'auto' method extracted almost no text. "
            f"Explicitly switching to 'ocr'."
        )

    # Default fallback
    else:
        suggestion["method"] = "ocr"
        suggestion["reason"] = (
            f"Quality score {quality_score:.2f} is below threshold "
            f"{quality_threshold}. Retrying with 'ocr'."
        )

    return suggestion


# ═══════════════════════════════════════════════════════════════
# Convenience: Combined quality + suggestion in one call
# ═══════════════════════════════════════════════════════════════


def validate_and_suggest(
    content_list: List[Dict[str, Any]],
    current_method: str = "auto",
    *,
    quality_threshold: float = 0.7,
) -> Dict[str, Any]:
    """Run quality check and get a parse-method suggestion in one call.

    Returns a dict suitable for logging and decision-making:
        {
            "quality_score": float,
            "quality_label": "good" | "marginal" | "poor",
            "needs_retry": bool,
            "suggestion": None or {...},
            "diagnostics": {...},
        }
    """
    quality_score, diagnostics = check_ocr_quality(content_list)
    suggestion = suggest_parse_method(
        content_list, current_method, quality_threshold=quality_threshold
    )

    return {
        "quality_score": round(quality_score, 3),
        "quality_label": diagnostics.get("quality_label", "unknown"),
        "needs_retry": suggestion is not None,
        "suggestion": suggestion,
        "diagnostics": diagnostics,
    }


__all__ = [
    "check_ocr_quality",
    "suggest_parse_method",
    "detect_document_language",
    "is_likely_scanned",
    "validate_and_suggest",
]
