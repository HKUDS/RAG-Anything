# Frontend Visualization

## Purpose

为智能制造专业智能体前端提供专业可视化组件，包括 D3 知识图谱力导向图、G 代码语法高亮编辑器和视频片段播放器，提升制造领域数据交互体验。

## Requirements

### Requirement: D3 知识图谱力导向图
系统 SHALL 在知识库页面的"知识图谱"标签页中集成 D3 力导向图，展示赛项知识节点及其关系。

#### Scenario: 图谱渲染
- **WHEN** 用户切换到"知识图谱"标签
- **THEN** 系统 SHALL 渲染包含所有知识节点的力导向图，节点按类型着色（知识点/赛题/技能），边按关系类型显示不同线型

#### Scenario: 节点交互
- **WHEN** 用户点击图谱中的某个节点
- **THEN** 系统 SHALL 高亮该节点及其邻接节点，并在侧边栏展示节点详情和谱系信息

#### Scenario: 缩放与拖拽
- **WHEN** 用户滚轮缩放或拖拽画布
- **THEN** 图谱 SHALL 平滑缩放/平移，节点位置随之更新

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
- **THEN** 系统 SHALL 调用 `/api/manufacturing/code/parse` 并在下方展示解析结果（行解释+风险列表）

### Requirement: 视频片段播放器
系统 SHALL 提供视频片段预览和跳转播放组件，用于展示视频定位结果。

#### Scenario: 视频片段列表
- **WHEN** QA 回答包含视频片段引用
- **THEN** 系统 SHALL 展示片段缩略图列表，每个片段显示起止时间戳和匹配度

#### Scenario: 时间戳跳转
- **WHEN** 用户点击视频片段
- **THEN** 播放器 SHALL 跳转到该片段的起始时间开始播放

### Requirement: 看板实时更新
系统 SHALL 在看板页面提供知识库导入进度指示。

#### Scenario: 导入进度
- **WHEN** 数据导入脚本正在运行
- **THEN** 看板 SHALL 每 5 秒轮询知识库统计 API，展示节点/文档数量的实时变化
