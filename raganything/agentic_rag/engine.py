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
import os
import re
import time
from typing import Any, Callable, Optional

# Data models + Tool ABC — extracted to tool_base.py (shared by engine ↔ tools)
from raganything.agentic_rag.tool_base import (
    ReasoningStep,
    AgentResult,
    StreamEvent,
    Tool,
)

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
        max_response_tokens: int = 4096,
        system_prompt_override: Optional[str] = None,
    ):
        """
        Args:
            llm_func: 异步 LLM 调用函数
            max_steps: 最大推理步数
            mode: 推理模式 "react" | "cot"
            system_prompt_override: 覆盖默认的 AI 助手角色身份 prompt。
                用于注入领域专家身份（如"智能制造教学专家"）。
                工具描述和推理格式指令保持不变。
        """
        self.llm_func = llm_func
        self.max_steps = max_steps
        self.mode = mode
        try:
            parsed_max_tokens = int(max_response_tokens)
        except (TypeError, ValueError):
            parsed_max_tokens = 4096
        self.max_response_tokens = max(512, min(16384, parsed_max_tokens))
        self.system_prompt_override = system_prompt_override
        self.tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        """注册工具"""
        if tool.name in self.tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self.tools[tool.name] = tool

    # ── Public API ─────────────────────────────────

    async def run(self, query: str, kb_ids: Optional[list[str]] = None) -> AgentResult:
        """执行 Agentic 查询（非流式，向后兼容）"""
        if self.mode == "react":
            return await self._react_loop(query)
        elif self.mode == "cot":
            return await self._cot_loop(query)
        else:
            raise ValueError(f"Unknown mode: {self.mode} (expected 'react' or 'cot')")

    async def run_with_context(self, query: str, context: str) -> AgentResult:
        """执行带预检索上下文的 CoT 推理。

        用于 CoT 模式：先由调用方（如 server.py）执行 RRF 检索获取上下文，
        再传入此方法进行基于检索内容的逐步推理。

        Args:
            query: 用户问题
            context: RRF 检索返回的上下文字符串
        """
        if self.mode != "cot":
            # 非 CoT 模式降级为普通 run
            return await self.run(query)
        return await self._cot_loop(query, context=context)

    async def run_stream(self, query: str) -> "AsyncIterator[StreamEvent]":
        """执行 Agentic 查询（流式）— FINISH 步 token-by-token 输出。

        Returns:
            AsyncIterator yielding StreamEvent:
            - type="thinking": 每步推理完成时（非 FINISH 步）
            - type="token": FINISH 步的逐 token 输出
            - type="done": 推理完成
        """
        if self.mode != "react":
            raise ValueError("run_stream() only supports mode='react'")

        start_time = time.time()
        trace: list[ReasoningStep] = []
        system_prompt, user_prompt = self._build_react_prompt(query)
        messages: list[dict] = []

        for step_num in range(1, self.max_steps + 1):
            step_start = time.time()

            # ── 调用 LLM（非流式，需完整解析 Thought/Action）──
            try:
                response = await self._call_llm_with_retry(
                    system_prompt, user_prompt, messages,
                    is_final_step=False,  # 非 FINISH 步用小 token 预算
                )
            except Exception as e:
                yield StreamEvent(
                    type="done",
                    content=f"推理过程出错: {e}",
                    total_steps=step_num,
                    answer=f"推理过程出错: {e}",
                )
                return

            # ── 解析输出 ──
            thought, action, action_input = self._parse_action(response)

            # ── 检查是否 FINISH ──
            if action.upper() == "FINISH":
                elapsed = (time.time() - step_start) * 1000
                answer = action_input.get("answer", thought) if action_input else thought
                # 若 2048 token 不足以产出答案（JSON 截断），补一次大 token 调用
                if not action_input or not action_input.get("answer"):
                    try:
                        response_full = await self._call_llm_with_retry(
                            system_prompt, user_prompt, messages,
                            is_final_step=True,
                        )
                        _, _, ai_full = self._parse_action(response_full)
                        answer = (ai_full.get("answer", thought) if ai_full else thought)
                    except Exception:
                        pass

                trace.append(ReasoningStep(
                    step_number=step_num,
                    thought=thought,
                    action="FINISH",
                    action_input=action_input,
                    observation="推理完成",
                    elapsed_ms=elapsed,
                ))

                # ── FINISH 步：用已生成的完整 answer 逐字流式输出 ──
                # 不发起第二次 LLM 调用，直接用第一次调用已生成的回答
                # 保证精度=单次完整 LLM 调用，速度=无额外调用开销
                for ch in answer:
                    yield StreamEvent(type="token", content=ch, step=step_num)
                    await asyncio.sleep(0)  # 让出事件循环，不阻塞

                yield StreamEvent(
                    type="done",
                    total_steps=step_num,
                    answer=answer,
                    elapsed_ms=(time.time() - start_time) * 1000,
                )
                return

            # ── 非 FINISH 步：执行工具 ──
            observation = await self._execute_tool_with_timeout(
                action, action_input or {}
            )
            elapsed = (time.time() - step_start) * 1000
            trace.append(ReasoningStep(
                step_number=step_num,
                thought=thought,
                action=action if action else None,
                action_input=action_input,
                observation=observation,
                elapsed_ms=elapsed,
            ))

            # ── 产出 thinking 事件 ──
            yield StreamEvent(
                type="thinking",
                step=step_num,
                thought=thought,
                action=action,
                observation=observation,
                elapsed_ms=elapsed,
            )

            # ── 拼接历史消息 ──
            remaining = self.max_steps - step_num
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": (
                f"[Step {step_num}/{self.max_steps}] Observation: {observation}\n\n"
                f"还剩 {remaining} 步。"
                f"{'这是最后一次机会，必须 FINISH。' if remaining == 0 else ''}\n"
                f"请继续推理。从 Thought 开始:"
            )})

            # ── 达到最大步数 ──
            if step_num >= self.max_steps:
                try:
                    final_response = await self._call_llm_with_retry(
                        system_prompt,
                        f"已达到最大步数限制({self.max_steps}步)。请基于已收集的信息给出最终回答。\n\n用户问题: {query}",
                        [],
                    )
                    full = final_response.strip() if isinstance(final_response, str) else str(final_response)
                except Exception:
                    full = "推理达到最大步数限制，无法生成最终回答。"
                yield StreamEvent(type="token", content=full)
                yield StreamEvent(
                    type="done",
                    total_steps=step_num,
                    answer=full,
                    elapsed_ms=(time.time() - start_time) * 1000,
                )
                return

        # Should not reach
        yield StreamEvent(
            type="done",
            answer="推理达到最大步数限制。",
            total_steps=self.max_steps,
            elapsed_ms=(time.time() - start_time) * 1000,
        )

    # ── ReAct Prompt 构建 ────────────────────────────

    def _build_react_prompt(self, query: str) -> tuple[str, str]:
        """构建 ReAct system prompt 和 user prompt"""
        tool_descriptions = "\n".join(
            f"- **{t.name}**: {t.description}\n  Parameters: {json.dumps(t.parameters, ensure_ascii=False)}"
            for t in self.tools.values()
        )

        tool_names = ", ".join(t.name for t in self.tools.values()) if self.tools else "无"

        role_identity = (
            self.system_prompt_override
            if self.system_prompt_override
            else "你是一个具备多步推理能力的 AI 助手。你可以使用工具来获取信息，然后逐步推理得出最终答案。"
        )

        system_prompt = f"""{role_identity}

## 可用工具
{tool_descriptions}

## 推理格式
你必须严格按照以下格式输出每一步：

Thought: <你的思考过程，分析当前需要什么信息，是否已有足够信息回答>
Action: <工具名称 或 FINISH>
Action Input: <JSON 格式的工具参数 或 最终答案>

## 规则
1. 每一步只能调用一个工具。
2. **第一步必须调用 search 检索知识库。** 不得在检索前 FINISH 或反问用户。即使问题看似模糊，也要先用问题原文 search 一次。
3. 每次收到 Observation 后，先判断：已有信息是否足以回答用户问题？如果是，立即 FINISH。
4. search 最多使用 2 次。第 2 次 search 后，无论结果如何必须 FINISH。
5. 如果 Observation 中的内容与之前重复，说明已无新信息，立即 FINISH。
6. Action 必须是以下之一: {tool_names}, FINISH
7. 只有在至少检索 1 次且仍然无法回答时，才能 FINISH 并说明"抱歉，知识库中未找到相关信息，建议补充更多背景描述"。
8. **FINISH 的回答必须严格基于检索到的 Observation 内容。** 每条事实都要能追溯到 Observation 中出现的原文。不得添加 Observation 中没有的信息，不得使用你自己的知识补充或编造。如果 Observation 中列出了6个模块，就只列出那6个，不要增减。
9. FINISH 的 Action Input 必须是完整的最终回答，不能是计划或说明。
10. 你必须用中文思考和回答。
11. **实体区分规则**：如果 Observation 中出现了名称相似的多个实体（如"开题答辩"和"毕业设计答辩"），必须仔细区分每个实体对应的属性值（如地点、时间），不得混淆。如果用户问的是"毕业答辩的地点"，注意区分"毕业答辩"（毕业设计答辩）和"开题答辩"的不同属性。回答时必须明确引用实体名称和对应的具体数值。
12. **原文引用与来源标注规则**：在 FINISH 回答中，每条事实性陈述后必须用 `[来源 文档名]` 标注。Observation 中每条信息都以 `[来源 文档名]` 标记了出处。引用原文时用引号嵌入（至少20字逐字复制）。示例：文章中说明系统包含六个模块[来源 毕业设计论文]。严禁使用 `[来源 N]`（数字编号）、"code"、"实体描述"、"entity_type"、"relationship"、"chunk_id"等系统内部术语。
13. **引用来源块**：FINISH 回答末尾必须附加参考文献块，格式：📚 参考来源，每行 `[来源 文档名] — "原文摘录..."`。文档名取自 Observation 中 `[来源 文档名]` 标记，不可编造。
14. **关联实体引用**：如果 Observation 中包含 `[关联实体]` 标注，在正文中用自然语句说明实体关系（如"实体A 与 实体B 之间存在'包含'关系"），并在参考文献块后附加关联实体摘要，格式：`- 实体A → 实体B（关系类型）`。无关联实体信息则省略。
15. **输出结构**：FINISH 回答必须按以下顺序组织：回答正文 → 📚 参考来源 → 关联实体摘要（如有）。不得省略任何必须的部分。
"""

        user_prompt = f"## 用户问题\n{query}\n\n现在请开始推理。从 Thought 开始:"

        return system_prompt, user_prompt

    # ── CoT Prompt 构建 ──────────────────────────────

    def _build_cot_prompt(self, query: str, context: str = "") -> tuple[str, str]:
        """构建 CoT (Chain-of-Thought) prompt。

        Args:
            query: 用户问题
            context: 可选的检索上下文。提供时注入 prompt 确保推理基于 KB 内容。
        """
        role_identity = (
            self.system_prompt_override
            if self.system_prompt_override
            else "你是一个具备逐步推理能力的 AI 助手。"
        )

        system_prompt = f"""{role_identity}

## 推理格式
请按以下格式逐步思考并回答：

思考步骤1: <第一步分析，引用检索内容中的具体事实>
思考步骤2: <第二步分析，引用检索内容中的具体事实>
...
最终回答: <综合各步骤后的完整答案，必须包含以下三个部分>
  回答正文：<清晰回答用户问题，每条事实性陈述后标注 [来源 文档名]>
  📚 参考来源：<列出所有引用的来源，格式：[来源 文档名] — "原文摘录...">
  关联实体摘要：（如有实体关系，用自然语句说明，格式：- 实体A → 实体B（关系类型））

## 规则
1. 每一步分析必须引用检索内容中的具体事实和数据，不得使用你自己的知识
2. **最终回答中的每条事实都必须标注 [来源 文档名] 标记，并追溯到检索内容的原文。** 禁止使用 [来源 N]（数字编号）。不得添加检索内容中没有的信息，不得使用你自己的知识补充或编造
3. 如果检索内容不足以回答问题，在最终回答中明确说明缺少什么信息
4. 最终回答必须基于前面的推理步骤和检索内容
5. 用中文思考和回答
6. **原文引用**：引用检索内容时用文档名标记来源（格式：`[来源 文档名]`），引文用引号嵌入原文（至少20字逐字复制）。严禁输出"code"、"实体描述"、"entity_type"、"relationship"等系统内部元数据术语。
7. **关联实体**：若检索内容包含 [关联实体] 标注，在回答中引用并用自然语句说明实体关系，末尾附加关联实体摘要。
"""
        if context:
            user_prompt = (
                f"## 检索内容\n{context}\n\n"
                f"## 用户问题\n{query}\n\n"
                f"请基于上述检索内容逐步推理。每一步都引用检索中的具体事实。"
                f"不要编造检索内容中没有的信息。如果检索内容中列出了 N 个条目，就只列出那 N 个，不要增减。"
                f"如果检索内容不足以回答问题，请明确说明。"
            )
        else:
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

            # ── 调用 LLM（非 FINISH 步用 1024 tokens 节省开销）──
            try:
                response = await self._call_llm_with_retry(
                    system_prompt, user_prompt, messages,
                    is_final_step=False,  # loop 中先小 token 预算调用
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
                # 若 2048 token 仍不足以产出答案（JSON 截断），补一次大 token 调用
                if not action_input or not action_input.get("answer"):
                    try:
                        response_full = await self._call_llm_with_retry(
                            system_prompt, user_prompt, messages,
                            is_final_step=True,
                        )
                        _, _, ai_full = self._parse_action(response_full)
                        if ai_full and ai_full.get("answer"):
                            answer = ai_full["answer"]
                    except Exception:
                        pass
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
        self, system_prompt: str, user_prompt: str, messages: list[dict],
        is_final_step: bool = False,
    ) -> str:
        """调用 LLM，带单次重试。

        Args:
            is_final_step: 是否为 FINISH 步。非 FINISH 步只需产出
                Thought+Action+JSON（~100-200 tokens），使用 max_tokens=1024
                以减少不必要的 token 预算开销。
        """
        max_tokens = self.max_response_tokens if is_final_step else min(2048, self.max_response_tokens)

        try:
            response = await self.llm_func(
                prompt=user_prompt,
                system_prompt=system_prompt,
                history_messages=messages,
                max_tokens=max_tokens,
                temperature=0.0,
            )
            if isinstance(response, str) and response.strip():
                return response.strip()
        except Exception:
            pass

        # Retry once (no sleep — immediate retry for transient failures)
        response = await self.llm_func(
            prompt=user_prompt,
            system_prompt=system_prompt,
            history_messages=messages,
            max_tokens=max_tokens,
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
                max_tokens=self.max_response_tokens,
                temperature=0.0,
            )
            return response.strip() if isinstance(response, str) else str(response)
        except Exception as e:
            return f"推理达到最大步数限制（{self.max_steps}步）。{str(e)}"

    # ── CoT Loop ────────────────────────────────────

    async def _cot_loop(self, query: str, context: str = "") -> AgentResult:
        """CoT 推理 — 逐步思考后汇总回答。

        Args:
            query: 用户问题
            context: 可选的检索上下文。提供时注入 prompt，确保推理基于 KB 内容。
        """
        trace: list[ReasoningStep] = []
        start_time = time.time()

        system_prompt, user_prompt = self._build_cot_prompt(query, context=context)

        try:
            response = await self.llm_func(
                prompt=user_prompt,
                system_prompt=system_prompt,
                history_messages=[],
                max_tokens=self.max_response_tokens,
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
# 内置工具 — extracted to tools.py (re-exported here for backward compat)
# ═══════════════════════════════════════════════════════════

from raganything.agentic_rag.tools import (  # noqa: F401, E402
    SearchTool,
    CalculatorTool,
    DatabaseQueryTool,
    WebSearchTool,
)

# Legacy inline definitions removed — see tools.py for:
# SearchTool, CalculatorTool, DatabaseQueryTool, WebSearchTool
#
# Original inline definitions were at lines 784-1146.
# Re-exported above via: from raganything.agentic_rag.tools import ...

# End of file — remaining content removed (was: SearchTool)
