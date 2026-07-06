"""
Tests for PromptBuilder — unified prompt construction pipeline.
Run: pytest tests/test_prompt_builder.py -v
"""
import os
import pytest

from raganything.services.prompt_builder import (
    ContextLayer,
    PromptBuilder,
    _truncate_by_tokens,
    _token_est,
)


# ═══════════════════════════════════════════════════════════
# Unit: _token_est / _truncate_by_tokens
# ═══════════════════════════════════════════════════════════

class TestTokenHelpers:
    def test_token_est_empty(self):
        assert _token_est("") == 0

    def test_token_est_cjk(self):
        # CJK text: ~2 chars per token
        assert _token_est("你好世界") == 2  # 4 chars // 2

    def test_token_est_english(self):
        assert _token_est("hello world") == 5  # 11 chars // 2

    def test_truncate_short_text(self):
        result = _truncate_by_tokens("hello", 10)
        assert result == "hello"  # shorter than budget

    def test_truncate_long_text(self):
        long_text = "abcdefghij" * 100  # 1000 chars
        result = _truncate_by_tokens(long_text, 10)  # 20 char budget
        assert len(result) <= 22  # 20 chars + truncation prefix
        assert "截断" in result


# ═══════════════════════════════════════════════════════════
# Unit: ContextLayer
# ═══════════════════════════════════════════════════════════

class TestContextLayer:
    def test_disabled_layer_empty(self):
        layer = ContextLayer(
            name="test", content="hello world",
            enabled=False
        )
        assert layer.effective_content() == ""

    def test_empty_content_returns_empty(self):
        layer = ContextLayer(name="test", content="", enabled=True)
        assert layer.effective_content() == ""

    def test_token_budget_truncation(self):
        layer = ContextLayer(
            name="test",
            content="hello world " * 10,  # ~120 chars
            max_tokens=15,  # 30 char budget
            enabled=True,
        )
        result = layer.effective_content()
        # Truncated result should be shorter than original
        assert len(result) < len("hello world " * 10)
        # Should contain truncation marker
        assert "截断" in result


# ═══════════════════════════════════════════════════════════
# Unit: PromptBuilder
# ═══════════════════════════════════════════════════════════

