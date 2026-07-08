"""
AgenticRAG 多步推理流程测试

验证制造智能体 QA 引擎的 ReAct 推理循环。
"""
import pytest
import asyncio


class TestAgenticRAGReasoning:
    """AgenticRAG 推理流程测试（需要 LLM API 环境变量）。"""

    def test_agentic_rag_init_with_system_prompt_override(self):
        """验证 AgenticRAG 支持 system_prompt_override 参数。"""
        from raganything.agentic_rag import AgenticRAG

        async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
            return "Thought: 测试思考\nAction: FINISH\nAction Input: {\"answer\": \"test\"}"

        agent = AgenticRAG(
            llm_func=dummy_llm,
            max_steps=3,
            mode="react",
            system_prompt_override="你是智能制造教学专家。",
        )
        assert agent.system_prompt_override == "你是智能制造教学专家。"
        assert agent.max_steps == 3
        assert agent.mode == "react"

        # Verify prompt includes override
        sp, up = agent._build_react_prompt("测试")
        assert "你是智能制造教学专家" in sp
        assert "工具" in sp  # tool descriptions retained

    def test_agentic_rag_default_prompt(self):
        """验证无 override 时使用默认 prompt。"""
        from raganything.agentic_rag import AgenticRAG

        async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
            return "Thought: ok\nAction: FINISH\nAction Input: {\"answer\": \"test\"}"

        agent = AgenticRAG(llm_func=dummy_llm, max_steps=2, mode="react")
        assert agent.system_prompt_override is None

        sp, _ = agent._build_react_prompt("测试")
        assert "具备多步推理能力的 AI 助手" in sp

    @pytest.mark.asyncio
    async def test_react_loop_finish_immediately(self):
        """验证 ReAct 循环在 LLM 直接 FINISH 时的行为。"""
        from raganything.agentic_rag import AgenticRAG

        async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
            return (
                "Thought: 可以直接回答问题\n"
                "Action: FINISH\n"
                'Action Input: {"answer": "这是一个测试回答"}'
            )

        agent = AgenticRAG(llm_func=dummy_llm, max_steps=5, mode="react")
        result = await agent.run("测试问题")
        assert result.answer == "这是一个测试回答"
        assert result.total_steps == 1
        assert len(result.trace) == 1
        assert result.trace[0].action == "FINISH"

    @pytest.mark.asyncio
    async def test_react_loop_max_steps(self):
        """验证 Agent 达到 max_steps 时能强制生成回答。"""
        from raganything.agentic_rag import AgenticRAG, Tool

        call_count = [0]

        class DummyTool(Tool):
            name = "search"
            description = "搜索"
            parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

            async def execute(self, input: dict) -> str:
                return "搜索结果：没有找到相关信息"

        async def llm_func(prompt, system_prompt=None, history_messages=None, **kw):
            call_count[0] += 1
            if call_count[0] <= 2:
                return (
                    f"Thought: 需要检索 (第{call_count[0]}次)\n"
                    'Action: search\n'
                    'Action Input: {"query": "test"}'
                )
            return (
                "Thought: 已尝试多次检索\n"
                "Action: FINISH\n"
                'Action Input: {"answer": "经过检索未找到相关信息"}'
            )

        agent = AgenticRAG(llm_func=llm_func, max_steps=3, mode="react")
        agent.register_tool(DummyTool())
        result = await agent.run("测试")

        assert result.total_steps <= 3
        assert len(result.trace) >= 1

    def test_qa_engine_agentic_rag_creation(self):
        """验证 QAEngine 创建 AgenticRAG 实例。"""
        from raganything.autorepair.agent.qa_engine import QAEngine

        async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
            return "test response"

        engine = QAEngine(
            rag_client=None,
            llm_client=dummy_llm,
            query_mode="rrf",
            max_steps=3,
        )
        # With a callable llm_client, _agentic_rag should be created
        assert engine._agentic_rag is not None
        assert engine._agentic_rag.max_steps == 3
        assert engine._agentic_rag.mode == "react"

    def test_agent_response_has_trace_field(self):
        """验证 AgentResponse 模型包含 trace 字段。"""
        from raganything.autorepair.knowledge_graph.models import AgentResponse

        resp = AgentResponse(
            query="test",
            answer="test answer",
            trace=[{"step": 1, "thought": "测试", "action": "search"}],
        )
        assert resp.trace == [{"step": 1, "thought": "测试", "action": "search"}]
        assert hasattr(resp, 'trace')

    def test_agentic_rag_max_response_tokens_is_clamped(self):
        from raganything.agentic_rag import AgenticRAG

        async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
            return 'Action: FINISH\nAction Input: {"answer": "ok"}'

        assert AgenticRAG(dummy_llm, max_response_tokens=128).max_response_tokens == 512
        assert AgenticRAG(dummy_llm, max_response_tokens=999999).max_response_tokens == 16384
        assert AgenticRAG(dummy_llm, max_response_tokens="bad").max_response_tokens == 4096

    @pytest.mark.asyncio
    async def test_agentic_rag_uses_runtime_token_budget(self):
        from raganything.agentic_rag import AgenticRAG

        calls = []

        async def dummy_llm(prompt, system_prompt=None, history_messages=None, **kw):
            calls.append(kw.get("max_tokens"))
            return "final answer"

        agent = AgenticRAG(dummy_llm, max_response_tokens=8192)
        await agent._call_llm_with_retry("system", "user", [], is_final_step=False)
        await agent._call_llm_with_retry("system", "user", [], is_final_step=True)
        await agent._force_final_answer("system", "question", [])
        await agent._cot_loop("question", context="context")

        assert calls == [2048, 8192, 8192, 8192]

    @pytest.mark.asyncio
    async def test_search_tool_passes_retrieval_runtime_parameters(self):
        from raganything.agentic_rag import SearchTool

        class DummyRAG:
            def __init__(self):
                self.calls = []

            async def aquery(self, query, mode="hybrid", **kwargs):
                self.calls.append({"query": query, "mode": mode, "kwargs": kwargs})
                return "search result"

        rag = DummyRAG()
        tool = SearchTool(
            rag,
            query_mode="rrf",
            top_k=77,
            chunk_top_k=12,
            enable_rerank=True,
            include_references=False,
        )

        result = await tool.execute({"query": "hello"})

        assert result == "search result"
        assert rag.calls == [
            {
                "query": "hello",
                "mode": "rrf",
                "kwargs": {
                    "only_need_context": True,
                    "enable_rerank": True,
                    "chunk_top_k": 12,
                    "top_k": 77,
                    "include_references": False,
                    "max_entity_tokens": 2000,
                    "max_relation_tokens": 1000,
                    "max_total_tokens": 8000,
                },
            }
        ]

    def test_agent_runtime_config_normalises_bounds_and_bools(self):
        from raganything.routers.agent import _agent_runtime_config

        config = _agent_runtime_config({
            "max_response_tokens": "999999",
            "retrieval_top_k": "2",
            "chunk_top_k": "bad",
            "enable_rerank": "yes",
            "include_references": "off",
        })

        assert config == {
            "max_response_tokens": 16384,
            "retrieval_top_k": 5,
            "chunk_top_k": 20,
            "enable_rerank": True,
            "include_references": False,
        }
