"""
Comprehensive tests for RAGAnything core modules.

Covers: config, utils, base, batch_parser, and enhanced_markdown.
Expands the project's test surface area significantly.
"""

import pytest
import base64
from pathlib import Path

from raganything.config import RAGAnythingConfig
from raganything.base import DocStatus
from raganything.utils import (
    separate_content,
    encode_image_to_base64,
    validate_image_file,
    get_processor_for_type,
    get_processor_supports,
)


# ── DocStatus Tests ──────────────────────────────────────────────


class TestDocStatus:
    def test_status_values(self):
        assert DocStatus.READY == "ready"
        assert DocStatus.HANDLING == "handling"
        assert DocStatus.PENDING == "pending"
        assert DocStatus.PROCESSING == "processing"
        assert DocStatus.PROCESSED == "processed"
        assert DocStatus.FAILED == "failed"

    def test_is_string_enum(self):
        assert isinstance(DocStatus.READY, str)
        assert DocStatus.PROCESSED == "processed"

    def test_all_statuses_unique(self):
        values = [s.value for s in DocStatus]
        assert len(values) == len(set(values))


# ── RAGAnythingConfig Tests ──────────────────────────────────────


class TestRAGAnythingConfig:
    def test_default_values(self, monkeypatch):
        # Clear environment overrides to make defaults deterministic
        for key in [
            "PARSER",
            "PARSE_METHOD",
            "ENABLE_IMAGE_PROCESSING",
            "ENABLE_TABLE_PROCESSING",
            "ENABLE_EQUATION_PROCESSING",
            "MAX_CONCURRENT_FILES",
            "CONTEXT_WINDOW",
            "CONTEXT_MODE",
            "MAX_CONTEXT_TOKENS",
            "INCLUDE_HEADERS",
            "INCLUDE_CAPTIONS",
            "USE_FULL_PATH",
        ]:
            monkeypatch.delenv(key, raising=False)

        config = RAGAnythingConfig()
        assert config.parse_method == "auto"
        assert config.parser == "mineru"
        assert config.enable_image_processing is True
        assert config.enable_table_processing is True
        assert config.enable_equation_processing is True
        assert config.max_concurrent_files == 1
        assert config.context_window == 1
        assert config.context_mode == "page"
        assert config.max_context_tokens == 2000
        assert config.include_headers is True
        assert config.include_captions is True
        assert config.use_full_path is False

    def test_custom_values(self):
        config = RAGAnythingConfig(
            working_dir="/tmp/custom",
            parser="docling",
            parse_method="ocr",
            enable_image_processing=False,
            max_concurrent_files=4,
            context_window=3,
        )
        assert config.working_dir == "/tmp/custom"
        assert config.parser == "docling"
        assert config.parse_method == "ocr"
        assert config.enable_image_processing is False
        assert config.max_concurrent_files == 4
        assert config.context_window == 3

    def test_supported_file_extensions_is_list(self):
        config = RAGAnythingConfig()
        assert isinstance(config.supported_file_extensions, list)
        assert ".pdf" in config.supported_file_extensions

    def test_context_filter_content_types(self):
        config = RAGAnythingConfig()
        assert isinstance(config.context_filter_content_types, list)
        assert "text" in config.context_filter_content_types

    def test_deprecated_mineru_parse_method(self):
        config = RAGAnythingConfig(parse_method="ocr")
        with pytest.warns(DeprecationWarning, match="deprecated"):
            _ = config.mineru_parse_method

    def test_deprecated_mineru_parse_method_setter(self):
        config = RAGAnythingConfig()
        with pytest.warns(DeprecationWarning, match="deprecated"):
            config.mineru_parse_method = "txt"
        assert config.parse_method == "txt"


# ── Content Separation Tests ─────────────────────────────────────


