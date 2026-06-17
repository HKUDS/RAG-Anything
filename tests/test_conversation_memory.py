"""
测试 ConversationManager — 多轮对话上下文记忆
"""
import asyncio
import json
import tempfile
import os
from pathlib import Path

import pytest

# 添加项目根路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from raganything.query import ConversationManager, ConversationContext, ThreadSummary


@pytest.fixture
def temp_storage():
    """使用临时文件避免影响测试数据"""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test_conv_")
    os.close(fd)
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_create_thread(temp_storage):
    """测试创建会话"""
    mgr = ConversationManager(temp_storage)
    thread = await mgr.get_or_create_thread("user1", title="测试会话")
    assert thread["id"].startswith("th_")
    assert thread["title"] == "测试会话"
    assert thread["user_id"] == "user1"
    assert thread["messages"] == []


@pytest.mark.asyncio
async def test_get_or_create_thread_reuse(temp_storage):
    """测试重复调用返回同一会话"""
    mgr = ConversationManager(temp_storage)
    t1 = await mgr.get_or_create_thread("user1", thread_id="th_test123")
    t2 = await mgr.get_or_create_thread("user1", thread_id="th_test123")
    assert t1["id"] == t2["id"] == "th_test123"


@pytest.mark.asyncio
async def test_add_message_and_get_context(temp_storage):
    """测试添加消息和提取上下文"""
    mgr = ConversationManager(temp_storage, max_rounds=2, max_tokens=4000)
    thread = await mgr.get_or_create_thread("user1", title="测试多轮")

    # 添加 3 轮对话
    await mgr.add_message(thread["id"], "user", "PLC故障码E001是什么意思？")
    await mgr.add_message(thread["id"], "assistant", "E001表示电机过载保护触发。")
    await mgr.add_message(thread["id"], "user", "这个故障怎么解决？")
    await mgr.add_message(thread["id"], "assistant", "首先检查电机负载是否过高。")
    await mgr.add_message(thread["id"], "user", "需要更换哪个部件？")
    await mgr.add_message(thread["id"], "assistant", "通常需要更换热继电器。")

    # 只取最近 max_rounds=2 轮（第1轮"E001"会被截断掉）
    ctx = await mgr.get_context(thread["id"], "我该去哪买热继电器？")
    assert ctx.round_count <= 2
    assert "热继电器" in ctx.history_text  # 最近 2 轮包含"热继电器"回答
    assert "需要更换" in ctx.history_text or "哪个部件" in ctx.history_text
    assert ctx.estimated_tokens > 0
    # 第1轮（E001解释）已超出 max_rounds=2，不应出现
    assert "E001" not in ctx.history_text


@pytest.mark.asyncio
async def test_token_budget_truncation(temp_storage):
    """测试 token 预算截断（max_tokens 很小）"""
    mgr = ConversationManager(temp_storage, max_rounds=5, max_tokens=50)
    thread = await mgr.get_or_create_thread("user1")
    for i in range(10):
        await mgr.add_message(thread["id"], "user", f"这是第{i}个很长很长很长很长很长很长的问题")
        await mgr.add_message(thread["id"], "assistant", f"这是第{i}个很长很长很长很长很长很长的回答")

    ctx = await mgr.get_context(thread["id"], "新问题")
    assert ctx.estimated_tokens <= 50 + 20  # 加上问题本身的一些余量


@pytest.mark.asyncio
async def test_list_threads(temp_storage):
    """测试列出用户会话"""
    mgr = ConversationManager(temp_storage)
    await mgr.get_or_create_thread("user1", title="会话A")
    await mgr.get_or_create_thread("user1", title="会话B")
    await mgr.get_or_create_thread("user2", title="用户2的会话")

    u1_list = await mgr.list_threads("user1")
    assert len(u1_list) == 2
    # 按更新时间倒序
    assert u1_list[0].updated_at >= u1_list[1].updated_at


