# Spec: 前端智能轮询

## ADDED Requirements

### Requirement: 页面可见性检测
前端看板页面 SHALL 根据浏览器页面可见性状态控制数据轮询。

#### Scenario: 页面隐藏时停止
- **WHEN** 用户切换到其他浏览器标签页
- **THEN** 看板 SHALL 停止数据轮询

#### Scenario: 页面恢复时立即刷新
- **WHEN** 用户切回看板标签页
- **THEN** 看板 SHALL 立即执行一次数据刷新

### Requirement: 自适应轮询间隔
轮询间隔 SHALL 根据用户活跃度动态调整。

#### Scenario: 活跃时加速
- **WHEN** 最近 30 秒内有查询操作
- **THEN** 轮询间隔 SHALL 为 5 秒

#### Scenario: 空闲时减速
- **WHEN** 超过 60 秒无查询操作
- **THEN** 轮询间隔 SHALL 为 15 秒
