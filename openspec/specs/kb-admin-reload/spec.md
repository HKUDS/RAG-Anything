# KB Admin Reload

## Purpose

提供管理员 API 端点手动清除指定知识库的内存缓存，触发下次查询时从磁盘重新加载最新数据。

## ADDED Requirements

### Requirement: 管理员手动重载 KB 缓存

系统 SHALL 提供 `POST /admin/reload-kb/{kb_name}` 端点，允许具有 `settings:write` 权限的用户清除指定 KB 的内存缓存。

#### Scenario: 成功清除缓存
- **WHEN** 管理员调用 `POST /admin/reload-kb/test`
- **AND** `kb_instances["test"]` 存在
- **THEN** 系统调用 `finalize_storages()` 清理旧实例
- **THEN** 系统从 `kb_instances` 中移除 "test"
- **THEN** 返回 `{"status": "ok", "message": "KB 'test' 缓存已清除"}`

#### Scenario: KB 不在缓存中
- **WHEN** 管理员调用 `POST /admin/reload-kb/nonexistent`
- **AND** `kb_instances["nonexistent"]` 不存在
- **THEN** 返回 `{"status": "skipped", "message": "KB 'nonexistent' 不在缓存中"}`

#### Scenario: 权限不足
- **WHEN** 非管理员（无 `settings:write` 权限）调用此端点
- **THEN** 返回 HTTP 403 Forbidden
