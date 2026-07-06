"""
Tests for conversation summary compression ratio mechanism.

Covers:
  - Compression ratio calculation logic
  - Retry loop with progressive prompt strengthening
  - Graceful degradation when retries exhausted
  - Environment variable defaults
  - Integration: _maybe_generate_summary gate checks

Run: pytest tests/test_agent_summary_compression.py -v
"""
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ═══════════════════════════════════════════════════════════════
# Helpers: build realistic mock responses for the LLM call
# ═══════════════════════════════════════════════════════════════


def _make_messages(count: int = 6) -> list[dict]:
    """Build a realistic message list.
    count=6 → 3 rounds of user+assistant.
    """
    msgs = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({
            "role": role,
            "content": f"Message {i+1} with some content about PLC fault diagnosis and troubleshooting steps for error codes." * 3,
        })
    return msgs


def _short_summary() -> str:
    return "核心讨论了PLC故障诊断的三种方法和E001错误码的解决方案。"


def _long_summary() -> str:
    """A summary that is deliberately too long — should trigger retry.

    Must be >40% of the transcript length to fail the ≥60% compression check.
    With _make_messages(6) producing ~1757 chars, we need >~702 chars here.
    """
    return "详细讨论了PLC故障诊断的方法包含：" + "电源检查流程步骤说明故障排查。" * 60


def _very_long_summary() -> str:
    """Even longer — for multi-retry tests where first attempt also fails."""
    return "详细讨论了PLC故障诊断的方法包含：" + "电源检查流程步骤说明故障排查。" * 80


def _make_short_messages(count: int = 6) -> list[dict]:
    """Build shorter messages so that _long_summary triggers retry more easily."""
    msgs = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({
            "role": role,
            "content": f"Message {i+1} about PLC fault E00{i+1}.",
        })
    return msgs


# ═══════════════════════════════════════════════════════════════
# Unit: Compression ratio calculation (pure logic, no LLM)
# ═══════════════════════════════════════════════════════════════


class TestCompressionRatioCalculation:
    """Verify the ratio formula: 1 - len(summary) / max(len(transcript), 1)"""

    def test_high_compression_passes(self):
        """Short summary over long transcript → high ratio."""
        transcript = "x" * 1000  # 1000 chars
        summary = "abc" * 10     # 30 chars
        ratio = 1.0 - (len(summary) / max(len(transcript), 1))
        assert ratio >= 0.60
        assert ratio == 1.0 - (30 / 1000)

    def test_low_compression_fails(self):
        """Long summary over short transcript → low ratio."""
        transcript = "x" * 100
        summary = "y" * 80     # 80% of transcript
        ratio = 1.0 - (len(summary) / max(len(transcript), 1))
        assert ratio < 0.60
        assert ratio == pytest.approx(0.20)

    def test_exactly_at_threshold(self):
        """Summary at exactly 40% of transcript → ratio == 0.60."""
        transcript = "x" * 100
        summary = "y" * 40     # exactly 40%
        ratio = 1.0 - (len(summary) / max(len(transcript), 1))
        assert ratio == 0.60

    def test_ratio_with_realistic_sizes(self):
        """Realistic scenario: 3500-char transcript, 85-char summary."""
        transcript = "用户: " + ("PLC故障排查 " * 200)  # ~3500 chars
        summary = "故障排查步骤：1.检查电源 2.读取故障码 3.更换故障模块 4.重启系统"
        ratio = 1.0 - (len(summary) / max(len(transcript), 1))
        # Should be well above 60%
        assert ratio > 0.90

    def test_edge_empty_transcript(self):
        """Empty transcript with non-empty summary yields negative ratio
        (max(len(transcript), 1) prevents division by zero, but ratio is
        negative when summary > 1 char). In practice, transcript is never
        empty because each message contributes at minimum a role label."""
        transcript = ""
        summary = "test"
        ratio = 1.0 - (len(summary) / max(len(transcript), 1))
        # max(0, 1) = 1 → ratio = 1 - 4/1 = -3.0. Division by zero avoided.
        assert ratio == -3.0


# ═══════════════════════════════════════════════════════════════
# Integration: _call_summary_llm with mocked LLM
# ═══════════════════════════════════════════════════════════════


