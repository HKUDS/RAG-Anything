# RAG-Anything 前端架构设计

## 1. 组件树

```plantuml
@startuml
skinparam packageBackgroundColor #F8F9FA
skinparam packageBorderColor #1A73E8
skinparam componentBackgroundColor #E8F0FE
skinparam componentBorderColor #4285F4
skinparam arrowColor #5F6368

package "App 根组件" {
  component "Sidebar\n侧边栏导航" as Sidebar
  component "Router\n路由分发" as Router
}

package "UploadPage\n文档上传" #LightYellow {
  component "DropZone\n拖拽上传区" as DropZone
  component "UrlInput\nURL导入" as UrlInput
  component "PasteArea\n粘贴内容" as PasteArea
  component "FileList\n文件列表" as FileList
  component "ProgressBar\n上传进度" as ProgressBar
}

package "KBPage\n知识库管理" #LightGreen {
  component "DocTable\n文档列表" as DocTable
  component "DocStatus\n状态卡片" as DocStatus
  component "DocStats\n统计概览" as DocStats
  component "GraphView\n知识图谱可视化" as GraphView
  component "DocDetail\n文档详情" as DocDetail
}

package "QueryPage\n智能查询" #LightCyan {
  component "ChatWindow\n对话窗口" as ChatWindow
  component "MessageBubble\n消息气泡" as MessageBubble
  component "ModeSwitch\n模式切换" as ModeSwitch
  component "SourceRef\n来源引用" as SourceRef
  component "QueryHistory\n查询历史" as QueryHistory
}

package "SettingsPage\n系统设置" #LightPink {
  component "ParserConfig\n解析器配置" as ParserConfig
  component "ModelConfig\n模型配置" as ModelConfig
  component "ChunkConfig\n切块参数" as ChunkConfig
  component "ToggleSwitch\n多模态开关" as ToggleSwitch
  component "CacheManager\n缓存管理" as CacheManager
}

package "MonitorPage\n监控面板" #Lavender {
  component "Timeline\n处理时间线" as Timeline
  component "MetricsCards\n性能指标卡" as MetricsCards
  component "LLMCalls\nLLM调用统计" as LLMCalls
  component "LiveLog\n实时日志" as LiveLog
}

Router --> UploadPage
Router --> KBPage
Router --> QueryPage
Router --> SettingsPage
Router --> MonitorPage

DropZone --> FileList
UrlInput --> FileList
PasteArea --> FileList
FileList --> ProgressBar

DocTable --> DocStatus
DocTable --> DocStats
DocTable --> GraphView
DocTable --> DocDetail

ChatWindow --> MessageBubble
ChatWindow --> ModeSwitch
ChatWindow --> SourceRef
ChatWindow --> QueryHistory

ParserConfig --> ModelConfig
ModelConfig --> ChunkConfig
ChunkConfig --> ToggleSwitch
ToggleSwitch --> CacheManager

Timeline --> MetricsCards
MetricsCards --> LLMCalls
LLMCalls --> LiveLog

@enduml
```

## 2. 数据流

```plantuml
@startuml
skinparam participantBackgroundColor #E8F0FE
skinparam participantBorderColor #4285F4
skinparam databaseBackgroundColor #FCE8E6
skinparam databaseBorderColor #EA4335
skinparam noteBackgroundColor #FFF9C4

actor "用户" as User
participant "React\nFrontend" as Frontend
participant "FastAPI\nServer" as Server
participant "RAGAnything\nPipeline" as RAG
database "rag_storage/\nKV Stores" as Storage
participant "千问/本地\nLLM API" as LLM

== 上传文档 ==
User -> Frontend: 拖拽/选择文件
Frontend -> Server: POST /api/upload\nmultipart/form-data
Server -> RAG: process_document_complete(file)
activate RAG
RAG -> RAG: Docling 解析
RAG -> LLM: 实体提取 ×N
RAG -> LLM: Embedding ×M
RAG -> Storage: 写入 KV + VDB
RAG --> Server: 完成/进度回调
deactivate RAG
Server --> Frontend: SSE 进度推送
Frontend --> User: 进度条更新

== 查询 ==
User -> Frontend: 输入问题
Frontend -> Server: POST /api/query\n{query, mode}
Server -> RAG: aquery(query, mode)
activate RAG
RAG -> Storage: 向量检索
RAG -> Storage: 图谱遍历
RAG -> LLM: 生成回答
RAG --> Server: 回答 + 来源
deactivate RAG
Server --> Frontend: {answer, sources}
Frontend --> User: 展示回答+引用

@enduml
```

## 3. 组件树

```plantuml
@startuml
skinparam componentBackgroundColor #E8F0FE
skinparam componentBorderColor #4285F4
skinparam arrowColor #5F6368

[App] --> [Router]

[App] --> [Sidebar]
[App] --> [ToastProvider]
[App] --> [WebSocketClient]

[Router] --> [UploadPage]
[UploadPage] --> [DropZone]
[UploadPage] --> [UrlInput]
[UploadPage] --> [PasteArea]
[UploadPage] --> [FileList]
[UploadPage] --> [ProgressCard]

[Router] --> [KnowledgeBasePage]
[KnowledgeBasePage] --> [StatsOverview]
[KnowledgeBasePage] --> [DocTable]
[KnowledgeBasePage] --> [DocDetailDrawer]
[KnowledgeBasePage] --> [GraphCanvas]

[StatsOverview] --> [DocCountCard]
[StatsOverview] --> [EntityCountCard]
[StatsOverview] --> [RelationCountCard]

[Router] --> [QueryPage]
[QueryPage] --> [ChatPanel]
[QueryPage] --> [QueryHistoryPanel]
[ChatPanel] --> [MessageList]
[ChatPanel] --> [ModeSelector]
[ChatPanel] --> [QueryInput]
[MessageList] --> [UserBubble]
[MessageList] --> [AIBubble]
[AIBubble] --> [SourceCitation]

[Router] --> [SettingsPage]
[SettingsPage] --> [ParserSelect]
[SettingsPage] --> [ModelConfigForm]
[SettingsPage] --> [ChunkSlider]
[SettingsPage] --> [MultimodalToggles]
[SettingsPage] --> [CacheActions]
[SettingsPage] --> [ApiTestButton]

[Router] --> [MonitorPage]
[MonitorPage] --> [TimelineView]
[MonitorPage] --> [MetricsGrid]
[MonitorPage] --> [LLMStatsChart]
[MonitorPage] --> [LogStream]
[MetricsGrid] --> [TotalDocs]
[MetricsGrid] --> [ProcessingRate]
[MetricsGrid] --> [AvgQueryTime]

@enduml
```

## 4. 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | 重定向到 /upload | 首页 |
| `/upload` | 文档上传 | 拖拽/文件夹/URL/粘贴四种方式 |
| `/knowledge` | 知识库管理 | 文档列表、图谱可视化、详情 |
| `/query` | 智能查询 | 对话式问答、多模式 |
| `/query/:id` | 查询详情 | 某次查询的完整对话 |
| `/settings` | 系统设置 | 解析器/模型/参数配置 |
| `/monitor` | 监控面板 | 实时状态、性能、日志 |
