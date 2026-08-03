## ADDED Requirements

### Requirement: 受控媒体根包含项目自有解析输出目录

系统 SHALL 将项目自有解析输出目录纳入受控媒体根，使这些目录中的图片可通过召回校验与 legacy 媒体交付。

#### Scenario: output 与 output_<kb> 目录图片通过召回校验

- **WHEN** 检索上下文、BM25/二元组扫描或图谱召回位于项目根下 `output` 或 `output_*` 目录中的图片路径
- **THEN** 路径校验 MUST 通过（图片后缀、真实文件、非符号链接）
- **AND** 不得以 `outside_controlled_root` 拒绝

#### Scenario: OUTPUT_DIR 指定的目录通过召回校验

- **WHEN** `OUTPUT_DIR` 环境变量指定了目录且候选路径位于其中
- **THEN** 路径校验 MUST 通过
- **AND** 相对路径 MUST 以项目根为基准绝对化后校验

#### Scenario: 项目外路径仍被拒绝

- **WHEN** 候选路径位于所有受控根之外
- **THEN** 校验 MUST 返回 `outside_controlled_root` 拒绝

#### Scenario: 交付保持所有权证据链

- **WHEN** 受控根内的图片路径被召回且需要交付
- **THEN** 系统 MUST 要求该精确路径出现在同一知识库的持久化 chunk 内容中（或匹配 ODL 媒体目录）
- **AND** 交付 MUST 通过 KB 绑定 grant 与 sha256 校验
