## 1. 独立媒体预算

- [x] 1.1 在智能体路由增加 `AGENT_MEDIA_RECALL_TIMEOUT` 安全解析（非法/NaN/无穷回退、最小 0.1s）和独立 media deadline，标准与 agentic 路径统一调用
- [x] 1.2 将受控媒体转换改为内部 deadline 感知的逐张校验，返回图片+超时状态；保留已验证 payload、传播取消、禁止后台遗留并保持路径安全与 3 张上限
- [x] 1.3 在 `.env.example` 与 `env.example` 声明默认 8 秒媒体预算

## 2. 会话摘要 Schema

- [x] 2.1 新增幂等 `027_agent_conversation_summary_columns.sql`，创建摘要列与部分索引
- [x] 2.2 更新 `scripts/pg_setup.py` 显式迁移清单，补入 `024` 至 `027`

## 3. 测试

- [x] 3.1 增加标准/CoT/ReAct 独立媒体预算、非法配置、部分结果、主动取消、无后台遗留和无本地路径泄露测试
- [x] 3.2 增加 `027` 双次执行、时间列部分索引、迁移清单 024-027 顺序和摘要仓库写读测试
- [x] 3.3 运行图片召回、deadline、媒体交付、摘要压缩及迁移定向回归

## 4. 迁移与收尾

- [x] 4.1 只读核验当前数据库后连续执行两次 `027`，验证两列、时间列部分索引与摘要写读闭环；不运行完整 `pg_setup.py`
- [x] 4.2 完成 apply 执行/审查/测试三专家复核，运行 `py_compile`、`git diff --check` 与 OpenSpec validate
- [x] 4.3 更新 `PROJECT_SUMMARY.md` 当前事实和近期任务记录并通过质量检查
