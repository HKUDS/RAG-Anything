# KB Cache Invalidation

## Purpose

KB 实例缓存自动失效——每次获取 KB 实例时检测磁盘数据是否比内存缓存更新，自动触发重建，确保查询始终基于最新数据。

## ADDED Requirements

### Requirement: get_kb 自动检测磁盘更新

系统 SHALL 在每次 `get_kb()` 调用时检查 `kv_store_doc_status.json` 的修改时间，若磁盘数据比内存缓存创建时间更新，则清除缓存并重建 KB 实例。

#### Scenario: 磁盘数据比缓存新
- **WHEN** `get_kb("test")` 被调用
- **AND** `kb_instances["test"]` 已存在
- **AND** `kv_store_doc_status.json` 的 mtime 大于缓存创建时间
- **THEN** 系统调用 `finalize_storages()` 清理旧实例
- **THEN** 系统从 `kb_instances` 中移除旧实例
- **THEN** 系统重新创建 KB 实例并从磁盘加载最新数据
- **THEN** 记录 `INFO` 日志"缓存过期重建: {name}"

#### Scenario: 磁盘数据未变更
- **WHEN** `get_kb("test")` 被调用
- **AND** `kb_instances["test"]` 已存在
- **AND** `kv_store_doc_status.json` 的 mtime ≤ 缓存创建时间
- **THEN** 系统直接返回缓存的 KB 实例，不做重建

#### Scenario: doc_status 文件不存在
- **WHEN** `get_kb("test")` 被调用
- **AND** `kb_instances["test"]` 已存在
- **AND** `kv_store_doc_status.json` 文件不存在
- **THEN** 系统直接返回缓存的 KB 实例（无法比较，信任缓存）
