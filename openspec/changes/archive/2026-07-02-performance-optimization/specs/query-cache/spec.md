# Spec: 查询结果缓存

## ADDED Requirements

### Requirement: 查询结果缓存
系统 SHALL 对相同查询文本在 TTL 内返回缓存结果，避免重复 RAG 检索和 LLM 调用。

#### Scenario: 缓存命中
- **WHEN** 用户在 60 秒内以完全相同文本重复查询
- **THEN** 系统 SHALL 直接返回上次结果，响应中添加 `X-Cache: HIT` 头

#### Scenario: 缓存过期
- **WHEN** 缓存条目超过 TTL（默认 60 秒）
- **THEN** 系统 SHALL 执行正常检索流程并更新缓存

#### Scenario: 强制刷新
- **WHEN** 查询携带 `?refresh=true`
- **THEN** 系统 SHALL 跳过缓存执行完整检索

### Requirement: 缓存容量限制
系统 SHALL 限制缓存条目数不超过 500 条，超出时淘汰最旧条目。

#### Scenario: LRU 淘汰
- **WHEN** 缓存达到 500 条上限且新查询不命中缓存
- **THEN** 系统 SHALL 移除最早添加的条目
