## 1. LLM 调用优化 — 分步 token 预算

- [x] 1.1 `_call_llm_with_retry()`: 新增 `is_final_step: bool = False` 参数，非 FINISH 步 max_tokens=1024，否则 4096
- [x] 1.2 `_react_loop()`: FINISH 分支调用传入 `is_final_step=True`，其它步骤传入 `False`
- [x] 1.3 `run_stream()`: 同 1.2，非 FINISH 步 `is_final_step=False`
- [x] 1.4 `_cot_loop()`: max_tokens 从 4096 降到 2048
- [x] 1.5 `_force_final_answer()`: 保持 max_tokens=4096，传入 `is_final_step=True`

## 2. LLM 调用优化 — 无阻塞重试

- [x] 2.1 `_call_llm_with_retry()`: 移除 retry 中的 `await asyncio.sleep(1)`，改为立即重试

## 3. SearchTool 轻量检索

- [x] 3.1 `SearchTool.__init__()`: 默认 `query_mode="rrf"`
- [x] 3.2 `SearchTool.execute()`: top_k 从 60 降到 30，max_total_tokens 从 16000 降到 8000
- [x] 3.3 `AgenticRAG.__init__()`: 新增 `agent_query_mode: str = "rrf"` 参数，透传给 SearchTool

## 4. 流式端点对齐

- [x] 4.1 `server.py` agent query stream: 构造 `SearchTool(instance, query_mode=query_mode)` 时，若 `query_mode` 为空则 fallback 到 `"rrf"`（`query_mode or "rrf"`）

## 5. 验证

- [ ] 5.1 重启服务，ReAct 模式查询，确认 steps 耗时 < 5s/步，总耗时 < 10s
- [ ] 5.2 CoT 模式查询，确认总耗时 < 8s
- [ ] 5.3 普通模式查询，确认行为不变（回归）
- [ ] 5.4 检查 ReAct 模式下 search tool 日志确认使用 rrf 模式
