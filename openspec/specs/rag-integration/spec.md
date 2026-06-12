# RAG Integration

## Purpose

将智能制造专业智能体的 QA 引擎和故障诊断引擎与 RAG-Anything 检索引擎对接，实现真正的检索增强生成，并通过依赖注入模式保持模块独立性。

## Requirements

### Requirement: QA 引擎对接 RAG 检索
QA 引擎 SHALL 通过依赖注入方式接入服务器已有的 RAG-Anything 检索引擎实例，实现真正的向量+BM25 混合检索。

#### Scenario: 检索增强回答
- **WHEN** 用户通过 API 发起文本问答
- **THEN** QA 引擎 SHALL 先调用 RAG-Anything 检索引擎获取 Top-K 相关文档，再基于检索结果生成回答并附带来源引用

#### Scenario: 检索超时降级
- **WHEN** RAG 检索耗时超过 3 秒
- **THEN** 系统 SHALL 取消检索，降级为无检索模式，回答中注明"检索超时，回答可能不完整"

#### Scenario: 检索为空时的处理
- **WHEN** RAG 检索返回 0 条结果
- **THEN** 系统 SHALL 返回预定义降级消息"当前知识库未覆盖该问题"

### Requirement: 故障诊断引擎对接案例库
故障诊断引擎 SHALL 通过 FaultCaseLibrary 进行真实案例检索，替代当前的空案例库。

#### Scenario: 案例匹配诊断
- **WHEN** 用户发起故障诊断
- **THEN** 诊断引擎 SHALL 在 FaultCaseLibrary 中检索相似案例，基于匹配结果生成追问或诊断结论

#### Scenario: 案例库为空时的处理
- **WHEN** FaultCaseLibrary 中无任何案例
- **THEN** 诊断引擎 SHALL 告知用户"案例库暂无数据"，仅基于 LLM 知识提供通用建议并标注"仅供参考"

### Requirement: LLM 统一配置
制造智能体 LLM 配置 SHALL 复用服务器已有的 `LLM_BINDING_API_KEY`、`LLM_BINDING_HOST`、`LLM_MODEL` 环境变量，不要求额外配置。

#### Scenario: LLM 环境变量缺失
- **WHEN** 必需的环境变量未设置
- **THEN** 服务器启动 SHALL 打印警告日志，QA/诊断接口返回"LLM 服务未配置"错误
