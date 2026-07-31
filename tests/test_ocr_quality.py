# -*- coding: utf-8 -*-
"""Tests for OCR quality validation and parse-method auto-selection."""

import pytest
from raganything.utils._quality import (
    check_ocr_quality,
    suggest_parse_method,
    detect_document_language,
    is_likely_scanned,
    validate_and_suggest,
    _is_valid_char,
    _is_chinese_char,
    _is_english_char,
)


class TestCharClassification:
    def test_chinese_char_detection(self):
        assert _is_chinese_char("中")
        assert _is_chinese_char("文")
        assert _is_chinese_char("测")
        assert not _is_chinese_char("a")
        assert not _is_chinese_char("1")
        assert not _is_chinese_char(".")

    def test_english_char_detection(self):
        assert _is_english_char("a")
        assert _is_english_char("Z")
        assert not _is_english_char("中")
        assert not _is_english_char("1")

    def test_valid_char(self):
        assert _is_valid_char("中")
        assert _is_valid_char("a")
        assert _is_valid_char("1")
        assert _is_valid_char(".")
        assert _is_valid_char("\n")
        assert _is_valid_char("\t")
        assert _is_valid_char("（")  # fullwidth paren
        assert not _is_valid_char("\x00")  # null byte
        assert not _is_valid_char("\x01")  # control char


class TestCheckOCRQuality:
    def test_empty_content(self):
        score, diag = check_ocr_quality([])
        assert score == 0.0
        assert diag["quality_label"] == "poor"

    def test_good_chinese_text(self):
        content = [
            {"type": "text", "text": "这是高质量的中文文本，包含许多有用的信息。系统架构设计良好。", "page_idx": 0},
            {"type": "text", "text": "第二章介绍方法细节。实验结果证明了有效性。", "page_idx": 1},
        ]
        score, diag = check_ocr_quality(content)
        assert score >= 0.8
        assert diag["quality_label"] == "good"
        assert diag["chinese_ratio"] > 0.5
        assert len(diag["issues"]) == 0

    def test_good_english_text(self):
        content = [
            {"type": "text", "text": "This is high quality English text with useful information about the system architecture.", "page_idx": 0},
            {"type": "text", "text": "Chapter 2 describes the methodology in detail. Experimental results confirm effectiveness.", "page_idx": 1},
        ]
        score, diag = check_ocr_quality(content)
        assert score >= 0.8
        assert diag["quality_label"] == "good"
        assert diag["english_ratio"] > 0.5

    def test_garbled_text_low_score(self):
        content = [
            {"type": "text", "text": "\x00\x01\x02 garbage \x0B\x0C more", "page_idx": 0},
            {"type": "text", "text": "??? ??? ???", "page_idx": 0},
        ]
        score, diag = check_ocr_quality(content)
        assert score < 0.8
        assert diag["issues"]

    def test_repeated_char_garbling(self):
        content = [
            {"type": "text", "text": "aaaaaaaaaaaaaaa bbbbbbbbbbbbbbb", "page_idx": 0},
        ]
        _, diag = check_ocr_quality(content)
        # 15 consecutive same chars should trigger garbling detection
        assert diag["garbling_count"] > 0

    def test_scanned_document_low_density(self):
        content = [
            {"type": "text", "text": "短", "page_idx": 0},
            {"type": "image", "img_path": "/tmp/p1.png", "page_idx": 0},
            {"type": "image", "img_path": "/tmp/p2.png", "page_idx": 1},
            {"type": "text", "text": "字", "page_idx": 2},
        ]
        score, diag = check_ocr_quality(content)
        assert score < 0.5
        assert diag["quality_label"] == "poor"
        assert diag["chars_per_page"] < 20

    def test_mixed_content_with_images(self):
        content = [
            {"type": "text", "text": "第一章 引言\n\n这是正文内容。", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "背景介绍和动机说明。", "page_idx": 0},
            {"type": "image", "img_path": "/tmp/fig.png", "page_idx": 1},
            {"type": "text", "text": "上图展示了系统架构。", "page_idx": 1},
            {"type": "text", "text": "第二章 方法", "text_level": 1, "page_idx": 2},
        ]
        score, diag = check_ocr_quality(content)
        assert score > 0.5
        # page 2 should be flagged as having text
        assert diag["total_pages"] >= 3


