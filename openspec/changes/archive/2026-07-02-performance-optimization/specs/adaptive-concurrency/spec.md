# Spec: LLM 自适应并发

## ADDED Requirements

### Requirement: 滑动窗口错误率检测
系统 SHALL 维护最近 N 次 API 调用结果（N=10，可配置），当错误率超过阈值（30%）时自动将并发数减半。

#### Scenario: 触发降级
- **WHEN** 最近 10 次 API 调用中有 4 次以上失败
- **THEN** 并发数 SHALL 从当前值减半（最小为 1）

#### Scenario: 自动恢复
- **WHEN** 降级后连续 20 次 API 调用全部成功
- **THEN** 并发数 SHALL 恢复至原值

### Requirement: 并发级别配置
自适应并发 SHALL 支持通过环境变量配置阈值。

#### Scenario: 自定义阈值
- **WHEN** 设置 `ADAPTIVE_CONCURRENCY_ERROR_RATE=0.5`
- **THEN** 错误率超过 50% 才触发降级
