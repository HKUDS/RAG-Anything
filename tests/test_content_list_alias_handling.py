import importlib.util
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def install_import_stubs():
    lightrag_module = types.ModuleType("lightrag")
    lightrag_utils = types.ModuleType("lightrag.utils")
    lightrag_utils.logger = FakeLogger()
    lightrag_utils.compute_mdhash_id = lambda value, prefix="": f"{prefix}test"

    raganything_pkg = types.ModuleType("raganything")
    raganything_pkg.__path__ = [str(PROJECT_ROOT / "raganything")]

    raganything_base = types.ModuleType("raganything.base")

    raganything_parser = types.ModuleType("raganything.parser")
    raganything_parser.MineruParser = object
    raganything_parser.MineruExecutionError = RuntimeError
    raganything_parser.get_parser = lambda *args, **kwargs: None

    sys.modules.setdefault("lightrag", lightrag_module)
    sys.modules.setdefault("lightrag.utils", lightrag_utils)
    sys.modules.setdefault("raganything", raganything_pkg)
    sys.modules.setdefault("raganything.base", raganything_base)
    sys.modules.setdefault("raganything.parser", raganything_parser)
    raganything_base.DocStatus = types.SimpleNamespace(
        READY="ready",
        HANDLING="handling",
        PENDING="pending",
        PROCESSING="processing",
        PROCESSED="processed",
        FAILED="failed",
    )


def load_project_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


install_import_stubs()
utils_module = load_project_module(
    "raganything.utils", PROJECT_ROOT / "raganything" / "utils.py"
)
processor_module = load_project_module(
    "raganything.processor", PROJECT_ROOT / "raganything" / "processor.py"
)

ProcessorMixin = processor_module.ProcessorMixin
format_table_body = utils_module.format_table_body
get_equation_text_and_format = utils_module.get_equation_text_and_format
get_table_body = utils_module.get_table_body
normalize_caption_list = utils_module.normalize_caption_list
separate_content = utils_module.separate_content
build_content_list_from_text = utils_module.build_content_list_from_text
build_content_list_from_text_file = utils_module.build_content_list_from_text_file
extract_section_path_from_content_list = (
    utils_module.extract_section_path_from_content_list
)
extract_neighbor_text_from_content_list = (
    utils_module.extract_neighbor_text_from_content_list
)


class ContentListAliasHandlingTests(unittest.TestCase):
    def test_separate_content_ignores_null_text_values(self):
        text, multimodal = separate_content(
            [
                {"type": "text", "text": None},
                {"type": "text", "text": "kept"},
            ]
        )

        self.assertEqual(text, "kept")
        self.assertEqual(multimodal, [])

    def test_separate_content_preserves_original_content_list_index(self):
        content = [
            {"type": "text", "text": "Before"},
            {"type": "image", "img_path": "/tmp/figure.png"},
            {"type": "text", "text": "After"},
            {"type": "table", "table_body": "| A | B |"},
        ]

        _, multimodal = separate_content(content)

        self.assertEqual([item["_content_list_index"] for item in multimodal], [1, 3])
        self.assertNotIn("_content_list_index", content[1])

    def test_table_alias_and_string_caption_feed_chunk_template(self):
        processor = ProcessorMixin()
        chunk = processor._apply_chunk_template(
            "table",
            {
                "table_data": [["Method", "Score"], ["RAGAnything", "95.2"]],
                "table_caption": "Performance table",
                "table_footnote": "Synthetic example",
            },
            "The table compares scores.",
        )

        self.assertEqual(get_table_body({"table_data": [["A", "B"]]}), [["A", "B"]])
        self.assertEqual(
            format_table_body([["A", "B"], ["C", "D"]]),
            "| A | B |\n| --- | --- |\n| C | D |",
        )
        self.assertEqual(format_table_body("| A | B |"), "| A | B |")
        self.assertEqual(
            normalize_caption_list("Performance table"), ["Performance table"]
        )
        self.assertIn("| Method | Score |", chunk)
        self.assertIn("| RAGAnything | 95.2 |", chunk)
        self.assertIn("Performance table", chunk)
        self.assertNotIn("P, e, r, f", chunk)
        self.assertIn("Synthetic example", chunk)

    def test_equation_latex_alias_is_not_dropped_from_chunk_template(self):
        processor = ProcessorMixin()

        text_item = {"text": "E = mc^2", "text_format": "latex"}
        equation_text, equation_format = get_equation_text_and_format(text_item)
        self.assertEqual(equation_text, "E = mc^2")
        self.assertEqual(equation_format, "latex")

        latex_only_item = {"latex": "E = mc^2"}
        equation_text, equation_format = get_equation_text_and_format(latex_only_item)
        self.assertEqual(equation_text, "E = mc^2")
        self.assertEqual(equation_format, "latex")

        chunk = processor._apply_chunk_template(
            "equation", latex_only_item, "A physics equation."
        )
        self.assertIn("E = mc^2", chunk)
        self.assertIn("Format: latex", chunk)
        self.assertIn("A physics equation.", chunk)

        equation_alias_item = {"equation": "x^2 + y^2 = 1"}
        equation_text, _ = get_equation_text_and_format(equation_alias_item)
        self.assertEqual(equation_text, "x^2 + y^2 = 1")

    def test_image_items_get_section_path_and_neighbor_text_metadata(self):
        content = [
            {"type": "text", "text": "1 Introduction", "text_level": 1},
            {"type": "text", "text": "background paragraph"},
            {"type": "text", "text": "2 Method", "text_level": 1},
            {"type": "text", "text": "2.1 Setup", "text_level": 2},
            {"type": "text", "text": "setup details before image"},
            {
                "type": "image",
                "img_path": "/tmp/figure_30_1.png",
                "image_caption": ["Figure 30.1 Ablation curve"],
            },
            {"type": "text", "text": "discussion after image"},
        ]

        _, multimodal = separate_content(content)
        image_item = multimodal[0]

        self.assertEqual(
            image_item["_section_path"],
            "2 Method > 2.1 Setup",
        )
        self.assertIn("setup details before image", image_item["_neighbor_text"])
        self.assertIn("discussion after image", image_item["_neighbor_text"])

    def test_image_chunk_template_includes_section_and_neighbor_text(self):
        processor = ProcessorMixin()
        chunk = processor._apply_chunk_template(
            "image",
            {
                "img_path": "/tmp/figure_30_1.png",
                "image_caption": "Figure 30.1 Ablation curve",
                "image_footnote": "Synthetic sample",
                "_section_path": "2 Method > 2.1 Setup",
                "_neighbor_text": "setup details before image discussion after image",
            },
            "A line chart comparing model variants.",
        )

        self.assertIn("Section Path: 2 Method > 2.1 Setup", chunk)
        self.assertIn(
            "Neighbor Text: setup details before image discussion after image", chunk
        )
        self.assertIn("A line chart comparing model variants.", chunk)

    def test_section_and_neighbor_helpers_handle_invalid_indices(self):
        content = [{"type": "text", "text": "1 Intro", "text_level": 1}]
        self.assertEqual(extract_section_path_from_content_list(content, -1), "")
        self.assertEqual(extract_neighbor_text_from_content_list(content, 99), "")