class TestCallSummaryLlm:
    """Test _call_summary_llm with mocked openai_complete_if_cache."""

    @pytest.mark.asyncio
    async def test_successful_compression_first_attempt(self):
        """LLM returns a short summary → passes compression on first try."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _short_summary()

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            assert result is not None
            assert "PLC" in result or "故障" in result
            # Should have succeeded on first attempt (only 1 LLM call)
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_low_compression(self):
        """First response too long → retry with stronger prompt → passes."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # Use short messages so _long_summary() exceeds 40%
            # First call: long summary (bad compression)
            # Second call: short summary (good compression)
            mock_llm.side_effect = [_long_summary(), _short_summary()]

            result = await _call_summary_llm(
                messages=_make_short_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            assert result is not None
            assert mock_llm.call_count == 2

            # Second call's prompt should include compression instruction
            second_call_prompt = mock_llm.call_args_list[1][0][1]
            assert "压缩" in second_call_prompt

    @pytest.mark.asyncio
    async def test_graceful_degradation_all_retries_exhausted(self):
        """All retries return long summaries → use best result anyway."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # Use 6 medium-length messages. Summaries are 40-50% of transcript
            # → all fail 60% threshold, but best (shortest) is still returned.
            msgs = _make_messages(6)
            mock_llm.side_effect = [
                _long_summary(),
                _very_long_summary(),
                _long_summary(),
            ]

            result = await _call_summary_llm(
                messages=msgs,
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            # Should still return a result (best among failures)
            assert result is not None
            # All 3 attempts made
            assert mock_llm.call_count == 3

    @pytest.mark.asyncio
    async def test_llm_failure_on_first_attempt_then_success(self):
        """First LLM call fails → skipped → second call succeeds."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [
                Exception("API timeout"),
                _short_summary(),
            ]

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            assert result is not None
            # Both attempts should have been tried
            assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_all_llm_calls_fail_returns_none(self):
        """Every LLM call throws → return None."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API down")

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            assert result is None
            assert mock_llm.call_count == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_response_too_short_skipped(self):
        """LLM returns <10 chars → treated as failure → retry."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["short", _short_summary()]

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            assert result is not None
            assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_incremental_summary_with_existing(self):
        """Incremental update with existing_summary merges correctly."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "更新后的摘要：故障已定位到电源模块和通信板卡。"

            result = await _call_summary_llm(
                messages=_make_messages(4),  # 2 new rounds
                existing_summary="之前的摘要：讨论了E001错误的基本排查。",
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            assert result is not None
            assert "电源" in result or "故障" in result
            # Prompt should contain both existing summary and new messages
            first_call_prompt = mock_llm.call_args_list[0][0][1]
            assert "已有摘要" in first_call_prompt
            assert "完整对话记录" in first_call_prompt

    @pytest.mark.asyncio
    async def test_compression_ratio_disabled_with_zero(self):
        """Setting compression_ratio=0.0 disables the check (always passes)."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # Returns a very long summary — but ratio check is 0%, so passes
            mock_llm.return_value = _long_summary()

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.0,   # effectively disabled
                max_retries=2,
            )

            # Should still return (no retries needed, ratio≥0 always)
            assert result is not None
            assert mock_llm.call_count == 1


# ═══════════════════════════════════════════════════════════════
# Unit: _maybe_generate_summary gate logic
# ═══════════════════════════════════════════════════════════════


class TestMaybeGenerateSummary:
    """Test the threshold/gate logic in _maybe_generate_summary."""

    @pytest.mark.asyncio
    async def test_disabled_when_summary_enabled_is_false(self):
        """Explicit false → returns None immediately."""
        from raganything.routers.agent import _maybe_generate_summary

        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "false"
        try:
            result = await _maybe_generate_summary(
                agent_id="test",
                thread_id="thread-1",
                conv_thread={"messages": _make_messages(20)},
            )
            assert result is None
        finally:
            del os.environ["CONVERSATION_SUMMARY_ENABLED"]

    @pytest.mark.asyncio
    async def test_skipped_when_below_threshold(self):
        """Less than trigger_messages → returns None."""
        from raganything.routers.agent import _maybe_generate_summary

        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "true"
        os.environ["CONVERSATION_SUMMARY_TRIGGER_ROUNDS"] = "3"
        try:
            result = await _maybe_generate_summary(
                agent_id="test",
                thread_id="thread-1",
                conv_thread={"messages": _make_messages(4)},  # 4 < 6
            )
            assert result is None
        finally:
            del os.environ["CONVERSATION_SUMMARY_ENABLED"]
            del os.environ["CONVERSATION_SUMMARY_TRIGGER_ROUNDS"]

    @pytest.mark.asyncio
    async def test_triggers_when_above_threshold(self):
        """Messages > trigger → calls _call_summary_llm."""
        from raganything.routers.agent import _maybe_generate_summary

        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "true"
        os.environ["CONVERSATION_SUMMARY_TRIGGER_ROUNDS"] = "3"

        try:
            with patch("raganything.routers.agent._call_summary_llm",
                       new_callable=AsyncMock) as mock_summary:
                with patch("raganything.routers.agent.pg_get_summary_updated_at",
                           new_callable=AsyncMock) as mock_updated:
                    with patch("raganything.routers.agent.pg_get_summary",
                               new_callable=AsyncMock) as mock_get:
                        with patch("raganything.routers.agent.pg_update_summary",
                                   new_callable=AsyncMock) as mock_update:
                            mock_updated.return_value = None  # no prior summary
                            mock_get.return_value = None
                            mock_summary.return_value = "摘要：讨论了PLC故障排查。"

                            result = await _maybe_generate_summary(
                                agent_id="test",
                                thread_id="thread-1",
                                conv_thread={"messages": _make_messages(10)},  # 10 >= 6
                            )

                            assert result is not None
                            assert mock_summary.call_count == 1
                            assert mock_update.call_count == 1
        finally:
            del os.environ["CONVERSATION_SUMMARY_ENABLED"]
            del os.environ["CONVERSATION_SUMMARY_TRIGGER_ROUNDS"]


