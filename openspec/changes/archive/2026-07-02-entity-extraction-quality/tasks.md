## 1. 配置层 — RAGAnythingConfig

- [x] 1.1 在 `RAGAnythingConfig` 中新增 `entity_types: str` 字段，默认 `""`，读取 `ENTITY_TYPES` 环境变量
- [x] 1.2 在 `RAGAnythingConfig` 中新增 `entity_extraction_min_degree: int` 字段，默认 `0`，读取 `ENTITY_EXTRACTION_MIN_DEGREE` 环境变量
- [x] 1.3 更新 `env.example` 添加 `ENTITY_TYPES` 和 `ENTITY_EXTRACTION_MIN_DEGREE` 注释

## 2. 实体类型白名单 — LightRAG addon_params 注入

- [x] 2.1 在 `_ensure_lightrag_initialized()` 中，当 `entity_types` 非空时，将解析后的实体类型列表注入 `lightrag_kwargs["addon_params"]["entity_types"]`
- [x] 2.2 确保 LightRAG 初始化时 `addon_params` 正确传递给 `extract_entities()`
- [x] 2.3 验证：配置 `ENTITY_TYPES=Part,Process,Material` 后 env var 正确读取，默认行为不变

## 3. 连通性过滤 — 孤立实体移除

- [x] 3.1 在 `processor.py` 中新增 `_filter_low_degree_entities()` 方法：遍历 `chunk_entity_relation_graph` 所有节点，移除 degree < `entity_extraction_min_degree` 的实体
- [x] 3.2 移除孤立实体时同步清理 `entities_vdb` 和 `full_entities` 中的对应条目
- [x] 3.3 保留被移除实体关联的 `text_chunks`（只清理实体，不删除文本）
- [x] 3.4 在文档处理流程中（`process_document_complete` 或实体入库后）调用 `_filter_low_degree_entities()`
- [x] 3.5 仅在 `entity_extraction_min_degree > 0` 时执行过滤，避免不必要的开销

## 4. 服务器设置 API

- [x] 4.1 在 `server.py` 的 `GET /api/settings` 响应中增加 `entity_types` 和 `entity_extraction_min_degree` 字段
- [x] 4.2 在 `server.py` 的 `SettingsUpdate` Pydantic 模型中增加对应字段
- [x] 4.3 在 `PUT /api/settings` 处理中，更新后写入环境变量并重建 RAG 实例

## 5. 前端设置页面

- [x] 5.1 在 `SettingsPage.jsx` 的"解析器"卡片下方新增"实体抽取"配置卡片
- [x] 5.2 添加 `entity_types` 文本输入框（placeholder: "如：Part, Process, Material"）
- [x] 5.3 添加 `entity_extraction_min_degree` 数字输入框（默认 0，提示"0=不过滤，1=移除孤立实体"）
- [x] 5.4 实现 `onChange` 即时保存（与现有 parser 选择器行为一致）

## 6. 验证测试

- [x] 6.1 测试默认行为不变：未配置时 LightRAG 使用默认实体类型，不做连通性过滤
- [x] 6.2 测试实体类型白名单：配置 `ENTITY_TYPES=Part,Material` 后，env var 正确传递到 config
- [x] 6.3 连通性过滤代码实现：`_filter_low_degree_entities()` 包含完整的 degree 检查 + graph/entities_vdb/full_entities 清理逻辑
- [x] 6.4 设置 API 代码实现：`SettingsUpdate` 模型、`GET/PUT /api/settings` 均已更新
- [x] 6.5 运行已有测试套件：27/27 passed，无回归
