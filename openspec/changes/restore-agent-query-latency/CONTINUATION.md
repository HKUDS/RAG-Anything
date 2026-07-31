# 新对话续办：restore-agent-query-latency

继续执行 OpenSpec change `restore-agent-query-latency`，不要归档、不要提前勾选
未验证任务，也不要回退或覆盖现有未提交改动。

## 当前事实

- OpenSpec 进度为 `10/16`；未完成任务为 1.2、3.1、4.1、4.3、4.4、5.2。
- 后端最近已重启，监听 `0.0.0.0:8001`；开始前重新检查
  `GET http://127.0.0.1:8001/api/health`，不得复用旧 PID。
- `EMBEDDING_CACHE_ENABLED=false` 必须保持关闭。
- 已实现并通过定向回归的行为：缓存 query core、请求级 LLM/VLM ContextVar、
  revision/兼容指纹、RRF/BM25 deadline 与 single-flight、活动 reader 的媒体复用、
  查询阶段计时；KB 获取和租约登记在同一 KB 锁内，初始化等待超时不会取消共享初始化，
  KB 删除会阻断新查询并等待现有 lease 排空。
- 最近验证：定向后端 `89 passed, 1 warning`；OpenSpec strict、`py_compile`、
  `git diff --check`、`scripts/check_project_summary.py` 均通过。确定性微基准的
  20 cold + 50 warm 生成前 P95 为 0.021 秒，但它尚不是完整应用链路验收。
- `pytest tests -q` 仍在约 60% 后出现 pytest 捕获临时文件关闭，随后级联
  `ValueError: I/O operation on closed file`。先隔离该测试基础设施问题，不能把它
  归因于本 change，也不能因此宣称全量通过。

## 强制准备

1. 完整阅读 `PROJECT_SUMMARY.md`、`AGENTS.md`、本 change 的 proposal/design/specs/tasks，
   再检查 `git status --short`，保留所有无关脏改动。
2. 执行 OpenSpec apply 的调度要求：至少安排实现、独立审查、独立测试三类专家。
3. 任何代码改动前先复核 `raganything/services/kb_service.py`、
   `raganything/routers/agent.py`、`raganything/hybrid_search/__init__.py` 与对应测试。

## 剩余任务的执行顺序

### 1.2 完整阶段观测

- 在不改 HTTP/SSE payload 的前提下补齐 BM25 PostgreSQL 读取和索引构建的独立计时；
  核查 settings/quota、core acquire、每种 Agent 模式检索、媒体、LLM 首/末 token、
  持久化、提前返回、异常和客户端取消都恰好记录一次 outcome。
- Prometheus 标签仅允许有界 phase/outcome/cache/channel；日志仅可含 trace ID 与上述
  有界字段，不得含问题、答案、用户、路径、host 或密钥。
- 增加隐私及错误/取消计时测试后才勾选。

### 3.1 全模式 deadline

- 对 standard、retrieval-only、tag、CoT、ReAct/SearchTool、查询改写、图片描述、
  视觉检索、RRF/BM25 和媒体校验逐项确认使用同一个绝对 monotonic deadline。
- core acquire 的调用方超时只能脱离共享初始化；普通请求本地子任务可按既有约定取消并
  observe。不得用降低 Top K、关闭通道或截断答案满足时限。
- 增加逐模式超时测试，验证可用通道仍融合且 ContextVar、lease、handler、heartbeat
  恰好清理一次。

### 4.1 与 4.3 测试

- 覆盖：两个并发用户使用不同 LLM/VLM、权限范围和 RetrievalOptions 时共享 core 但不
  串模型、缓存或参数；revision/兼容指纹替换；LRU；取消；任务绑定 ingestion 不复用 core。
- 覆盖：活动 text chunk reader 的媒体复用；旧媒体所有权验证仍 fail-closed；SSE
  早退、空 LLM 响应、异常和断连释放 lease/上下文/日志 handler。
- 使用真实 `RAGAnything` 的不可哈希 dataclass 替身或等价断言，防止租约键回归。

### 4.4 真实链路确定性 benchmark

- 用确定性 provider、PG/chunk-reader 测试替身驱动实际 `acquire_query_kb`、RRF/BM25、
  媒体和 SSE 编排；不能只测 `asyncio.sleep()` 的独立 core。
- 验收：20 次 cold、50 次 warm、同 key 并发 single-flight；应用控制的生成前 P95
  <= 8 秒；固定 22 秒生成器的端到端 P95 <= 30 秒；warm core acquire P95 <= 100ms。
- 在 benchmark 脚本中写明真实 provider smoke 的前置条件与单独归因规则。

### 5.2 运行验收

- 先完成上述测试，再受控重启 8001 并验证健康端点 200。
- 使用授权的测试用户和可用 provider 执行 1 次 cold、至少 20 次 warm 实际 SSE 查询；
  记录不含内容的阶段时间、cache hit/miss、超时回收和 provider 时间。
- 若 provider 不可用、没有受权会话或网络条件不足，记录为外部阻塞，不要伪造结果，
  不勾选 5.2。

## 最终验证命令

```powershell
openspec validate restore-agent-query-latency --strict
.\.venv\Scripts\python.exe -m pytest -q <新增测试> <现有相关测试>
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m py_compile <受改模块>
git diff --check
.\.venv\Scripts\python.exe scripts\check_project_summary.py
```

仅当证据覆盖任务描述时，更新 `tasks.md` 勾选。完成后更新
`PROJECT_SUMMARY.md`，确保不超过 30 KiB、近期记录不超过 15 条，再进入独立复审与归档。
