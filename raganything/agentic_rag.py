"""
Agentic RAG 多步推理引擎 — ReAct / Chain-of-Thought 推理循环 + 工具调用

用法:
    from raganything.agentic_rag import AgenticRAG, SearchTool, CalculatorTool

    agentic = AgenticRAG(llm_func=llm_func, mode="react", max_steps=5)
    agentic.register_tool(SearchTool(rag_instance))
    agentic.register_tool(CalculatorTool())
    result = await agentic.run("去年销售额最高的产品是什么，比第二名高多少%")
    print(result.answer)
    for step in result.trace:
        print(f"Step {step.step_number}: {step.thought[:60]}...")
"""
from __future__ import annotations

import asyncio
import json
import math as _math
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════


@dataclass
class ReasoningStep:
    """单步推理记录"""
    step_number: int
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict] = None
    observation: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class AgentResult:
    """Agentic RAG 查询结果"""
    answer: str
    trace: list[ReasoningStep] = field(default_factory=list)
    total_steps: int = 0
    total_elapsed_ms: float = 0.0


# ═══════════════════════════════════════════════════════════
# Tool 基类
# ═══════════════════════════════════════════════════════════


class Tool(ABC):
    """工具抽象基类

    子类必须定义:
        name: str           — 工具名称（用于 ReAct Action 匹配）
        description: str    — 工具描述（注入 LLM prompt）
        parameters: dict    — JSON Schema 参数定义

    子类必须实现:
        async execute(input: dict) -> str
    """
    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    async def execute(self, input: dict) -> str:
        ...

    def to_schema(self) -> dict:
        """返回 OpenAI function-calling 格式的工具 schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# ═══════════════════════════════════════════════════════════
# AgenticRAG — ReAct / CoT 推理循环
# ═══════════════════════════════════════════════════════════


class AgenticRAG:
    """Agentic RAG 多步推理引擎

    Args:
        llm_func: 异步 LLM 调用函数 async (prompt, system_prompt, **kw) -> str
        max_steps: 最大推理步数（默认 5）
        mode: 推理模式 "react" | "cot"
    """

    def __init__(
        self,
        llm_func: Callable,
        max_steps: int = 5,
        mode: str = "react",
    ):
        self.llm_func = llm_func
        self.max_steps = max_steps
        self.mode = mode
        self.tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        """注册工具"""
        if tool.name in self.tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self.tools[tool.name] = tool

    # ── Public API ─────────────────────────────────

    async def run(self, query: str, kb_ids: Optional[list[str]] = None) -> AgentResult:
        """执行 Agentic 查询

        Args:
            query: 用户问题
            kb_ids: 指定知识库 ID 列表（可选，传递给 SearchTool）

        Returns:
            AgentResult 包含最终回答和推理轨迹
        """
        if self.mode == "react":
            return await self._react_loop(query)
        elif self.mode == "cot":
            return await self._cot_loop(query)
        else:
            raise ValueError(f"Unknown mode: {self.mode} (expected 'react' or 'cot')")

    # ── ReAct Prompt 构建 ────────────────────────────

    def _build_react_prompt(self, query: str) -> tuple[str, str]:
        """构建 ReAct system prompt 和 user prompt"""
        tool_descriptions = "\n".join(
            f"- **{t.name}**: {t.description}\n  Parameters: {json.dumps(t.parameters, ensure_ascii=False)}"
            for t in self.tools.values()
        )

        tool_names = ", ".join(t.name for t in self.tools.values()) if self.tools else "无"

        system_prompt = f"""你是一个具备多步推理能力的 AI 助手。你可以使用工具来获取信息，然后逐步推理得出最终答案。

## 可用工具
{tool_descriptions}

## 推理格式
你必须严格按照以下格式输出每一步：

Thought: <你的思考过程，分析当前需要什么信息，是否已有足够信息回答>
Action: <工具名称 或 FINISH>
Action Input: <JSON 格式的工具参数 或 最终答案>

