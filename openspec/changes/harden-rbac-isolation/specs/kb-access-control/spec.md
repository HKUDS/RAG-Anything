# KB Access Control (Delta)

## MODIFIED Requirements

### Requirement: 视觉向量设置读写分离
`GET /kb/{kb}/vision-settings` SHALL 仅需 `kb:read` 与 KB 可见性；`PUT /kb/{kb}/vision-settings` SHALL 保持 `kb:write` 或 KB 属主。

#### Scenario: 有 kb:read 的可见 KB
- **WHEN** 用户具有 `kb:read` 且对该 KB 可见
- **THEN** 读取视觉向量设置 SHALL 返回 200

### Requirement: KB 删除在 PG 模式下可用
删除知识库 SHALL 在 PG 存储模式下正常完成（含空 KB 与含文档 KB），返回 200 并清理元数据、目录与 PG 行。

#### Scenario: PG 模式删除知识库
- **WHEN** 管理员或有 `kb:delete` 的属主删除知识库
- **THEN** 删除请求 SHALL 返回 200，且不因“删除中状态重新加载存储”而失败