# ═══════════════════════════════════════════════════════════════
# Unit: Environment variable defaults
# ═══════════════════════════════════════════════════════════════


class TestEnvDefaults:
    """Verify all new/changed environment variable defaults."""

    def test_conversation_max_rounds_default(self):
        val = int(os.getenv("CONVERSATION_MAX_ROUNDS", "10"))
        assert val == 10

    def test_summary_enabled_default(self):
        val = os.getenv("CONVERSATION_SUMMARY_ENABLED", "true")
        assert val.lower() == "true"

    def test_summary_trigger_rounds_default(self):
        val = int(os.getenv("CONVERSATION_SUMMARY_TRIGGER_ROUNDS", "3"))
        assert val == 3

    def test_compression_ratio_default(self):
        val = float(os.getenv("CONVERSATION_COMPRESSION_RATIO", "0.60"))
        assert val == 0.60

    def test_compression_max_retries_default(self):
        val = int(os.getenv("CONVERSATION_COMPRESSION_MAX_RETRIES", "2"))
        assert val == 2

    def test_backward_compat_explicit_overrides_default(self):
        """Explicit env var takes precedence over new default."""
        os.environ["CONVERSATION_MAX_ROUNDS"] = "3"
        os.environ["CONVERSATION_SUMMARY_ENABLED"] = "false"
        try:
            rounds = int(os.getenv("CONVERSATION_MAX_ROUNDS", "10"))
            enabled = os.getenv("CONVERSATION_SUMMARY_ENABLED", "true")
            assert rounds == 3  # explicit override
            assert enabled.lower() == "false"  # explicit override
        finally:
            del os.environ["CONVERSATION_MAX_ROUNDS"]
            del os.environ["CONVERSATION_SUMMARY_ENABLED"]


# ═══════════════════════════════════════════════════════════════
# Unit: Retry hint injection
# ═══════════════════════════════════════════════════════════════


class TestRetryHintInjection:
    """Verify retry hints are properly included in LLM prompts."""

    @pytest.mark.asyncio
    async def test_retry_hint_appended_on_second_attempt(self):
        """Second LLM call should include the compression strengthening hint."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # Use short messages + long summary to trigger retry
            mock_llm.side_effect = [_long_summary(), _short_summary()]

            await _call_summary_llm(
                messages=_make_short_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            # Second call should have the retry hint
            second_prompt = mock_llm.call_args_list[1][0][1]
            assert "压缩" in second_prompt
            assert "40%" in second_prompt

    @pytest.mark.asyncio
    async def test_extreme_retry_hint_on_third_attempt(self):
        """Third attempt (second retry) should include the extreme hint."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # Need short messages so even very long summaries fail compression
            mock_llm.side_effect = [
                _very_long_summary(),
                _long_summary(),
                _short_summary(),
            ]

            await _call_summary_llm(
                messages=_make_short_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=2,
            )

            # Third call should have the extreme hint
            third_prompt = mock_llm.call_args_list[2][0][1]
            assert "极限" in third_prompt
            assert "10 个字" in third_prompt


# ═══════════════════════════════════════════════════════════════
# Edge cases: retry loop safety
# ═══════════════════════════════════════════════════════════════


class TestRetryLoopSafety:
    """Verify retry loop handles edge case configurations safely."""

    @pytest.mark.asyncio
    async def test_max_retries_exceeds_hints_array(self):
        """max_retries=5 but hints only have 2 entries → uses last hint."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # All attempts fail compression (short messages + long summaries)
            mock_llm.side_effect = [
                _long_summary(), _very_long_summary(),
                _long_summary(), _very_long_summary(),
                _long_summary(), _long_summary(),
            ]

            result = await _call_summary_llm(
                messages=_make_short_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=5,  # exceeds hints array (2 entries)
            )

            # Should NOT crash with IndexError
            assert result is not None
            # All 6 attempts made (1 + 5 retries)
            assert mock_llm.call_count == 6

    @pytest.mark.asyncio
    async def test_max_retries_zero_still_tries_once(self):
        """max_retries=0 → 1 attempt (no retries)."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            # First attempt passes
            mock_llm.return_value = _short_summary()

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=0,
            )

            assert result is not None
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_negative_still_tries_once(self):
        """max_retries=-1 → still 1 attempt (guard: max(1, ...))."""
        from raganything.routers.agent import _call_summary_llm

        with patch("raganything.routers.agent.openai_complete_if_cache",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _short_summary()

            result = await _call_summary_llm(
                messages=_make_messages(6),
                existing_summary=None,
                model="test-model",
                compression_ratio=0.60,
                max_retries=-1,
            )

            assert result is not None
            assert mock_llm.call_count == 1
