# Spec: 制造智能体 KB 选择器

## ADDED Requirements

### Requirement: 制造页面独立 KB 选择
制造智能体页面 SHALL 提供独立的 KB 选择器，切换后制造智能体的检索范围随之变更。

#### Scenario: 切换 KB
- **WHEN** 用户在制造智能体页面切换 KB
- **THEN** 制造智能体 QA/诊断的后端检索 SHALL 使用选中的 KB

#### Scenario: 默认 KB
- **WHEN** 用户首次进入制造智能体页面
- **THEN** KB 选择器 SHALL 默认为当前活跃 KB

### Requirement: API kb 参数
制造 API 端点 SHALL 支持 `?kb=` 查询参数，指定检索目标 KB。

#### Scenario: 指定 KB
- **WHEN** 请求 `/api/manufacturing/qa?kb=111`
- **THEN** 后端 SHALL 使用 KB 111 的向量库进行检索
