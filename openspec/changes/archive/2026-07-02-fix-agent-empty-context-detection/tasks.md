## 1. Core Detection Logic

- [x] 1.1 Add `_is_empty_context(ctx)` helper function at module level in `agent.py` that detects fail_response (`"[no-context]" in ctx`) or degraded context (no `"[来源 "` and `len(ctx.strip()) <= 200`)
- [x] 1.2 Add bypass-mode prompt construction logic: when empty context detected, build prompt telling LLM "知识库中暂无相关数据，使用自身知识回答并注明限制"

## 2. Normal RAG Path Fix (agent_mode=none)

- [x] 2.1 After `ctx = ctx_task.result()` (line ~534), call `_is_empty_context(ctx)` to detect empty context
- [x] 2.2 When empty context detected: emit thinking event `"知识库中暂无相关数据，使用自身知识回答"`, skip RAG prompt assembly, switch to bypass mode LLM call
- [x] 2.3 Ensure `done` event includes `fallback: true` when fallback occurred
- [x] 2.4 Keep existing `_has_chunks` check as double-safety for edge cases where context is non-empty but degraded

## 3. CoT Path Edge Case (agent_mode=cot)

- [x] 3.1 After `cot_context = await instance.aquery(...)` (line ~395-400), call `_is_empty_context(cot_context)` to detect empty context
- [x] 3.2 When empty context detected: set `cot_context = ""` and emit thinking event about fallback (the existing CoT logic already handles empty string gracefully)

## 4. Verification

- [x] 4.1 Unit-level verified: `_is_empty_context("Sorry...[no-context]")` returns True; manual runtime verification pending (requires running server + empty KB)
- [x] 4.2 Unit-level verified: `_is_empty_context("[来源 1] valid..."+padding)` returns False; manual runtime verification pending (requires running server + populated KB)
- [x] 4.3 Logic verified: fail_response path now returns `is_fallback=True` and bypasses the `_has_chunks`/warning path entirely; warning only fires for genuine degraded context with entities but no chunks
