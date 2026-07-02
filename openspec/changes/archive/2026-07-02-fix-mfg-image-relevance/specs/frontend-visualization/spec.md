# Frontend Visualization (Delta)

## MODIFIED Requirements

### Requirement: 看板实时更新
系统 SHALL 在看板页面提供知识库导入进度指示。当看板无数据时，SHALL 展示包含三步工作流指引（导入数据 → 构建知识图谱 → 开始智能问答）的引导卡片。

#### Scenario: 导入进度
- **WHEN** 数据导入脚本正在运行
- **THEN** 看板 SHALL 每 5 秒轮询知识库统计 API，展示节点/文档数量的实时变化

#### Scenario: 首次使用空状态
- **WHEN** 看板所有统计指标为 0 或空
- **THEN** 看板 SHALL 展示引导卡片，包含"导入知识库数据"（跳转至知识库页面）、"浏览知识图谱"（跳转至知识图谱页）、"启动智能问答"（跳转至智能体页）三个操作入口

#### Scenario: 有数据时隐藏引导
- **WHEN** 看板加载完成后统计指标非全零
- **THEN** 看板 SHALL 隐藏引导卡片，正常展示数据统计区域

## ADDED Requirements

### Requirement: 智能体页面空状态组件
制造智能体页面的 QA、Code Parser、Fault Diagnosis 各 Tab 在无内容时 SHALL 展示功能说明、示例操作入口。

#### Scenario: QA Tab 空状态
- **WHEN** 用户首次进入 QA Tab（无历史消息）
- **THEN** 页面 SHALL 展示"输入制造领域问题"提示文字和 3 个可点击示例问题按钮，点击示例问题后直接发送查询

#### Scenario: Fault Diagnosis Tab 空状态
- **WHEN** 用户首次进入故障诊断 Tab（无诊断会话）
- **THEN** 页面 SHALL 展示"描述设备故障现象"提示文字和 3 个可点击示例故障描述按钮