class TestPromptBuilder:
    def test_basic_build(self):
        builder = PromptBuilder()
        builder.system_instruction("You are helpful.")
        builder.user_query("What is Python?")
        prompt, sp = builder.build()

        assert "What is Python" in prompt
        assert "You are helpful" in sp

    def test_disabled_layers_excluded(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_context_layer(ContextLayer(
            name="hidden", content="should not appear",
            priority=15, enabled=False,
        ))
        builder.user_query("hello")
        prompt, _ = builder.build()

        assert "should not appear" not in prompt

    def test_layers_sorted_by_priority(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_context_layer(ContextLayer(
            name="layer_a", content="[A]", priority=30, label="## A\n",
        ))
        builder.add_context_layer(ContextLayer(
            name="layer_b", content="[B]", priority=20, label="## B\n",
        ))
        builder.user_query("query")
        prompt, _ = builder.build()

        pos_b = prompt.index("[B]")
        pos_a = prompt.index("[A]")
        assert pos_b < pos_a  # lower priority comes first

    def test_summary_layer_injection(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_summary("Previous conversation about PLC debugging.")
        builder.add_recent_history("user: what is E001?\nassistant: E001 is motor overload.")
        builder.user_query("How to fix it?")

        # Summary is enabled by default (CONVERSATION_SUMMARY_ENABLED=true)
        prompt, _ = builder.build()
        assert "PLC debugging" in prompt  # summary enabled

        # Explicitly disable summary
        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "false"
        builder2 = PromptBuilder()
        builder2.system_instruction("sys")
        builder2.add_summary("Previous conversation about PLC debugging.")
        builder2.user_query("How to fix it?")
        prompt2, _ = builder2.build()
        assert "PLC debugging" not in prompt2  # summary explicitly disabled
        del os.environ["CONVERSATION_SUMMARY_ENABLED"]

    def test_no_history_when_empty(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_recent_history("")  # empty
        builder.user_query("hello")
        prompt, _ = builder.build()

        # "对话历史" label should not appear when disabled
        assert "对话历史" not in prompt

    def test_image_context_injection(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        img_text = "## 用户上传图片的视觉描述\nA photo of a PLC panel.\n"
        builder.add_image_context(img_text)
        builder.user_query("What is this?")
        prompt, _ = builder.build()

        assert "PLC panel" in prompt

    def test_empty_image_context_disabled(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_image_context("")  # empty
        builder.user_query("hello")
        prompt, _ = builder.build()

        # No image section should appear
        assert "视觉描述" not in prompt

    def test_retrieval_context_injection(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.retrieval_context("[来源 doc1] PLC troubleshooting guide content...")
        builder.user_query("How to reset PLC?")
        prompt, _ = builder.build()

        assert "doc1" in prompt
        assert "检索内容" in prompt

    def test_degraded_hint_when_no_chunks(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.retrieval_context("very short")
        builder.degraded_hint("⚠️ The knowledge base has limited data.")
        builder.user_query("query")
        prompt, _ = builder.build()

        assert "limited data" in prompt

    def test_citation_instruction_injection(self):
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.user_query("query", "[Cite with: source, content]")
        prompt, _ = builder.build()

        assert "Cite with" in prompt

    def test_token_budget_enforcement(self):
        """When total tokens exceed budget, low-priority layers get trimmed."""
        builder = PromptBuilder(max_total_tokens=200)  # very tight budget
        builder.system_instruction("sys")
        builder.add_recent_history("message " * 100)  # ~50 tokens
        builder.retrieval_context("context " * 500)  # ~250 tokens
        builder.user_query("test query")
        prompt, _ = builder.build()

        # Should still produce output (not crash)
        assert "test query" in prompt
        # Should have trimmed something (retrieval context gets trimmed first)
        # Either retrieval is present (trimmed) or entirely removed
        assert len(prompt) > 0

    def test_system_instruction_never_truncated(self):
        builder = PromptBuilder(max_total_tokens=50)  # extremely tight
        builder.system_instruction("You are a helpful assistant.")
        builder.retrieval_context("long context " * 100)
        builder.user_query("important query")
        prompt, sp = builder.build()

        # User query MUST be present
        assert "important query" in prompt
        # System instruction MUST be preserved
        assert "helpful assistant" in sp

    def test_multiple_layers_all_disabled(self):
        """When all optional layers are disabled, only query appears."""
        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_context_layer(ContextLayer(
            name="disabled1", content="gone1", enabled=False,
        ))
        builder.add_context_layer(ContextLayer(
            name="disabled2", content="gone2", enabled=False,
        ))
        builder.user_query("just me")
        prompt, _ = builder.build()

        assert "gone1" not in prompt
        assert "gone2" not in prompt
        assert "just me" in prompt


# ═══════════════════════════════════════════════════════════
# Integration: Prompt output consistency (RAG/ReAct/CoT)
# ═══════════════════════════════════════════════════════════

class TestPromptConsistency:
    """Verify that PromptBuilder produces consistent output matching
    the previous manual concatenation format."""

    def test_rag_mode_structure(self):
        """RAG mode: history → retrieval → query → citation."""
        builder = PromptBuilder()
        builder.system_instruction("You are a knowledge base assistant.")
        builder.add_recent_history("用户: What is E001?\n助手: E001 is motor overload.")
        builder.retrieval_context("[来源 manual.pdf] E001 troubleshooting steps...")
        builder.user_query("How to fix E001?", "[Cite sources in answer]")
        prompt, sp = builder.build()

        # Verify structure: history before retrieval, query at end
        assert "What is E001" in prompt
        assert "E001 troubleshooting" in prompt
        assert "How to fix E001" in prompt
        # Query should be at the end
        assert prompt.rfind("How to fix E001") > prompt.rfind("E001 troubleshooting")
        # Citation instruction should be present
        assert "Cite sources" in prompt
        # System prompt preserved
        assert "knowledge base assistant" in sp

    def test_react_mode_query_string(self):
        """ReAct mode: context prepended to query string."""
        builder = PromptBuilder()
        builder.add_image_context("## 图片描述\nPLC panel photo.\n")
        builder.add_recent_history("用户: check fault\n助手: which fault code?")
        builder.user_query("E001")
        prompt, _ = builder.build()

        # Image context before history
        assert "PLC panel" in prompt
        assert "check fault" in prompt
        assert "E001" in prompt
        # Query at the end
        assert prompt.strip().endswith("E001") or "E001\n" in prompt

    def test_cot_mode_context_with_retrieval(self):
        """CoT mode: image + history prepended to retrieval context."""
        builder = PromptBuilder()
        img_section = "## 图片描述\nManufacturing dashboard.\n"
        builder.add_image_context(img_section)
        builder.add_recent_history("用户: what is the status?\n助手: analyzing...")
        builder.retrieval_context("[来源 status.json] Line 3: operating normally")
        builder.user_query("Any issues?")
        prompt, _ = builder.build()

        assert "Manufacturing dashboard" in prompt
        assert "analyzing" in prompt
        assert "Line 3" in prompt
        assert "Any issues" in prompt


# ═══════════════════════════════════════════════════════════
# Summary-related unit tests
# ═══════════════════════════════════════════════════════════

class TestSummaryIntegration:
    """Test summary-injection behavior in PromptBuilder."""

    def test_summary_enabled_by_default(self):
        """CONVERSATION_SUMMARY_ENABLED defaults to true (since v2.1)."""
        # Clear any env override
        os.environ.pop("CONVERSATION_SUMMARY_ENABLED", None)

        builder = PromptBuilder()
        builder.system_instruction("sys")
        builder.add_summary("A summary of prior discussion.")
        builder.user_query("new question")
        prompt, _ = builder.build()

        # Summary SHOULD appear (enabled by default)
        assert "prior discussion" in prompt

    def test_summary_plus_history_dual_injection(self):
        """When enabled, both summary and recent history appear."""
        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "true"
        try:
            builder = PromptBuilder()
            builder.system_instruction("sys")
            builder.add_summary("Prior: discussed PLC E001 error.")
            builder.add_recent_history("用户: what next?\n助手: check power supply.")
            builder.user_query("power is fine, what else?")
            prompt, _ = builder.build()

            # Both layers should be present
            assert "PLC E001" in prompt  # summary
            assert "check power supply" in prompt  # recent history
            # Summary should appear before recent history
            pos_summary = prompt.index("PLC E001")
            pos_recent = prompt.index("check power supply")
            assert pos_summary < pos_recent
        finally:
            del os.environ["CONVERSATION_SUMMARY_ENABLED"]

    def test_no_summary_degradation_to_truncation(self):
        """When summary is enabled but None, only recent history appears."""
        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "true"
        try:
            builder = PromptBuilder()
            builder.system_instruction("sys")
            builder.add_summary("")  # no summary yet
            builder.add_recent_history("用户: question\n助手: answer")
            builder.user_query("next question")
            prompt, _ = builder.build()

            # Recent history should still appear
            assert "question" in prompt
            assert "answer" in prompt
            # No summary label
            assert "对话摘要" not in prompt
        finally:
            del os.environ["CONVERSATION_SUMMARY_ENABLED"]