class TestBuildContentListFromText(unittest.TestCase):
    """#331: .txt/.md are built directly into a content list, no PDF round trip."""

    def test_paragraphs_split_on_blank_lines(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird."
        content = build_content_list_from_text(text)

        self.assertEqual(len(content), 3)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[0]["text"], "First paragraph.")
        self.assertEqual(content[1]["text"], "Second paragraph.")
        self.assertEqual(content[2]["text"], "Third.")
        # every block carries the synthetic page index
        for block in content:
            self.assertEqual(block["page_idx"], 0)

    def test_blank_and_whitespace_only_paragraphs_ignored(self):
        text = "Para one.\n\n   \n\nPara two.\n\n\n\nPara three."
        content = build_content_list_from_text(text)

        self.assertEqual(
            [c["text"] for c in content], ["Para one.", "Para two.", "Para three."]
        )

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(build_content_list_from_text(""), [])
        self.assertEqual(build_content_list_from_text("\n\n  \n"), [])

    def test_cjk_text_preserved(self):
        text = "第一段中文内容。\n\n第二段中文内容。"
        content = build_content_list_from_text(text)

        self.assertEqual(len(content), 2)
        self.assertEqual(content[0]["text"], "第一段中文内容。")
        self.assertEqual(content[1]["text"], "第二段中文内容。")

    def test_custom_page_idx_stamped(self):
        content = build_content_list_from_text("Hello", page_idx=7)
        self.assertEqual(content[0]["page_idx"], 7)

    def test_read_from_file_utf8(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as f:
            f.write("# Title\n\nBody paragraph with 中文。")
            path = f.name
        try:
            content = build_content_list_from_text_file(path)
        finally:
            import os

            os.unlink(path)

        self.assertEqual(len(content), 2)
        self.assertEqual(content[0]["text"], "# Title")
        self.assertEqual(content[1]["text"], "Body paragraph with 中文。")

    def test_read_gbk_encoded_file(self):
        # GBK is a common encoding for Chinese text files on Windows; the
        # reader must fall back to it when UTF-8 decoding fails (matching the
        # ReportLab text-to-PDF path).
        import tempfile

        text = "第一段中文。\n\n第二段中文。"
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".txt", delete=False
        ) as f:
            f.write(text.encode("gbk"))
            path = f.name
        try:
            content = build_content_list_from_text_file(path)
        finally:
            import os

            os.unlink(path)

        self.assertEqual(len(content), 2)
        self.assertEqual(content[0]["text"], "第一段中文。")
        self.assertEqual(content[1]["text"], "第二段中文。")


if __name__ == "__main__":
    unittest.main()