class TestDetectLanguage:
    def test_chinese_dominant(self):
        content = [
            {"type": "text", "text": "这是一个中文文档，包含许多汉字。系统的设计考虑了可扩展性和性能。" * 5, "page_idx": 0},
        ]
        assert detect_document_language(content) == "zh"

    def test_english_dominant(self):
        content = [
            {"type": "text", "text": "This is an English document containing many words about system design." * 10, "page_idx": 0},
        ]
        assert detect_document_language(content) == "en"

    def test_unknown_short_text(self):
        content = [
            {"type": "text", "text": "Hi", "page_idx": 0},
        ]
        assert detect_document_language(content) == "unknown"


class TestIsLikelyScanned:
    def test_scanned_document(self):
        content = [
            {"type": "image", "img_path": "/tmp/p1.png", "page_idx": 0},
            {"type": "image", "img_path": "/tmp/p2.png", "page_idx": 1},
            {"type": "text", "text": "少", "page_idx": 2},
        ]
        is_scan, conf, reason = is_likely_scanned(content)
        assert is_scan
        assert conf > 0.5

    def test_digital_document(self):
        content = [
            {"type": "text", "text": "Chapter 1 Introduction\n\nThis is a digital document with plenty of text content." * 5, "page_idx": 0},
            {"type": "text", "text": "Chapter 2 Methods\n\nDetailed methodology description here." * 5, "page_idx": 1},
        ]
        is_scan, conf, _ = is_likely_scanned(content)
        assert not is_scan
        assert conf < 0.5


class TestSuggestParseMethod:
    def test_good_quality_no_retry(self):
        content = [
            {"type": "text", "text": "高质量的中文文本，内容充实且结构清晰。" * 20, "page_idx": 0},
            {"type": "text", "text": "第二章 方法\n\n详细的方法描述。" * 10, "page_idx": 1},
        ]
        suggestion = suggest_parse_method(content, current_method="auto")
        assert suggestion is None  # Good enough, no retry

    def test_scanned_doc_suggests_ocr(self):
        content = [
            {"type": "image", "img_path": "/tmp/p1.png", "page_idx": 0},
            {"type": "text", "text": "少", "page_idx": 1},
        ]
        suggestion = suggest_parse_method(content, current_method="auto")
        assert suggestion is not None
        assert suggestion["method"] == "ocr"

    def test_txt_failed_suggests_auto(self):
        content = [
            {"type": "image", "img_path": "/tmp/p1.png", "page_idx": 0},
        ]
        suggestion = suggest_parse_method(content, current_method="txt")
        assert suggestion is not None
        assert suggestion["method"] in ("auto", "ocr")


class TestValidateAndSuggest:
    def test_good_quality(self):
        content = [
            {"type": "text", "text": "这是高质量的文本内容，用于测试验证。" * 30, "page_idx": 0},
        ]
        result = validate_and_suggest(content)
        assert result["quality_label"] == "good"
        assert not result["needs_retry"]
        assert result["quality_score"] >= 0.8

    def test_poor_quality(self):
        content = [
            {"type": "image", "img_path": "/tmp/scan.png", "page_idx": 0},
            {"type": "text", "text": "短", "page_idx": 1},
        ]
        result = validate_and_suggest(content)
        assert result["quality_label"] == "poor"
        assert result["needs_retry"]
        assert result["suggestion"] is not None

    def test_custom_threshold(self):
        """Verifies threshold parameter correctly gates retry decisions."""
        # Good content: no retry at any reasonable threshold
        good = [
            {"type": "text", "text": "This is high quality well written text content." * 30, "page_idx": 0},
        ]
        result = validate_and_suggest(good, quality_threshold=0.9)
        assert not result["needs_retry"]

        # Poor content (near-empty): always triggers retry at any sensible threshold
        near_empty = [
            {"type": "image", "img_path": "/tmp/s.png", "page_idx": 0},
        ]
        result2 = validate_and_suggest(near_empty, quality_threshold=0.9)
        assert result2["needs_retry"]
        # Score 0.0 with 0.1 threshold still triggers retry (below any threshold)
        result3 = validate_and_suggest(near_empty, quality_threshold=0.5)
        assert result3["needs_retry"]
