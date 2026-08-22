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
extract_section_path_from_content_list = (
    utils_module.extract_section_path_from_content_list
)
extract_neighbor_text_from_content_list = (
    utils_module.extract_neighbor_text_from_content_list
)


class ContentListAliasHandlingTests(unittest.TestCase):
    def test_separate_content_ignores_null_text_values(self):
        text, page_texts, multimodal = separate_content(
            [
                {"type": "text", "text": None},
                {"type": "text", "text": "kept"},
            ]
        )

        self.assertEqual(text, "kept")
        self.assertEqual(page_texts, ["kept"])
        self.assertEqual(multimodal, [])

    def test_separate_content_preserves_original_content_list_index(self):
        content = [
            {"type": "text", "text": "Before"},
            {"type": "image", "img_path": "/tmp/figure.png"},
            {"type": "text", "text": "After"},
            {"type": "table", "table_body": "| A | B |"},
        ]

        _, _, multimodal = separate_content(content)

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

        _, _, multimodal = separate_content(content)
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


class SeparateContentPageGroupingTests(unittest.TestCase):
    """#330: text must retain page boundaries through chunking.

    ``separate_content`` returns per-page text runs so that page provenance
    survives downstream token-chunking. Very short consecutive pages are merged
    into a single run to avoid tiny, low-context chunks, but a run never mixes
    non-adjacent pages.
    """

    def test_short_consecutive_pages_merged_into_one_run(self):
        content = [
            {"type": "text", "text": "tiny page A", "page_idx": 0},
            {"type": "text", "text": "tiny page B", "page_idx": 1},
        ]
        _, page_texts, _ = separate_content(content)

        self.assertEqual(len(page_texts), 1)
        self.assertIn("tiny page A", page_texts[0])
        self.assertIn("tiny page B", page_texts[0])

    def test_big_page_starts_its_own_run(self):
        content = [
            {"type": "text", "text": "A" * 600, "page_idx": 0},
            {"type": "text", "text": "B" * 600, "page_idx": 1},
        ]
        _, page_texts, _ = separate_content(content)

        self.assertEqual(len(page_texts), 2)
        self.assertIn("A" * 600, page_texts[0])
        self.assertNotIn("B", page_texts[0])
        self.assertIn("B" * 600, page_texts[1])

    def test_runs_are_contiguous_page_ranges(self):
        # A large page is its own run; the following short page merges with the
        # next large page rather than bleeding into page 0's run.
        content = [
            {"type": "text", "text": "P0" * 300, "page_idx": 0},
            {"type": "text", "text": "P1 short", "page_idx": 1},
            {"type": "text", "text": "P2" * 300, "page_idx": 2},
        ]
        _, page_texts, _ = separate_content(content)

        self.assertEqual(len(page_texts), 2)
        self.assertIn("P1 short", page_texts[1])
        self.assertNotIn("P1 short", page_texts[0])
        # page 1 and 2 share a run; page 0 is alone
        self.assertNotIn("P2", page_texts[0])

    def test_flat_text_is_concatenation_of_page_runs(self):
        content = [
            {"type": "text", "text": "alpha", "page_idx": 0},
            {"type": "text", "text": "beta", "page_idx": 1},
        ]
        text, page_texts, _ = separate_content(content)

        self.assertEqual(text, "alpha\n\nbeta")
        self.assertEqual("\n\n".join(page_texts), text)

    def test_text_without_page_idx_falls_back_to_single_bucket(self):
        content = [
            {"type": "text", "text": "no page A"},
            {"type": "text", "text": "no page B"},
        ]
        _, page_texts, _ = separate_content(content)

        self.assertEqual(len(page_texts), 1)
        self.assertIn("no page A", page_texts[0])
        self.assertIn("no page B", page_texts[0])


if __name__ == "__main__":
    unittest.main()