## 规则
1. 每一步只能调用一个工具。
2. 如果用户的问题需要知识库中的信息，第一步必须先调用 search 检索。
3. 每次收到 Observation 后，先判断：已有信息是否足以回答用户问题？如果是，立即 FINISH。
4. search 最多使用 2 次。第 2 次 search 后，无论结果如何必须 FINISH。
5. 如果 Observation 中的内容与之前重复，说明已无新信息，立即 FINISH。
6. Action 必须是以下之一: {tool_names}, FINISH
7. 如果确实无法回答，Action 设为 FINISH，Action Input: {{"answer": "抱歉，当前无法回答此问题"}}
8. FINISH 的 Action Input 必须是完整的最终回答，不能是计划或说明。
9. 你必须用中文思考和回答。
"""

        user_prompt = f"## 用户问题\n{query}\n\n现在请开始推理。从 Thought 开始:"

        return system_prompt, user_prompt

    # ── CoT Prompt 构建 ──────────────────────────────

    def _build_cot_prompt(self, query: str) -> tuple[str, str]:
        """构建 CoT (Chain-of-Thought) prompt"""
        system_prompt = """你是一个具备逐步推理能力的 AI 助手。

## 推理格式
请按以下格式逐步思考并回答：

思考步骤1: <第一步分析>
思考步骤2: <第二步分析>
...
最终回答: <综合各步骤后的完整答案>

