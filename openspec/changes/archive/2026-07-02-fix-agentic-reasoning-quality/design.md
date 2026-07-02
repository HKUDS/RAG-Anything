## Context

实测发现 ReAct 和 CoT 模式回答质量远不如普通 RAG 模式：
- ReAct：Agent 对"功能模块有哪些"直接 FINISH 反问用户
- CoT：完全使用 LLM 自带知识，未检索 KB

## Goals / Non-Goals

**Goals:**
- ReAct：强制首步 search，不允许在检索前 FINISH
- CoT：注入检索上下文，使推理基于 KB 内容

**Non-Goals:**
- 不修改 ReAct 的其他规则（step limit、duplicate detection 等）
- 不改变默认模式行为

## Decisions

### Decision 1: ReAct prompt 规则 2 从软约束改为硬约束

**现状** (agentic_rag.py:326):
```
2. 如果用户的问题需要知识库中的信息，第一步必须先调用 search 检索。
```

LLM 可以将此解读为"我认为这个问题不需要知识库信息 → 跳过 search"。

**修改后**:
```
2. 第一步必须调用 search 检索知识库。不得在检索前 FINISH 或反问用户。即使问题看似模糊，也要先用问题原文 search 一次。
```

**理由**: 这是 AgenticRAG 最核心的质量保障——不存在"不需要检索"的场景。如果 KB 真的没有相关信息，search 会返回"未找到"，Agent 再基于此 FINISH。

### Decision 2: CoT 改为先检索后推理

**现状**: server.py CoT 路径直接 `agentic.run(req.query)`，`_cot_loop` 无检索步骤。

**修改后**: server.py 先执行 `rag.aquery(mode="rrf", only_need_context=True)` → 将上下文传入 `agentic.run_with_context(query, context)` → `_cot_loop` 接收 context 并注入 prompt。

**替代方案**: 让 CoT 也注册 SearchTool 实现自主检索 → 但这会使 CoT 变成 ReAct，违背 CoT"纯推理"的设计初衷。CoT 的价值在推理深度，检索应先于推理完成。

### Decision 3: CoT prompt 改为检索增强

**现状**: user_prompt = `## 用户问题\n{query}\n\n请开始逐步推理。`

**修改后**（当 context 提供时）:
```
## 检索内容
{context}

## 用户问题
{query}

请基于上述检索内容逐步推理。每一步都引用检索中的具体事实。不要使用你自己的知识。
```
