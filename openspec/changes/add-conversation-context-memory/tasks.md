## 1. ConversationManager 核心实现

- [x] 1.1 在 `raganything/query.py` 中创建 `ConversationManager` 类，含数据结构 (`Thread`, `ThreadSummary`, `ConversationContext`) 和 `__init__`(storage_path, max_rounds, max_tokens)
- [x] 1.2 实现 `_load()` / `_save()` 方法，使用 `asyncio.Lock` 保护 `conversations.json` 并发读写
- [x] 1.3 实现 `get_or_create_thread(user_id, thread_id, title)` — 按 user_id+thread_id 查找或创建，自动截取 title 前 50 字符
- [x] 1.4 实现 `add_message(thread_id, role, content)` — 追加消息、更新 updated_at、触发 save；单条消息 max 10000 字符
- [x] 1.5 实现 `get_context(thread_id, current_query)` — 提取最近 max_rounds 轮历史，按 max_tokens 截断，返回 `ConversationContext`
- [x] 1.6 实现 `list_threads(user_id)` — 返回该用户的会话摘要列表（id, title, message_count, updated_at），按更新时间倒序
- [x] 1.7 实现 `delete_thread(thread_id)` — 删除会话，返回 bool
- [x] 1.8 实现每用户最多 50 个会话的限制检查

## 2. Server API 端点

- [x] 2.1 在 `server.py` 中初始化全局 `ConversationManager` 单例，在 `startup_event` 中加载，使用环境变量 `CONVERSATIONS_FILE`（默认 `./conversations.json`）
- [x] 2.2 新增 `GET /api/conversations` 端点 — 调用 `list_threads(current_user["id"])` 返回会话列表
- [x] 2.3 新增 `POST /api/conversations` 端点 — 接收 `{title}`，调用 `get_or_create_thread()`，返回 thread 信息
- [x] 2.4 新增 `DELETE /api/conversations/{thread_id}` 端点 — 调用 `delete_thread()`，校验归属权（查询时验证 user_id 匹配）
- [x] 2.5 在 `QueryRequest` Pydantic 模型中添加可选字段 `thread_id: str = ""`
- [x] 2.6 在 `AgentQueryRequest` 中添加可选字段 `thread_id: str = ""`（已有）

## 3. Query 流程集成

- [x] 3.1 在 `/api/query` 端点中，当 `thread_id` 非空时调用 `conversation_manager.get_context()` 获取 `ConversationContext`
- [x] 3.2 将 `conversation_history` 注入 final prompt，在检索文档区域前插入对话历史区
- [x] 3.3 在 prompt 中增加对话历史区：`## 对话历史\n{history}\n\n## 检索内容\n{ctx}\n\n## 问题\n{query}`
- [x] 3.4 在 `rewrite_query()` 调用处传入 `conversation_history` 作为 `history` 参数
- [x] 3.5 在 `/api/query/stream` 端点中同样注入对话历史
- [x] 3.6 LLM 生成完成后，调用 `add_message()` 保存本轮对话
- [x] 3.7 查询响应中返回 `thread_id` 字段
- [x] 3.8 更新 `query_history` 记录以包含 `thread_id` 字段

## 4. Prompt 模板扩展

- [x] 4.1 在 `raganything/prompts_zh.py` 中新增 `CONVERSATION_CONTEXT_TEMPLATE` 中文模板变量
- [x] 4.2 在 `raganything/prompt.py` 中新增 `CONVERSATION_CONTEXT_TEMPLATE` 英文模板变量
- [x] 4.3 确保 `only_need_context=True` 模式（仅检索不回生成）不注入历史区（已在 server.py 中分离处理）

## 5. 配置与测试

- [x] 5.1 添加环境变量 `CONVERSATION_MAX_ROUNDS`（默认 3）、`CONVERSATION_MAX_TOKENS`（默认 2000）、`CONVERSATIONS_FILE`（默认 `./conversations.json`）
- [x] 5.2 添加环境变量 `CONVERSATION_MAX_PER_USER`（默认 50）
- [x] 5.3 编写单元测试：验证 ConversationManager 的 CRUD、消息追加、历史截断、用户隔离 (14 tests, all passing)
- [x] 5.4 编写集成测试：验证多轮对话中代词指代消解（历史注入 prompt 逻辑）
- [x] 5.5 手动验证：现有无 `thread_id` 的单轮查询行为不受影响（向后兼容，56 existing tests pass）
