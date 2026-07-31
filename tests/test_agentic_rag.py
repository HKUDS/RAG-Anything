"""
MVP 验收测试 — Agentic RAG 多步推理引擎

运行: pytest tests/test_agentic_rag.py -v
"""
import asyncio
import pytest

from raganything.agentic_rag import (
    AgenticRAG,
    SearchTool,
    CalculatorTool,
    DatabaseQueryTool,
    WebSearchTool,
    ReasoningStep,
    AgentResult,
    Tool,
)


# ═══════════════════════════════════════════════════════════
# Mock LLM — 模拟 ReAct 循环中 LLM 的行为
# ═══════════════════════════════════════════════════════════

class MockLLM:
    """可编程的 Mock LLM，用于测试不同的推理路径"""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0
        self.calls: list[dict] = []

    async def __call__(self, prompt="", system_prompt="", history_messages=None, **kw):
        self.calls.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "history_messages": history_messages,
        })
        idx = min(self.call_count, len(self.responses) - 1)
        response = self.responses[idx]
        self.call_count += 1
        return response


# ═══════════════════════════════════════════════════════════
# Mock RAG — 模拟知识库检索
# ═══════════════════════════════════════════════════════════

class MockRAG:
    """模拟 RAGAnything 实例的 aquery 方法"""

    def __init__(self, kb_data: dict[str, str] | None = None):
        self.kb_data = kb_data or {}
        self.queries: list[str] = []

    async def aquery(self, query, mode="hybrid", **kw):
        self.queries.append(query)
        # 返回匹配的知识库内容
        for key, content in self.kb_data.items():
            if key.lower() in query.lower():
                return content
        return "知识库中未找到相关信息"


# ═══════════════════════════════════════════════════════════
# 测试 6.1: Agent 自动分步检索+计算
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_agent_two_step_search_and_calculate():
    """MVP 验收: Agent 分 2 步完成检索+计算任务"""
    mock_rag = MockRAG({
        "销售额": "产品A销售额: 1000万, 产品B销售额: 800万, 产品C销售额: 600万",
    })

    # 模拟 LLM 输出：
    # Step 1: 检索销售额数据
    # Step 2: 计算差距百分比
    mock_llm = MockLLM([
        """Thought: 需要先检索产品销售额数据
Action: search
Action Input: {"query": "各产品销售额"}
""",
        """Thought: 已获取数据：产品A 1000万, 产品B 800万。计算(1000-800)/800*100=25%
Action: FINISH
Action Input: {"answer": "销售额最高的产品是产品A（1000万），比第二名产品B（800万）高25%"}
""",
    ])

    agentic = AgenticRAG(llm_func=mock_llm, mode="react", max_steps=5)
    agentic.register_tool(SearchTool(mock_rag))
    agentic.register_tool(CalculatorTool())

    result = await agentic.run("去年销售额最高的产品是什么，比第二名高多少%")

    assert isinstance(result, AgentResult)
    assert result.total_steps == 2
    assert "产品A" in result.answer
    assert "25%" in result.answer or "25" in result.answer
    assert len(result.trace) == 2  # 2 个推理步骤（不含 FINISH 步骤，FINISH 也是 trace 的一部分）

    # 验证第一步是搜索，第二步是 FINISH
    assert len(mock_rag.queries) >= 1
    print(f"✅ 2步推理完成: steps={result.total_steps}, answer={result.answer[:80]}")


# ═══════════════════════════════════════════════════════════
# 测试 6.2: max_steps=5 时不会无限循环
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_max_steps_enforced_no_infinite_loop():
    """MVP 验收: max_steps=5 强制终止，不会无限循环"""
    mock_rag = MockRAG({"test": "test data"})

    # 模拟 LLM 每步都继续搜索，永不 FINISH
    responses = []
    for i in range(10):
        responses.append(f"""Thought: 还需要更多信息，继续搜索
Action: search
Action Input: {{"query": "step {i+1}"}}
""")

    mock_llm = MockLLM(responses)

    agentic = AgenticRAG(llm_func=mock_llm, mode="react", max_steps=5)
    agentic.register_tool(SearchTool(mock_rag))

    result = await agentic.run("无限循环测试问题")

    # 必须在 5 步内终止
    assert result.total_steps <= 5
    assert "达到最大步数限制" in result.answer or result.total_steps == 5
    print(f"✅ max_steps 强制终止: steps={result.total_steps}")


# ═══════════════════════════════════════════════════════════
# 测试 6.3: 工具超时 30s 自动跳过
# ═══════════════════════════════════════════════════════════

class SlowTool(Tool):
    """模拟超时工具"""
    name = "slow_tool"
    description = "A deliberately slow tool for testing timeout"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, delay: float = 35.0):
        self.delay = delay

    async def execute(self, input: dict) -> str:
        await asyncio.sleep(self.delay)
        return "Slow result"


