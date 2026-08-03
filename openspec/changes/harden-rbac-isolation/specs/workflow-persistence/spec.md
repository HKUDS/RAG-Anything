# Workflow Persistence (Delta)

## MODIFIED Requirements

### Requirement: 运行记录属主隔离
工作流运行列表/详情 SHALL 按属主隔离：非管理员仅能看到自己的运行；`/ws/workflow-run/{run_id}` 订阅前 SHALL 校验运行属主。

#### Scenario: 非管理员读取他人运行
- **WHEN** 具有 `workflow:read` 的非管理员用户查询他人工作流的运行列表或详情，或订阅他人运行的 WebSocket
- **THEN** 服务端 SHALL 不返回他人运行数据（列表为空或 403/404），WebSocket 拒绝订阅