class TestSeparateContent:
    def test_empty_list(self):
        text, multimodal = separate_content([])
        assert text == ""
        assert multimodal == []

    def test_text_only(self):
        content = [
            {"type": "text", "text": "Hello world"},
            {"type": "text", "text": "Second paragraph"},
        ]
        text, multimodal = separate_content(content)
        assert "Hello world" in text
        assert "Second paragraph" in text
        assert multimodal == []

    def test_multimodal_only(self):
        content = [
            {"type": "image", "img_path": "/path/to/image.png"},
            {"type": "table", "table_body": "col1|col2"},
        ]
        text, multimodal = separate_content(content)
        assert text == ""
        assert len(multimodal) == 2
        assert multimodal[0]["type"] == "image"
        assert multimodal[1]["type"] == "table"

    def test_mixed_content(self):
        content = [
            {"type": "text", "text": "Introduction"},
            {"type": "image", "img_path": "/path/to/fig1.png"},
            {"type": "text", "text": "Discussion"},
            {"type": "table", "table_body": "data"},
            {"type": "equation", "text": "E=mc^2"},
        ]
        text, multimodal = separate_content(content)
        assert "Introduction" in text
        assert "Discussion" in text
        assert len(multimodal) == 3

    def test_whitespace_text_ignored(self):
        content = [
            {"type": "text", "text": "   "},
            {"type": "text", "text": "Valid text"},
            {"type": "text", "text": "\n\t"},
        ]
        text, multimodal = separate_content(content)
        assert "Valid text" in text
        assert "   " not in text.split("\n\n")

    def test_missing_type_defaults_to_text(self):
        content = [{"text": "no type field"}]
        text, multimodal = separate_content(content)
        assert "no type field" in text


# ── Image Encoding Tests ─────────────────────────────────────────


