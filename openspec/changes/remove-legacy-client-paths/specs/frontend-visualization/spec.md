## MODIFIED Requirements

### Requirement: G 代码编辑器组件
系统 SHALL 在智能体页面的"代码解析"标签页中提供 G 代码语法高亮编辑器。

#### Scenario: 语法高亮
- **WHEN** 用户在编辑器中输入 G 代码
- **THEN** 系统 SHALL 对 G 指令（蓝色）、M 指令（绿色）、坐标值（橙色）、注释（灰色）应用不同颜色

#### Scenario: 风险实时标注
- **WHEN** 编辑器检测到高风险代码模式（如 G00 后紧跟负 Z 值）
- **THEN** 系统 SHALL 在行号旁显示警告图标，hover 显示风险说明

#### Scenario: 一键解析
- **WHEN** 用户点击"解析"按钮
- **THEN** 系统 SHALL 调用受 RBAC 保护的 `/api/autorepair/code/parse` 并在下方展示解析结果（行解释+风险列表）