@pytest.mark.asyncio
async def test_user_isolation(temp_storage):
    """测试用户隔离"""
    mgr = ConversationManager(temp_storage)
    t1 = await mgr.get_or_create_thread("user1", title="用户1会话")
    await mgr.add_message(t1["id"], "user", "敏感问题")
    await mgr.add_message(t1["id"], "assistant", "敏感回答")

    # 用户2 不能通过 list_threads 看到用户1的会话
    u2_list = await mgr.list_threads("user2")
    assert len(u2_list) == 0

    # 用户2 无法通过 get_context 获取用户1的会话（需用户隔离校验）
    # 当前 get_context 不校验用户归属，但 API 层校验
    ctx = await mgr.get_context(t1["id"])
    assert ctx.history_text != ""  # get_context 内部不校验用户（由 API 层做）


@pytest.mark.asyncio
async def test_delete_thread(temp_storage):
    """测试删除会话"""
    mgr = ConversationManager(temp_storage)
    thread = await mgr.get_or_create_thread("user1", title="待删除")
    assert await mgr.delete_thread(thread["id"]) is True
    assert await mgr.delete_thread("nonexistent") is False


@pytest.mark.asyncio
async def test_max_per_user_limit(temp_storage):
    """测试每用户会话数上限"""
    max_pu = 3
    mgr = ConversationManager(temp_storage, max_per_user=max_pu)
    for i in range(max_pu):
        result = await mgr.get_or_create_thread("user1", title=f"会话{i}")
        assert "error" not in result

    # 第 4 个应该被拒绝
    over = await mgr.get_or_create_thread("user1", title="超出限制")
    assert "error" in over


@pytest.mark.asyncio
async def test_persistence(temp_storage):
    """测试持久化（保存后重新加载）"""
    mgr1 = ConversationManager(temp_storage, max_rounds=3, max_tokens=2000)
    t1 = await mgr1.get_or_create_thread("user1", title="持久化测试")
    await mgr1.add_message(t1["id"], "user", "测试消息")

    # 重新加载
    mgr2 = ConversationManager(temp_storage, max_rounds=3, max_tokens=2000)
    await mgr2._load()
    t2_threads = await mgr2.list_threads("user1")
    assert len(t2_threads) == 1
    assert t2_threads[0].id == t1["id"]
    assert t2_threads[0].title == "持久化测试"
    assert t2_threads[0].message_count == 1


@pytest.mark.asyncio
async def test_get_context_for_rewrite(temp_storage):
    """测试查询改写历史提取"""
    mgr = ConversationManager(temp_storage, max_rounds=3)
    thread = await mgr.get_or_create_thread("user1")
    await mgr.add_message(thread["id"], "user", "PLC故障码E001是什么意思？")
    await mgr.add_message(thread["id"], "assistant", "E001表示电机过载...")
    await mgr.add_message(thread["id"], "user", "第二个问题")

    history = await mgr.get_context_for_rewrite(thread["id"])
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert "PLC" in history[0]["content"]


@pytest.mark.asyncio
async def test_title_truncation(temp_storage):
    """测试标题截断"""
    mgr = ConversationManager(temp_storage)
    long_title = "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的标题" * 5
    thread = await mgr.get_or_create_thread("user1", title=long_title)
    assert len(thread["title"]) <= 50


@pytest.mark.asyncio
async def test_empty_thread_context(temp_storage):
    """测试空会话的上下文"""
    mgr = ConversationManager(temp_storage)
    thread = await mgr.get_or_create_thread("user1")
    ctx = await mgr.get_context(thread["id"], "新问题")
    assert ctx.history_text == ""
    assert ctx.round_count == 0


@pytest.mark.asyncio
async def test_message_content_truncation(temp_storage):
    """测试单条消息长度截断"""
    mgr = ConversationManager(temp_storage)
    thread = await mgr.get_or_create_thread("user1")
    long_msg = "A" * 15000
    await mgr.add_message(thread["id"], "user", long_msg)
    # 重新读取
    updated = await mgr.get_or_create_thread("user1", thread_id=thread["id"])
    assert len(updated["messages"][0]["content"]) <= 10000


@pytest.mark.asyncio
async def test_stats(temp_storage):
    """测试统计信息"""
    mgr = ConversationManager(temp_storage)
    t = await mgr.get_or_create_thread("user1")
    await mgr.add_message(t["id"], "user", "Q1")
    await mgr.add_message(t["id"], "assistant", "A1")
    stats = mgr.get_stats()
    assert stats["total_threads"] == 1
    assert stats["total_messages"] == 2
    assert temp_storage in stats["storage_path"]
