## Context

LightRAG 内部有三处使用 `global_config["addon_params"].get("language", DEFAULT_SUMMARY_LANGUAGE)`：
1. 关键词提取（`extract_keywords_only`）— 决定从查询中提取的关键词语言
2. 实体提取（`extract_entities`）— 决定索引时提取的实体描述语言
3. 摘要生成（`generate_summary`）— 决定回答摘要语言

`DEFAULT_SUMMARY_LANGUAGE = "English"` 定义在 `lightrag/constants.py:14`。RAGAnything 初始化 LightRAG 时，仅向 `addon_params` 注入了 `entity_types`，未注入 `language`，导致默认使用 "English"。

当用户用中文提问时，LLM 按 "English" 指令提取英文关键词（如 "System, Function modules"），然后用这些英文关键词在中文实体库（如 "智能筛查系统"、"系统功能测试"）中做向量检索。余弦相似度阈值 0.2 下，跨语言向量匹配几乎不可能成功，返回 0 结果。

## Goals / Non-Goals

**Goals:**
- 在 LightRAG 初始化时注入 `addon_params.language = "Chinese"`，使关键词提取语言与实体库语言一致
- 支持通过环境变量 `LIGHTRAG_LANGUAGE` 覆盖默认值

**Non-Goals:**
- 不修改 LightRAG 库本身的代码（仅通过 addon_params 配置）
- 不影响 RRF 查询模式（RRF 不使用 LightRAG 的关键词提取）

## Decisions

### Decision 1: 在 raganything.py 初始化处注入 language

**方案**：在 `raganything/raganything.py` 第 429 行附近（与注入 `entity_types` 同一位置），追加：

```python
addon = lightrag_params.setdefault("addon_params", {})
# ... existing entity_types injection ...
addon.setdefault("language", self.config.lightrag_language)
```

**理由**：
- 与现有 `entity_types` 注入模式一致
- 最小改动（2 行代码）
- 不影响初始化流程的其他部分

### Decision 2: 默认值设为 "Chinese"

**方案**：默认 `LIGHTRAG_LANGUAGE=Chinese`。

**理由**：
- 项目目标用户是中文用户，知识库文档为中文
- 从 "English" 改为 "Chinese" 修复了核心失配问题
- 英文用户可通过环境变量覆盖

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 英文知识库用户受默认值影响 | 设置 `LIGHTRAG_LANGUAGE=English` 即可恢复 |
| 已缓存的英文关键词可能需要清理 | LightRAG 的 llm_response_cache 会随新查询自动刷新 |

## Open Questions

无。修复方案明确且最小化。