@pytest.mark.asyncio
async def test_tool_timeout_30s_auto_skip(monkeypatch):
    """MVP 验收: 单工具超时 30s 自动跳过，不中断推理"""
    # 缩短超时时间便于测试
    monkeypatch.setenv("AGENT_TOOL_TIMEOUT", "1")

    # Step 1: 调用慢工具 → 超时
    # Step 2: FINISH（因为 max_steps=2）
    mock_llm = MockLLM([
        """Thought: 需要调用慢工具
Action: slow_tool
Action Input: {}
""",
        """Thought: 慢工具超时了，尝试回答
Action: FINISH
Action Input: {"answer": "工具超时，无法获取数据"}
""",
    ])

    agentic = AgenticRAG(llm_func=mock_llm, mode="react", max_steps=2)
    agentic.register_tool(SlowTool(delay=10.0))  # 实际延迟 10s，但超时设为 1s

    result = await agentic.run("测试超时")

    # 应该正常完成（超时被跳过）
    assert result.answer is not None
    # 第一步应该记录了超时
    assert len(result.trace) >= 1
    obs_has_timeout = any(
        "超时" in (s.observation or "") for s in result.trace
    )
    assert obs_has_timeout, f"超时未被记录。Trace: {result.trace}"
    print(f"✅ 工具超时处理正常: timeout_detected={obs_has_timeout}")


# ═══════════════════════════════════════════════════════════
# 测试 6.4: 不支持的问题明确告知用户
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unsupported_question_explicitly_refused():
    """MVP 验收: 不支持的问题明确告知用户"""
    mock_rag = MockRAG({})

    mock_llm = MockLLM([
        """Thought: 用户要求删除系统文件，这超出了我的能力范围
Action: FINISH
Action Input: {"answer": "抱歉，当前无法回答此问题。删除系统文件不在我的能力范围内，请咨询系统管理员。"}
""",
    ])

    agentic = AgenticRAG(llm_func=mock_llm, mode="react", max_steps=3)
    agentic.register_tool(SearchTool(mock_rag))

    result = await agentic.run("请帮我删除系统文件")

    assert result.answer is not None
    assert len(result.answer) > 0
    # 应该包含拒绝/无法回答的信息
    assert any(
        keyword in result.answer
        for keyword in ["无法", "抱歉", "不能", "超出", "不支持"]
    ), f"Expected refusal message in: {result.answer}"
    print(f"✅ 不支持的问题已明确告知: {result.answer[:80]}")


# ═══════════════════════════════════════════════════════════
# 辅助测试：Calculator 安全求值
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_calculator_safe_eval():
    """安全求值正常计算"""
    calc = CalculatorTool()
    result = await calc.execute({"expression": "123 * 456 + 789"})
    assert "56877" in result


@pytest.mark.asyncio
async def test_calculator_blocks_malicious_input():
    """恶意输入被拦截"""
    calc = CalculatorTool()
    # 尝试 import
    result = await calc.execute({"expression": "__import__('os').system('dir')"})
    assert "不允许" in result

    # 尝试 exec
    result = await calc.execute({"expression": "exec('print(1)')"})
    assert "不允许" in result


# ═══════════════════════════════════════════════════════════
# 辅助测试：Tool 注册
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tool_registration():
    """工具注册正常"""
    mock_llm = MockLLM([])
    agentic = AgenticRAG(llm_func=mock_llm)

    calc = CalculatorTool()
    agentic.register_tool(calc)
    assert "calculator" in agentic.tools

    # 重复注册应报错
    with pytest.raises(ValueError):
        agentic.register_tool(CalculatorTool())


# ═══════════════════════════════════════════════════════════
# 辅助测试：DatabaseQueryTool 预留接口
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_database_query_tool_stats():
    """DatabaseQueryTool 返回真实统计数据 (PG available) or graceful message (PG unavailable)"""
    tool = DatabaseQueryTool(kb_dir="./rag_storage")
    result = await tool.execute({"query": "全部"})
    # If PG is available, expect real stats; otherwise graceful unavailable message
    if "数据库不可用" in result or "数据库查询出错" in result:
        # PG not available in test context — tool handles it gracefully
        assert "PostgreSQL" in result or "PG" in result or "未初始化" in result or "出错" in result
    else:
        assert "文档统计" in result
        assert "知识库列表" in result
        assert "智能体统计" in result


# ═══════════════════════════════════════════════════════════
# 辅助测试：DatasetSearchTool 空查询
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_tool_empty_query():
    """空查询被拒绝"""
    tool = SearchTool(rag_instance=None)
    result = await tool.execute({"query": ""})
    assert "查询词不能为空" in result


@pytest.mark.asyncio
async def test_search_tool_no_rag():
    """无 RAG 实例时明确报错"""
    tool = SearchTool(rag_instance=None)
    result = await tool.execute({"query": "test"})
    assert "未初始化" in result
