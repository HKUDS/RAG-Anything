## 1. 模板调整 (prompt.py + prompts_zh.py)

- [x] 1.1 修改 `prompt.py` 中 `table_chunk` 模板：将 `Analysis` 字段移到 `Structure` 之前，调整字段顺序和描述
- [x] 1.2 同步修改 `prompts_zh.py` 中 `table_chunk` 模板

## 2. 结构简化 (processor.py)

- [x] 2.1 在 `_apply_chunk_template()` 的 `content_type == "table"` 分支中，对 `table_body` 做预处理：从每个 cell 提取 `{row, col, text}` 三条信息，构建简化版结构
- [x] 2.2 对简化后的 `table_body` 做长度检查：超过 2000 字符时截断并标注

## 3. 验证

- [ ] 3.1 对"13.相关文件"使用 `force_reprocess=true` 重新处理
- [ ] 3.2 查询"毕业答辩的地点"，确认 RRF 返回的表格 chunk 中 `Analysis` 位于 `Structure` 之前
- [ ] 3.3 确认 LLM 回答返回 13216 而非 13220
