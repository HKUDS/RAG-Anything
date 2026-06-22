## Context

当前 `agent_query_stream`（[agent.py:534](raganything/routers/agent.py#L534)）在普通 RAG 路径中通过 `instance.aquery(only_need_context=True)` 获取检索上下文 `ctx`。当知识库无匹配数据时，LightRAG 底层 `_build_query_context` 返回 `None`→`kg_query` 返回 `None`→`aquery_llm` 返回 fail_response dict→`aquery` 提取 `PROMPTS["fail_response"]` 即 `"Sorry, I'm not able to provide an answer to that question.[no-context]"`。

现有检测逻辑 `_has_chunks = "[来源 " in ctx and len(ctx.strip()) > 200`（line 588）存在两个盲区：
1. fail_response 不含 `"[来源 "` 但 `ctx.strip()` 为 truthy → 触发 warning 但仍将 fail_response 作文本传给 LLM
2. KB 有实体/关系但无 text chunks 时，context 也不含 `"[来源 "` → 同样问题

AgenticRAG 路径（CoT）虽在 line 399 有 try-except 兜底，但未显式检测空上下文，失败静默。

## Goals / Non-Goals

**Goals:**
- 在 `agent_query_stream` 中可靠检测"检索无结果/无效上下文"场景
- 检测到空上下文时向用户反馈明确信息 + 降级到 bypass 模式
- 保持与 LightRAG 现有 fail_response 约定的兼容性

**Non-Goals:**
- 不修改 LightRAG 上游代码（本仓库不控制 LightRAG）
- 不改变 LightRAG 的 fail_response 格式
- 不改变 ReAct 路径的检索逻辑（ReAct 通过 SearchTool 自行检索，有自己的空结果处理）
- 不添加新的 API 端点

## Decisions

### Decision 1: 使用 `"[no-context]"` 标记检测 fail_response

**选择**: 检测 `ctx` 中是否包含 `"[no-context]"` 标记（LightRAG fail_response 的特征字符串）。

**备选**: 
- 直接比对 `ctx == PROMPTS["fail_response"]` — 但 LightRAG 的 `PROMPTS` 并非公开导出，且 import 路径不够稳定
- 检测 `ctx.strip()` 长度 < 100 — 但可能误杀合法的简短上下文

**理由**: `"[no-context]"` 是 LightRAG fail_response 中唯一非自然语言的特殊标记，误判概率极低，且不依赖 LightRAG 内部 API。

### Decision 2: 空上下文时降级为 bypass 模式

**选择**: 检测到空上下文后，不将 fail_response 传给 LLM，而是切换到 bypass 模式（`agent_mode="bypass"`），让 LLM 用自己的知识回答并告知用户"知识库中暂无相关数据"。

**备选**:
- 直接返回错误/提示给前端 — 用户体验不佳，用户期待获得某种回答
- 静默替换为空白上下文 — LLM 可能胡编乱造而没有 warning

**理由**: bypass 模式是本项目已有的机制（[agent.py:597](raganything/routers/agent.py#L597) 已有 `_DEGRADED_HINT`），扩展利用此路径提供降级体验。LLM 回答前会收到"知识库中暂无相关数据"的系统提示，用户不会被误导。

### Decision 3: 在 ctx 获取后立即检测，而非在 prompt 组装时

**选择**: 在 `ctx = ctx_task.result()`（line 534）之后立即检测 fail_response，命中则跳过 Step 2 的检索上下文 prompt 组装，直接走 bypass 路径。

**理由**: 早检测避免将 fail_response 嵌入 prompt 组装逻辑，减少污染；也避免 `📋 检索到 {len(ctx)} 字符上下文` 的误导性 thinking 消息。

## Risks / Trade-offs

- **[风险] `[no-context]` 标记依赖 LightRAG 内部实现** → 缓解：此标记自 LightRAG 早期版本即存在，变更概率低；即使变更，检测失败仅回退当前行为（warning + degraded hint），不算回归
- **[风险] bypass 模式下 LLM 可能编造不存在的功能** → 缓解：bypass 路径在 system_prompt 中明确告知"知识库中暂无相关数据，使用自身知识回答并注明限制"
- **[权衡] CoT 路径已有 try-except** → 保持现状，CoT 路径的静默失败已在 proposal 中标记为可同步修复但不阻塞主逻辑