class TestEncodeImageToBase64:
    def test_valid_image(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = encode_image_to_base64(str(img))
        assert result != ""
        # Verify it's valid base64
        decoded = base64.b64decode(result)
        assert decoded.startswith(b"\x89PNG")

    def test_nonexistent_file(self):
        result = encode_image_to_base64("/nonexistent/image.png")
        assert result == ""

    def test_empty_file(self, tmp_path):
        img = tmp_path / "empty.png"
        img.write_bytes(b"")
        result = encode_image_to_base64(str(img))
        assert result == ""


# ── Image Validation Tests ───────────────────────────────────────


class TestValidateImageFile:
    def test_valid_image_file(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        assert validate_image_file(str(img)) is True

    def test_nonexistent_file(self):
        assert validate_image_file("/nonexistent/image.png") is False

    def test_invalid_extension(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"not an image")
        assert validate_image_file(str(f)) is False

    def test_file_too_large(self, tmp_path):
        img = tmp_path / "huge.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * (51 * 1024 * 1024))
        assert validate_image_file(str(img), max_size_mb=50) is False

    def test_symlink_blocked(self, tmp_path):
        real = tmp_path / "real.jpg"
        real.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        link = tmp_path / "link.jpg"
        link.symlink_to(real)
        assert validate_image_file(str(link)) is False

    def test_all_valid_extensions(self, tmp_path):
        extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"]
        for ext in extensions:
            img = tmp_path / f"test{ext}"
            img.write_bytes(b"\x00" * 100)
            assert validate_image_file(str(img)) is True, f"Failed for {ext}"


# ── Processor Type Mapping Tests ─────────────────────────────────


class TestGetProcessorForType:
    def test_image_type(self):
        processors = {"image": "img_proc", "table": "tbl_proc", "generic": "gen_proc"}
        assert get_processor_for_type(processors, "image") == "img_proc"

    def test_table_type(self):
        processors = {"image": "img_proc", "table": "tbl_proc", "generic": "gen_proc"}
        assert get_processor_for_type(processors, "table") == "tbl_proc"

    def test_equation_type(self):
        processors = {"equation": "eq_proc", "generic": "gen_proc"}
        assert get_processor_for_type(processors, "equation") == "eq_proc"

    def test_unknown_type_falls_back_to_generic(self):
        processors = {"generic": "gen_proc"}
        assert get_processor_for_type(processors, "audio") == "gen_proc"

    def test_missing_processor_returns_none(self):
        processors = {}
        assert get_processor_for_type(processors, "image") is None


class TestGetProcessorSupports:
    def test_image_supports(self):
        supports = get_processor_supports("image")
        assert isinstance(supports, list)
        assert len(supports) > 0
        assert any("image" in s.lower() or "visual" in s.lower() for s in supports)

    def test_table_supports(self):
        supports = get_processor_supports("table")
        assert isinstance(supports, list)
        assert any("table" in s.lower() for s in supports)

    def test_equation_supports(self):
        supports = get_processor_supports("equation")
        assert isinstance(supports, list)
        assert any("formula" in s.lower() or "math" in s.lower() for s in supports)

    def test_generic_supports(self):
        supports = get_processor_supports("generic")
        assert isinstance(supports, list)

    def test_unknown_type(self):
        supports = get_processor_supports("unknown_type")
        assert supports == ["Basic processing"]


# ── BatchProcessingResult Tests ──────────────────────────────────


class TestBatchProcessingResult:
    def test_success_rate_calculation(self):
        from raganything.batch_parser import BatchProcessingResult

        result = BatchProcessingResult(
            successful_files=["a.pdf", "b.pdf"],
            failed_files=["c.pdf"],
            total_files=3,
            processing_time=10.0,
            errors={"c.pdf": "parse error"},
            output_dir="/tmp/output",
        )
        assert result.success_rate == pytest.approx(66.67, abs=0.1)

    def test_success_rate_zero_files(self):
        from raganything.batch_parser import BatchProcessingResult

        result = BatchProcessingResult(
            successful_files=[],
            failed_files=[],
            total_files=0,
            processing_time=0.0,
            errors={},
            output_dir="/tmp/output",
        )
        assert result.success_rate == 0.0

    def test_summary_contains_info(self):
        from raganything.batch_parser import BatchProcessingResult

        result = BatchProcessingResult(
            successful_files=["a.pdf"],
            failed_files=["b.pdf"],
            total_files=2,
            processing_time=5.5,
            errors={"b.pdf": "error"},
            output_dir="/tmp/output",
        )
        summary = result.summary()
        assert "Total files: 2" in summary
        assert "Successful: 1" in summary
        assert "Failed: 1" in summary
        assert "5.50 seconds" in summary

    def test_dry_run_flag(self):
        from raganything.batch_parser import BatchProcessingResult

        result = BatchProcessingResult(
            successful_files=[],
            failed_files=[],
            total_files=0,
            processing_time=0.0,
            errors={},
            output_dir="/tmp/output",
            dry_run=True,
        )
        assert result.dry_run is True
        assert "Dry run: True" in result.summary()


# ── BatchParser Initialization Tests ─────────────────────────────


class TestBatchParserInit:
    def test_supported_extensions(self):
        from raganything.batch_parser import BatchParser

        bp = BatchParser(parser_type="mineru", skip_installation_check=True)
        exts = bp.get_supported_extensions()
        assert ".pdf" in exts
        assert ".png" in exts
        assert ".docx" in exts

    def test_invalid_parser_type(self):
        from raganything.batch_parser import BatchParser

        with pytest.raises(ValueError, match="Unsupported parser type"):
            BatchParser(parser_type="nonexistent", skip_installation_check=True)

    def test_filter_supported_files(self, tmp_path):
        from raganything.batch_parser import BatchParser

        # Create test files
        (tmp_path / "doc.pdf").write_bytes(b"pdf")
        (tmp_path / "img.png").write_bytes(b"png")
        (tmp_path / "data.csv").write_bytes(b"csv")
        (tmp_path / "readme.py").write_bytes(b"py")

        bp = BatchParser(parser_type="mineru", skip_installation_check=True)
        supported = bp.filter_supported_files([str(tmp_path)], recursive=False)
        
        supported_names = [Path(f).name for f in supported]
        assert "doc.pdf" in supported_names
        assert "img.png" in supported_names
        assert "readme.py" not in supported_names

    def test_filter_nonexistent_path(self):
        from raganything.batch_parser import BatchParser

        bp = BatchParser(parser_type="mineru", skip_installation_check=True)
        result = bp.filter_supported_files(["/nonexistent/path"])
        assert result == []
