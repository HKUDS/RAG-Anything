## 1. 默认值调整（参数达标）

- [x] 1.1 修改 `agent.py` 第 651 行：`CONVERSATION_MAX_ROUNDS` 默认值从 `"3"` 改为 `"10"`
- [x] 1.2 修改 `agent.py` 第 191 行：`CONVERSATION_SUMMARY_TRIGGER_ROUNDS` 默认值从 `"5"` 改为 `"3"`
- [x] 1.3 修改 `agent.py` 第 188 行：`CONVERSATION_SUMMARY_ENABLED` 默认值从 `"false"` 改为 `"true"`
- [x] 1.4 修改 `prompt_builder.py` 第 63 行：`conversation_summary` 的 `enabled` 默认从 `False` 改为 `True`
- [x] 1.5 修改 `prompt_builder.py` 第 306 行：`add_summary()` 方法中 `CONVERSATION_SUMMARY_ENABLED` 读取默认值从 `"false"` 改为 `"true"`

## 2. 压缩比校验机制

- [x] 2.1 在 `agent.py` 中新增环境变量读取：`CONVERSATION_COMPRESSION_RATIO`（默认 `0.60`）、`CONVERSATION_COMPRESSION_MAX_RETRIES`（默认 `2`）
- [x] 2.2 修改 `_call_summary_llm()` 函数签名，新增参数 `compression_ratio: float = 0.60` 和 `max_retries: int = 2`
- [x] 2.3 在 `_call_summary_llm()` 内部实现压缩比计算：`ratio = 1 - len(summary) / len(transcript)`
- [x] 2.4 实现重试循环：压缩比不达标时，以强化 prompt 重试 LLM 调用（最多 2 次）
- [x] 2.5 实现重试 prompt 强化策略：第 1 次追加压缩强度指令，第 2 次追加极限压缩指令
- [x] 2.6 实现重试耗尽后的优雅降级：记录警告日志，使用最后一次结果
- [x] 2.7 添加结构化日志：`[SUMMARY-COMPRESSION] input_chars=N, output_chars=M, ratio=X%, attempt=N/N, pass=true/false`
- [x] 2.8 更新 `_maybe_generate_summary()` 调用处，传递新的压缩比参数

## 3. 配置文档更新

- [x] 3.1 更新 `.env.example` 多轮对话段：`CONVERSATION_MAX_ROUNDS` 注释默认值 3→10
- [x] 3.2 更新 `.env.example` 摘要压缩段：`CONVERSATION_SUMMARY_ENABLED` 注释 false→true，trigger_rounds 5→3
- [x] 3.3 在 `.env.example` 摘要压缩段新增 `CONVERSATION_COMPRESSION_RATIO` 和 `CONVERSATION_COMPRESSION_MAX_RETRIES` 配置项

## 4. 测试验证

- [x] 4.1 验证默认值：不设置任何环境变量时，`CONVERSATION_MAX_ROUNDS` 生效为 10
- [x] 4.2 验证摘要自动启用：启动服务后，`CONVERSATION_SUMMARY_ENABLED` 默认生效为 true
- [x] 4.3 验证压缩比计算：构造已知长度输入/输出，确认比例计算正确
- [x] 4.4 验证重试流程：模拟 LLM 返回长摘要，确认触发重试和日志输出
- [x] 4.5 验证优雅降级：模拟 2 次重试均不达标，确认使用最后一次结果
- [x] 4.6 验证向后兼容：显式设置旧环境变量值（如 `CONVERSATION_MAX_ROUNDS=3`、`CONVERSATION_SUMMARY_ENABLED=false`），确认显式值优先于新默认值
