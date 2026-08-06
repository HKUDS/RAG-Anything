## MODIFIED Requirements

### Requirement: Worker 子进程正确报告所有失败
系统 SHALL 在 worker 子进程 (`process_worker.py`) 中，当文档处理后的 `doc_status` 为 `failed` 或 `chunks_count` 为 0 时，以非零 exit code 退出；并且 embedding identity、KB workspace 冲突和 legacy 向量存储冲突 SHALL 在 LightRAG 初始化前以不可重试失败报告。

#### Scenario: doc_status 为 failed 时 worker exit 1
- **WHEN** LightRAG 内部将文档的 doc_status 标记为 `failed`
- **AND** worker 处理完成后检查 doc_status
- **THEN** worker SHALL 以 exit code 1 退出
- **AND** worker SHALL 在 stdout 输出包含 `ERROR` 的消息

#### Scenario: chunks_count 为 0 时 worker exit 1
- **WHEN** 文档处理完成后 doc_status 的 `chunks_count` 为 0
- **THEN** worker SHALL 以 exit code 1 退出（无论 status 字段为何值）

#### Scenario: embedding 或 workspace preflight 冲突
- **WHEN** snapshot identity 缺失/未知、KB 已登记不兼容 identity、检测到 legacy 向量表，或 workspace 被覆盖
- **THEN** worker SHALL 在初始化 RAG 存储前失败
- **AND** failure code SHALL identify the conflict, stage SHALL be `embedding_preflight`, and retryable SHALL be `false`

#### Scenario: 正常处理成功时 worker exit 0
- **WHEN** 文档处理完成后 doc_status 的 `status` 不为 `failed`
- **AND** `chunks_count > 0`
- **THEN** worker SHALL 以 exit code 0 退出
