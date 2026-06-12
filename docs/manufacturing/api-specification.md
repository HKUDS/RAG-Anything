# 智能制造专业智能体 — 接口规范文档

> **版本**: v1.0 | **状态**: 初稿 | **基础路径**: `/api/v1/manufacturing`

## 1. 认证方式

所有 API 请求需在 Header 中携带：
```
Authorization: Bearer <jwt_token>
X-Institution-ID: <institution_id>
```

## 2. 接口列表

### 2.1 知识图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/knowledge-graph/nodes` | 获取知识节点列表 |
| GET | `/knowledge-graph/nodes/{id}` | 获取节点详情 |
| POST | `/knowledge-graph/nodes` | 创建知识节点 |
| PUT | `/knowledge-graph/nodes/{id}` | 更新知识节点 |
| DELETE | `/knowledge-graph/nodes/{id}` | 删除知识节点 |
| GET | `/knowledge-graph/edges` | 获取边列表 |
| POST | `/knowledge-graph/edges` | 创建边 |
| GET | `/knowledge-graph/lineage/{node_id}` | 获取谱系树 |

### 2.2 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/knowledge-base/upload` | 上传多模态资源 |
| GET | `/knowledge-base/resources` | 搜索资源列表 |
| GET | `/knowledge-base/resources/{id}` | 获取资源详情 |
| POST | `/knowledge-base/clean` | 触发数据清洗 |
| POST | `/knowledge-base/copyright-review` | 提交版权审核 |

### 2.3 智能体

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/qa` | 文本问答 |
| POST | `/agent/video-locate` | 视频片段定位 |
| POST | `/agent/code-parse` | 代码解析 |
| POST | `/agent/fault-diagnosis` | 故障诊断（支持多轮） |

### 2.4 运维

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ops/health` | 健康检查 |
| GET | `/ops/metrics` | 监控指标 |
| GET | `/ops/dashboard` | 数据看板数据 |

## 3. 请求/响应示例

### 文本问答
```json
// POST /agent/qa
{
  "query": "数控铣削的切削参数如何选择？",
  "context": {"competition_track": "machining"}
}
// Response
{
  "answer": "...",
  "citations": [{"source_title": "...", "page": 42, "excerpt": "..."}],
  "confidence": 0.92,
  "processing_time_ms": 850
}
```

## 4. 错误码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限（如跨院校数据访问） |
| 404 | 资源不存在 |
| 429 | 请求频率超限 |
| 500 | 服务内部错误 |
