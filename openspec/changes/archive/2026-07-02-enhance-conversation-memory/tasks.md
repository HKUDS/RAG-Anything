## 1. Phase 0: MEMORY.md 索引修复

- [x] 1.1 补全 MEMORY.md 索引：添加 `openspec-scheduling-integration` 和 `parallel-agent-code-review` 两个条目

## 2. Phase 1-2: PromptBuilder 统一管线

- [x] 2.1 新建 `raganything/services/prompt_builder.py`，实现 `ContextLayer` dataclass 和 `PromptBuilder` 类（含 `add_layer()`, `build()` 方法）
- [x] 2.2 实现分层 Token 预算分配逻辑：按 priority 升序组装，超预算从低优先级层截断
- [x] 2.3 在 `agent.py` 的 RAG 模式（L990-1037）接入 PromptBuilder，替换手动拼接
- [x] 2.4 在 `agent.py` 的 ReAct 模式（L560-579）接入 PromptBuilder
- [x] 2.5 在 `agent.py` 的 CoT 模式（L612-627）接入 PromptBuilder
- [x] 2.6 清理 agent.py 中图片上下文拼接的重复代码（统一由 PromptBuilder 的 image_context 层处理）
- [x] 2.7 新增 `CONVERSATION_CONTEXT_LAYER_CONFIG` 环境变量支持（JSON 格式，可覆盖各层 max_tokens 和 enabled）

## 3. Phase 3: 对话摘要压缩

- [x] 3.1 创建 migration 脚本 `migrations/009_conversation_summary.sql`：为 `agent_conversations` 表添加 `summary TEXT` 和 `summary_updated_at TIMESTAMPTZ` 字段
- [x] 3.2 在 `pg_agent_repo.py` 中新增 `pg_update_summary(thread_id, summary_text)` 和 `pg_get_summary(thread_id)` 函数
- [x] 3.3 在 `agent.py` 的 query stream 响应完成后，添加摘要触发检查逻辑（消息数 > 阈值 → 异步调用 `_maybe_generate_summary()`）
- [x] 3.4 实现 `_maybe_generate_summary(thread_id, existing_summary, new_messages)` 函数：调用 LLM 生成/更新摘要
- [x] 3.5 在 PromptBuilder 中实现 summary 层（priority=20）：若摘要存在则注入 `## 对话摘要\n{summary}` 块
- [x] 3.6 新增环境变量：`CONVERSATION_SUMMARY_ENABLED`（默认 false）、`CONVERSATION_SUMMARY_TRIGGER_ROUNDS`（默认 5）、`CONVERSATION_SUMMARY_MAX_TOKENS`（默认 1000）、`CONVERSATION_SUMMARY_LLM_MODEL`（默认同主模型）

## 4. 测试

- [x] 4.1 编写 PromptBuilder 单元测试：覆盖所有层组合、token 截断、disabled layer 跳过
- [x] 4.2 编写三种模式（RAG/ReAct/CoT）的 Prompt 对比测试：重构前后输出一致性
- [x] 4.3 编写摘要生成测试：触发条件、增量摘要、失败降级
- [x] 4.4 编写 Prompt 注入测试：摘要 + 近期消息双注入、无摘要降级为纯截断
- [x] 4.5 回归测试：确认现有 `test_conversation_memory` 相关测试仍然通过

## 5. 配置与文档

- [x] 5.1 更新 `.env.example`：添加 Phase 3 所有新增环境变量及说明
- [x] 5.2 验证 MEMORY.md 索引补全后两个记忆文件可被正确加载
