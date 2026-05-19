"""Tests for _strip_thinking_tags in BaseModalProcessor (issue #159).

Reasoning models like DeepSeek-R1 and Qwen2.5-think wrap their chain-of-thought
in <think>…</think> blocks.  When JSON parsing fails, the raw response was
previously stored verbatim — polluting the knowledge graph with internal model
reasoning instead of actual content descriptions.  These tests verify that the
fallback path strips thinking tags before storing or returning the response.
"""

from raganything.modalprocessors import BaseModalProcessor


class TestStripThinkingTags:
    """Unit tests for BaseModalProcessor._strip_thinking_tags."""

    def test_strips_think_tags(self):
        raw = "<think>some reasoning here</think>final answer"
        assert BaseModalProcessor._strip_thinking_tags(raw) == "final answer"

    def test_strips_thinking_tags(self):
        raw = "<thinking>internal thought</thinking>real content"
        assert BaseModalProcessor._strip_thinking_tags(raw) == "real content"

    def test_strips_multiline_think_block(self):
        raw = "<think>\nline one\nline two\n</think>\nactual description"
        assert BaseModalProcessor._strip_thinking_tags(raw) == "actual description"

    def test_case_insensitive(self):
        raw = "<THINK>uppercase block</THINK>answer"
        assert BaseModalProcessor._strip_thinking_tags(raw) == "answer"

    def test_no_tags_unchanged(self):
        raw = "plain response without any tags"
        assert BaseModalProcessor._strip_thinking_tags(raw) == raw

    def test_empty_string(self):
        assert BaseModalProcessor._strip_thinking_tags("") == ""

    def test_only_think_tags_returns_empty(self):
        raw = "<think>nothing useful</think>"
        assert BaseModalProcessor._strip_thinking_tags(raw) == ""

    def test_multiple_think_blocks(self):
        raw = "<think>first</think>middle<think>second</think>end"
        assert BaseModalProcessor._strip_thinking_tags(raw) == "middleend"

    def test_nested_angle_brackets_in_content_preserved(self):
        """Content after think block that contains angle brackets must survive."""
        raw = "<think>reasoning</think>result with <b>HTML</b>"
        assert BaseModalProcessor._strip_thinking_tags(raw) == "result with <b>HTML</b>"


class ConcreteProcessor(BaseModalProcessor):
    """Minimal concrete subclass used to instantiate BaseModalProcessor."""

    def __init__(self):
        # Skip the full __init__ that requires a LightRAG instance
        pass

    async def process_multimodal_content(self, *args, **kwargs):
        pass


class TestParseResponseFallback:
    """Tests that parse fallback paths return cleaned (think-stripped) content."""

    THINK_RESPONSE = (
        "<think>\nLet me analyze this step by step...\n</think>\n"
        "This is the actual description of the image."
    )

    def setup_method(self):
        self.proc = ConcreteProcessor()

        # Patch _robust_json_parse to always raise ValueError so fallback fires
        def always_fail(response):
            raise ValueError("forced failure")

        self.proc._robust_json_parse = always_fail

    def test_image_fallback_strips_think(self):
        from raganything.modalprocessors import ImageModalProcessor

        proc = ConcreteProcessor()
        proc.__class__ = ImageModalProcessor
        proc._robust_json_parse = lambda r: (_ for _ in ()).throw(ValueError("forced"))

        caption, entity = proc._parse_response(self.THINK_RESPONSE)
        assert "<think>" not in caption
        assert "<think>" not in entity["summary"]
        assert "actual description" in caption

    def test_table_fallback_strips_think(self):
        from raganything.modalprocessors import TableModalProcessor

        proc = ConcreteProcessor()
        proc.__class__ = TableModalProcessor
        proc._robust_json_parse = lambda r: (_ for _ in ()).throw(ValueError("forced"))

        caption, entity = proc._parse_table_response(self.THINK_RESPONSE)
        assert "<think>" not in caption
        assert "<think>" not in entity["summary"]
        assert "actual description" in caption

    def test_equation_fallback_strips_think(self):
        from raganything.modalprocessors import EquationModalProcessor

        proc = ConcreteProcessor()
        proc.__class__ = EquationModalProcessor
        proc._robust_json_parse = lambda r: (_ for _ in ()).throw(ValueError("forced"))

        caption, entity = proc._parse_equation_response(self.THINK_RESPONSE)
        assert "<think>" not in caption
        assert "<think>" not in entity["summary"]

    def test_generic_fallback_strips_think(self):
        from raganything.modalprocessors import GenericModalProcessor

        proc = ConcreteProcessor()
        proc.__class__ = GenericModalProcessor
        proc._robust_json_parse = lambda r: (_ for _ in ()).throw(ValueError("forced"))

        caption, entity = proc._parse_generic_response(self.THINK_RESPONSE)
        assert "<think>" not in caption
        assert "<think>" not in entity["summary"]
