"""Regression tests for user-facing SSE retrieval progress."""

import pytest

from raganything.routers.shared import _is_thinking_msg, _translate_thinking_msg


@pytest.mark.parametrize(
    ("log_message", "expected"),
    [
        ("Initializing LightRAG with parameters: {'working_dir': './rag_storage'}", "正在准备知识库检索..."),
        ("LightRAG, parse cache, multimodal status cache, and multimodal processors initialized", "知识库检索已准备就绪"),
        ("Executing RRF hybrid query", "正在综合检索相关资料..."),
        ("Embedding func: 4 new workers initialized (Timeouts: Func: 30s)", "正在进行语义匹配..."),
        ("Final context: 20 chunks", "已整理 20 条相关资料"),
    ],
)
def test_translates_supported_retrieval_progress(log_message, expected):
    assert _translate_thinking_msg(log_message) == expected
    assert _is_thinking_msg(log_message) is True


@pytest.mark.parametrize(
    "technical_log",
    [
        "PostgreSQL table: LIGHTRAG_VDB_ENTITY missing suffix. Pls add model_name to embedding_func.",
        "Parse cache disabled: active KV backend does not support namespace=parse_cache",
        "Multimodal status cache disabled: active KV backend does not support namespace=multimodal_status",
        "[vision-repo] Initialized dim=2048 model=doubao-embedding-vision-251215",
        "Unexpected provider configuration detail",
    ],
)
def test_hides_internal_logs_from_user_progress(technical_log):
    assert _translate_thinking_msg(technical_log) == ""
    assert _is_thinking_msg(technical_log) is False
