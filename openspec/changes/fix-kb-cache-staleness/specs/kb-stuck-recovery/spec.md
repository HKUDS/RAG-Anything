# KB Stuck Recovery

## Purpose

定期扫描所有知识库，自动检测并修复卡在 "handling" 状态的实际已完成文档，防止前端永久显示"入库中"。

## ADDED Requirements

### Requirement: 周期扫描卡住文档

系统 SHALL 在服务器启动后每 300 秒扫描所有已注册 KB 的 doc_status，将满足恢复条件的文档自动标记为 completed。

#### Scenario: 发现可恢复的卡住文档
- **WHEN** 后台扫描任务运行
- **AND** 某 KB 的 `kv_store_doc_status.json` 中存在 status="handling" 的文档
- **AND** 该文档的 `metadata.processing_end_time` 已写入
- **THEN** 系统将该文档 status 修改为 "completed"
- **THEN** 清除该 KB 的内存缓存实例
- **THEN** 记录 `INFO` 日志"修复卡住文档: {kb}/{doc_id}"

#### Scenario: 无卡住文档
- **WHEN** 后台扫描任务运行
- **AND** 所有 KB 的 doc_status 中没有 status="handling" 的文档
- **THEN** 扫描静默完成，不做任何修改

#### Scenario: 扫描异常
- **WHEN** 后台扫描过程中发生异常（如文件读取失败）
- **THEN** 系统记录 `WARNING` 日志
- **THEN** 继续扫描下一个 KB，不中断整体流程

### Requirement: 启动时立即扫描

系统 SHALL 在服务器启动时立即执行一次卡住文档扫描，不等首次 300 秒周期。

#### Scenario: 启动扫描
- **WHEN** FastAPI 应用启动（lifespan startup）
- **THEN** 系统立即执行一次 `_recover_stuck_documents()` 扫描
- **THEN** 然后启动周期性后台任务（300 秒间隔）
