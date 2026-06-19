## 1. Core Fix

- [x] 1.1 在 `raganything/config.py` 的 `RAGAnythingConfig` 中新增 `lightrag_language` 字段，默认值从环境变量 `LIGHTRAG_LANGUAGE` 读取，fallback 为 `"Chinese"`
- [x] 1.2 在 `raganything/raganything.py` 的 LightRAG 初始化段，向 `addon_params` 注入 `language`：`addon.setdefault("language", self.config.lightrag_language)`
- [x] 1.3 在 `.env` 中添加 `EMB_DIM=1024`（DashScope text-embedding-v3 的实际维度）
- [x] 1.4 在 `raganything/query/pipeline.py` 中添加路由逻辑：当 `only_need_context=True` 时，将非 RRF/非 graph 模式统一路由到 RRF 管道（绕过 LightRAG 内部查询的维度/语言/numpy 兼容性问题）

## 2. Verification

- [x] 2.1 语法检查：确认 `config.py`、`raganything.py`、`pipeline.py`、`kb_service.py` 编译无误
- [x] 2.2 功能验证：所有 6 种查询模式 (hybrid/local/global/naive/mix/rrf) 均返回 15 个来源的上下文
- [x] 2.3 现有测试回归：`pytest tests/` 406 passed, 3 skipped, 0 failed