## 规则
1. 每一步分析都需要引用具体的检索内容
2. 如果信息不足，在最终回答中明确说明
3. 最终回答必须基于前面的推理步骤
"""
        user_prompt = f"## 用户问题\n{query}\n\n请开始逐步推理。"
        return system_prompt, user_prompt

    # ── 输出解析 ────────────────────────────────────

    def _parse_action(self, response: str) -> tuple[str, str, dict | None]:
        """解析 LLM 输出中的 Thought/Action/Action Input

        支持三种格式:
        1. 标准格式: Thought: ... / Action: xxx / Action Input: {...}
        2. 中文格式: 思考: ... / 行动: xxx / 行动输入: {...}
        3. 自由格式: 将整个回答作为 thought，自动降级为 FINISH

        Returns:
            (thought, action, action_input_dict)
        """
        thought = ""
        action = ""
        action_input: dict | None = None

        # ── 匹配 Thought/思考 ──
        thought_match = re.search(
            r'(?:Thought|思考|分析)\s*[:：]\s*(.+?)(?=\n\s*(?:Action|行动|FINISH|完成|Observation|观察)\s*[:：]|\Z)',
            response, re.DOTALL | re.IGNORECASE
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        # ── 匹配 Action/行动/工具 ──
        action_match = re.search(
            r'(?:Action|行动|工具)\s*[:：]\s*(\w+)',
            response, re.IGNORECASE
        )
        if action_match:
            action = action_match.group(1).strip()

        # ── 检测 FINISH/完成/最终回答 ──
        if re.search(r'(?:FINISH|完成|最终回答|Final\s*Answer)', response, re.IGNORECASE):
            action = "FINISH"

        # ── 解析 JSON Action Input ──
        # Pattern 1: Action Input: {...}
        json_match = re.search(
            r'(?:Action\s*Input|行动输入|参数)\s*[:：]\s*(\{[^}]+\})',
            response, re.DOTALL | re.IGNORECASE
        )
        if json_match:
            try:
                action_input = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Pattern 2: Any JSON block in the response
        if action_input is None:
            json_blocks = re.findall(r'\{[^{}]*\}', response)
            for block in reversed(json_blocks):
                try:
                    parsed = json.loads(block)
                    # 如果是 {"answer": "..."} 或 {"query": "..."}，这就是 action input
                    if isinstance(parsed, dict) and any(
                        k in parsed for k in ("answer", "query", "expression")
                    ):
                        action_input = parsed
                        break
                except json.JSONDecodeError:
                    continue

        # ── Fallback: 无法解析时默认 FINISH ──
        if not action:
            # 如果有行动但没有工具名，默认 FINISH
            action = "FINISH"
            if thought and not action_input:
                action_input = {"answer": thought}
            elif not action_input:
                # 把整个回答当做最终答案
                text = response.strip()
                action_input = {"answer": text[:2000]}

        # Final fallback: if FINISH but no JSON, treat whole text as answer
        if action.upper() == "FINISH" and action_input is None:
            # Use everything after "FINISH" as the answer
            finish_idx = re.search(r'FINISH', response, re.IGNORECASE)
            if finish_idx:
                answer_text = response[finish_idx.end():].strip().lstrip(':：').strip()
                if answer_text:
                    action_input = {"answer": answer_text}
                else:
                    action_input = {"answer": thought or "无法生成回答"}

        return thought, action, action_input

    # ── ReAct Loop ──────────────────────────────────

    async def _react_loop(self, query: str) -> AgentResult:
        """ReAct 推理主循环"""
        trace: list[ReasoningStep] = []
        start_time = time.time()

        system_prompt, user_prompt = self._build_react_prompt(query)
        messages: list[dict] = []

        for step_num in range(1, self.max_steps + 1):
            step_start = time.time()

            # ── 调用 LLM ──
            try:
                response = await self._call_llm_with_retry(
                    system_prompt, user_prompt, messages
                )
            except Exception as e:
                # LLM 调用失败，返回已收集信息
                return AgentResult(
                    answer=f"推理过程出错: {e}",
                    trace=trace,
                    total_steps=step_num,
                    total_elapsed_ms=(time.time() - start_time) * 1000,
                )

            # ── 解析输出 ──
            thought, action, action_input = self._parse_action(response)

            # ── 检查是否 FINISH ──
            if action.upper() == "FINISH":
                answer = action_input.get("answer", thought) if action_input else thought
                trace.append(ReasoningStep(
                    step_number=step_num,
                    thought=thought,
                    action="FINISH",
                    action_input=action_input,
                    observation="推理完成",
                    elapsed_ms=(time.time() - step_start) * 1000,
                ))
                return AgentResult(
                    answer=answer,
                    trace=trace,
                    total_steps=step_num,
                    total_elapsed_ms=(time.time() - start_time) * 1000,
                )

            # ── 执行工具（带超时）──
            observation = await self._execute_tool_with_timeout(
                action, action_input or {}
            )

            elapsed_ms = (time.time() - step_start) * 1000
            trace.append(ReasoningStep(
                step_number=step_num,
                thought=thought,
                action=action if action else None,
                action_input=action_input,
                observation=observation,
                elapsed_ms=elapsed_ms,
            ))

            # ── 拼接历史消息给下一轮（含步数额度提示）──
            remaining = self.max_steps - step_num
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": (
                f"[Step {step_num}/{self.max_steps}] Observation: {observation}\n\n"
                f"还剩 {remaining} 步。"
                f"{'这是最后一次机会，必须 FINISH。' if remaining == 0 else ''}\n"
                f"请继续推理。从 Thought 开始:"
            )})

            # ── 检查是否超过最大步数 ──
            if step_num >= self.max_steps:
                # 尝试生成最终回答
                final_answer = await self._force_final_answer(
                    system_prompt, query, trace
                )
                return AgentResult(
                    answer=final_answer,
                    trace=trace,
                    total_steps=step_num,
                    total_elapsed_ms=(time.time() - start_time) * 1000,
                )

        # Should not reach here
        return AgentResult(
            answer="推理达到最大步数限制，以下为截至目前收集的信息。",
            trace=trace,
            total_steps=self.max_steps,
            total_elapsed_ms=(time.time() - start_time) * 1000,
        )

    async def _call_llm_with_retry(
        self, system_prompt: str, user_prompt: str, messages: list[dict]
    ) -> str:
        """调用 LLM，带单次重试"""
        conversation = [
            {"role": "system", "content": system_prompt},
            *messages,
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self.llm_func(
                prompt=user_prompt,
                system_prompt=system_prompt,
                history_messages=messages,
                max_tokens=4096,
                temperature=0.0,
            )
            if isinstance(response, str) and response.strip():
                return response.strip()
        except Exception:
            pass

        # Retry once
        await asyncio.sleep(1)
        response = await self.llm_func(
            prompt=user_prompt,
            system_prompt=system_prompt,
            history_messages=messages,
            max_tokens=4096,
            temperature=0.0,
        )
        return response.strip() if isinstance(response, str) else str(response)

    async def _force_final_answer(
        self, system_prompt: str, query: str, trace: list[ReasoningStep]
    ) -> str:
        """当 max_steps 耗尽时，强制基于观察生成最终回答（去重+综合）"""
        # 去重：合并高度相似的 observation
        seen = set()
        deduped = []
        for s in trace:
            if s.observation:
                # 取前 100 字符做相似度判断
                key = s.observation[:100].strip()
                if key not in seen:
                    seen.add(key)
                    deduped.append(s)

        observations = "\n".join(
            f"Step {s.step_number} Observation: {s.observation}"
            for s in deduped if s.observation
        )

        unique_count = len(deduped)
        total_count = len([s for s in trace if s.observation])
        dedup_note = (
            f"（原始{total_count}条已去重至{unique_count}条，重复内容已合并）"
            if total_count > unique_count else ""
        )

        final_prompt = (
            f"以下是多次检索收集到的信息（已去重）。请综合这些信息，直接给出最终回答。\n\n"
            f"## 用户问题\n{query}\n\n"
            f"## 收集到的信息{dedup_note}\n{observations}\n\n"
            f"## 要求\n"
            f"1. 综合所有信息，提取关键事实和数据\n"
            f"2. 直接给出完整回答，不要再说\"需要更多信息\"\n"
            f"3. 如果信息确实不足以回答问题，明确说明缺少什么"
        )
        try:
            response = await self.llm_func(
                prompt=final_prompt,
                system_prompt=system_prompt,
                history_messages=[],
                max_tokens=4096,
                temperature=0.0,
            )
            return response.strip() if isinstance(response, str) else str(response)
        except Exception as e:
            return f"推理达到最大步数限制（{self.max_steps}步）。{str(e)}"

    # ── CoT Loop ────────────────────────────────────

    async def _cot_loop(self, query: str) -> AgentResult:
        """CoT 推理 — 逐步思考后汇总回答"""
        trace: list[ReasoningStep] = []
        start_time = time.time()

        system_prompt, user_prompt = self._build_cot_prompt(query)

        try:
            response = await self.llm_func(
                prompt=user_prompt,
                system_prompt=system_prompt,
                history_messages=[],
                max_tokens=4096,
                temperature=0.0,
            )
            response = response.strip() if isinstance(response, str) else str(response)
        except Exception as e:
            return AgentResult(
                answer=f"CoT 推理出错: {e}",
                trace=trace,
                total_steps=0,
                total_elapsed_ms=(time.time() - start_time) * 1000,
            )

        # ── 解析 CoT 输出 ──
        # 尝试提取 "思考步骤N" 和 "最终回答"
        steps = re.split(r'思考步骤\s*\d+\s*[:：]', response)
        final_answer = response

        # 查找最终回答部分
        final_match = re.search(
            r'最终回答\s*[:：]\s*(.+)', response, re.DOTALL | re.IGNORECASE
        )
        if final_match:
            final_answer = final_match.group(1).strip()
            # 前面的部分是推理步骤
            reasoning_part = response[:final_match.start()]
            cot_steps = re.split(r'思考步骤\s*\d+\s*[:：]', reasoning_part)
            for i, step_text in enumerate(cot_steps):
                if step_text.strip():
                    trace.append(ReasoningStep(
                        step_number=i,
                        thought=step_text.strip(),
                        elapsed_ms=0,
                    ))
        else:
            # 没有明确格式，整体作为一个思考步骤
            trace.append(ReasoningStep(
                step_number=1,
                thought=response,
                elapsed_ms=0,
            ))
            final_answer = response

        total_ms = (time.time() - start_time) * 1000
        return AgentResult(
            answer=final_answer,
            trace=trace,
            total_steps=len(trace),
            total_elapsed_ms=total_ms,
        )

    # ── 工具执行（带超时）────────────────────────────

    async def _execute_tool_with_timeout(
        self, tool_name: str, tool_input: dict
    ) -> str:
        """执行工具，30 秒超时"""
        tool = self.tools.get(tool_name)
        if not tool:
            return f"工具 '{tool_name}' 不存在。可用工具: {', '.join(self.tools.keys())}"

        try:
            result = await asyncio.wait_for(
                tool.execute(tool_input),
                timeout=float(os.getenv("AGENT_TOOL_TIMEOUT", "30")),
            )
            return result
        except asyncio.TimeoutError:
            return f"工具调用超时（{os.getenv('AGENT_TOOL_TIMEOUT', '30')}秒），已跳过"
        except Exception as e:
            return f"工具执行出错: {str(e)}"


# ═══════════════════════════════════════════════════════════
# 内置工具
# ═══════════════════════════════════════════════════════════


class SearchTool(Tool):
    """知识库检索工具 — 封装 RAG 检索能力"""

    name = "search"
    description = "在知识库中检索相关文档内容。当需要查找具体信息、数据或政策时使用此工具。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询词，应具体明确",
            },
        },
        "required": ["query"],
    }

    def __init__(self, rag_instance=None, query_mode: str = "hybrid"):
        """
        Args:
            rag_instance: RAGAnything 实例（提供 aquery 方法）
            query_mode: 检索模式 "rrf" | "hybrid" | "local" | "global" | "naive"
        """
        self.rag = rag_instance
        self.query_mode = query_mode

    async def execute(self, input: dict) -> str:
        query = input.get("query", "")
        if not query:
            return "搜索失败：查询词不能为空"

        if self.rag is None:
            return "搜索失败：知识库未初始化"

        try:
            result = await self.rag.aquery(
                query,
                mode=self.query_mode,
                only_need_context=True,
                enable_rerank=False,
                chunk_top_k=40,
                top_k=60,
                max_entity_tokens=3000,
                max_relation_tokens=2000,
                max_total_tokens=16000,
            )
            if not result or not result.strip():
                return "知识库中未找到相关信息"
            # 截断过长上下文
            if len(result) > 8000:
                result = result[:8000] + "\n...(内容过长，已截断)"
            return result
        except Exception as e:
            return f"搜索出错: {str(e)}"


class CalculatorTool(Tool):
    """四则运算安全求值工具"""

    name = "calculator"
    description = "执行数学计算（四则运算、幂运算、平方根等）。支持运算符: + - * / ** // %。支持函数: sqrt, pow, abs, round, min, max, sum。"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式，例如 '123 * 456 + 789' 或 'sqrt(144) + pow(2, 10)'",
            },
        },
        "required": ["expression"],
    }

    # 安全白名单
    _SAFE_GLOBALS: dict[str, Any] = {
        "__builtins__": {},
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "sqrt": _math.sqrt,
        "sin": _math.sin,
        "cos": _math.cos,
        "tan": _math.tan,
        "log": _math.log,
        "log10": _math.log10,
        "pi": _math.pi,
        "e": _math.e,
        "ceil": _math.ceil,
        "floor": _math.floor,
        "int": int,
        "float": float,
    }

    # 禁止的关键词
    _FORBIDDEN = [
        "__", "import", "exec", "eval", "open", "compile",
        "globals", "locals", "getattr", "setattr", "delattr",
        "os.", "sys.", "subprocess", "socket", "http",
        "class", "lambda", "yield", "async", "await",
    ]

    async def execute(self, input: dict) -> str:
        expression = input.get("expression", "").strip()
        if not expression:
            return "计算错误：表达式为空"

        # 安全检查
        expr_lower = expression.lower()
        for forbidden in self._FORBIDDEN:
            if forbidden in expr_lower:
                return f"表达式包含不允许的操作: {forbidden}"

        # 只允许安全字符
        safe_chars = set(
            "0123456789+-*/.() **//% <>=!&|^~," +
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
        )
        for ch in expression:
            if ch not in safe_chars and not ch.isspace():
                return f"表达式包含不允许的字符: '{ch}'"

        try:
            result = eval(expression, self._SAFE_GLOBALS, {})
            if isinstance(result, float):
                # 避免浮点误差
                if abs(result - round(result, 0)) < 1e-10:
                    result = int(round(result, 0))
                else:
                    result = round(result, 6)
            return str(result)
        except ZeroDivisionError:
            return "计算错误: 除以零"
        except Exception as e:
            return f"计算错误: {str(e)}"


class DatabaseQueryTool(Tool):
    """内部数据统计查询工具 — 只读查询 JSON 数据存储"""

    name = "database_query"
    description = (
        "查询 RAG 系统内部统计信息。支持: "
        "(1) 文档统计: 总数、按状态分组(processed/failed/handling)、按知识库分组; "
        "(2) 知识库列表: 所有 KB 名称、创建时间; "
        "(3) 实体/关系/块数量; "
        "(4) 智能体统计: 数量、名称列表; "
        "(5) 存储总览: 综合统计。"
        "使用中文关键词查询，例如 query='文档统计' 或 query='知识库列表'。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "要查询的统计类型。可选值: 文档统计, 知识库列表, "
                    "实体统计, 智能体统计, 存储总览, 全部"
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, kb_dir: str = "./rag_storage"):
        self.kb_dir = kb_dir
        self.project_dir = "."

    async def execute(self, input: dict) -> str:
        query_text = input.get("query", "").strip()
        try:
            return self._query_stats(query_text)
        except Exception as e:
            return f"数据库查询出错: {str(e)}"

    def _query_stats(self, query: str) -> str:
        """根据自然语言查询读取 JSON 文件并返回统计"""
        results: list[str] = []

        # ── 文档统计 ──
        if any(kw in query for kw in ("文档", "doc", "全部", "总览", "存储")):
            results.append(self._doc_stats())

        # ── 知识库列表 ──
        if any(kw in query for kw in ("知识库", "kb", "全部", "总览", "存储")):
            results.append(self._kb_list())

        # ── 实体/关系统计 ──
        if any(kw in query for kw in ("实体", "关系", "块", "entity", "relation", "chunk", "全部", "总览", "存储")):
            results.append(self._entity_stats())

        # ── 智能体统计 ──
        if any(kw in query for kw in ("智能体", "agent", "全部", "总览", "存储")):
            results.append(self._agent_stats())

        if not results:
            # 默认返回综合总览
            results = [
                self._doc_stats(),
                self._kb_list(),
                self._agent_stats(),
            ]

        return "\n\n".join(results)

    def _safe_read_json(self, path: str) -> dict:
        """安全读取 JSON，文件不存在返回空"""
        try:
            p = Path(path)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _doc_stats(self) -> str:
        """文档统计"""
        lines = ["## 文档统计"]
        # 默认 KB
        ds = self._safe_read_json(f"{self.kb_dir}/kv_store_doc_status.json")
        if ds:
            total = len(ds)
            by_status: dict[str, int] = {}
            total_chunks = 0
            for info in ds.values():
                st = info.get("status", "unknown")
                by_status[st] = by_status.get(st, 0) + 1
                total_chunks += info.get("chunks_count", 0)
            lines.append(f"- 总文档数: {total}")
            lines.append(f"- 总块数: {total_chunks}")
            for st, cnt in by_status.items():
                lines.append(f"  - {st}: {cnt} 个")
            # 最近处理的文档
            sorted_docs = sorted(
                ds.items(),
                key=lambda x: x[1].get("updated_at", ""),
                reverse=True,
            )
            lines.append("- 最近文档:")
            for doc_id, info in sorted_docs[:5]:
                fname = info.get("file_path", "?")
                st = info.get("status", "?")
                chunks = info.get("chunks_count", 0)
                lines.append(f"  - {fname} [{st}, {chunks} chunks]")
        # 全量文档
        fd = self._safe_read_json(f"{self.kb_dir}/kv_store_full_docs.json")
        if fd:
            lines.append(f"- 全量文档记录: {len(fd)} 条")
        return "\n".join(lines)

    def _kb_list(self) -> str:
        """知识库列表"""
        lines = ["## 知识库列表"]
        kb_meta = self._safe_read_json("rag_storage_kb_meta.json")
        if kb_meta:
            lines.append(f"- 总数: {len(kb_meta)}")
            for name, info in kb_meta.items():
                created = info.get("created", "")[:10]
                display = info.get("name", name)
                lines.append(f"  - {name}: {display} (创建于 {created})")
        return "\n".join(lines)

    def _entity_stats(self) -> str:
        """实体/关系/块统计"""
        lines = ["## 实体与关系统计"]
        entities = self._safe_read_json(f"{self.kb_dir}/kv_store_full_entities.json")
        relations = self._safe_read_json(f"{self.kb_dir}/kv_store_full_relations.json")
        chunks = self._safe_read_json(f"{self.kb_dir}/vdb_chunks.json")

        if entities:
            total_names = sum(
                len(v.get("entity_names", [])) for v in entities.values()
            )
            lines.append(f"- 实体类型数: {len(entities)}, 实体名称数: {total_names}")
        if relations:
            total_pairs = sum(
                len(v.get("relation_pairs", [])) for v in relations.values()
            )
            lines.append(f"- 关系类型数: {len(relations)}, 关系对数: {total_pairs}")
        if chunks:
            lines.append(f"- 向量块数: {len(chunks)}")
        return "\n".join(lines)

    def _agent_stats(self) -> str:
        """智能体统计"""
        lines = ["## 智能体统计"]
        agent_meta = self._safe_read_json("agent_meta.json")
        if agent_meta:
            agents = agent_meta.get("agents", [])
            lines.append(f"- 总数: {len(agents)}")
            for a in agents[:10]:
                lines.append(f"  - {a.get('name','?')} (模型: {a.get('llm_model','?')}, KB: {a.get('kb_name','?')})")
        return "\n".join(lines)


class WebSearchTool(Tool):
    """外部网页搜索工具"""

    name = "web_search"
    description = "搜索互联网上的公开信息。当知识库中没有相关信息时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
        },
        "required": ["query"],
    }

    def __init__(self):
        self._request_count = 0
        self._window_start = time.time()

    async def execute(self, input: dict) -> str:
        query = input.get("query", "")
        if not query:
            return "搜索失败：查询词不能为空"

        # ── 限流：10次/60秒 ──
        now = time.time()
        if now - self._window_start > 60:
            self._request_count = 0
            self._window_start = now
        if self._request_count >= 10:
            return "搜索请求过于频繁，请稍后再试"
        self._request_count += 1

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": "1",
                        "skip_disambig": "1",
                    },
                    headers={"User-Agent": "RAGAnything/1.0"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    # Abstract
                    if data.get("AbstractText"):
                        results.append(f"摘要: {data['AbstractText']}")
                    # Related Topics
                    for topic in data.get("RelatedTopics", [])[:5]:
                        if isinstance(topic, dict) and topic.get("Text"):
                            results.append(f"- {topic['Text']}")
                    if results:
                        return "\n".join(results[:5])
                    return "未找到相关搜索结果"

                return f"搜索服务返回异常: HTTP {resp.status_code}"
        except ImportError:
            return "搜索失败：httpx 未安装"
        except Exception as e:
            return f"搜索服务暂时不可用: {str(e)}"
