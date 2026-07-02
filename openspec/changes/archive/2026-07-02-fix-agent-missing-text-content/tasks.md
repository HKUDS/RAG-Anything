## 1. Core Backfill Logic (agent_mode=none 路径)

- [x] 1.1 在 `agent.py` bigram 扫描循环中同步收集文本内容：for 循环中新增 `scored_texts` 列表，存储 `(chunk_id, content, score, doc_name)` 元组
- [x] 1.2 实现 `_build_backfill_context()` 辅助函数：接收 scored_texts 列表，去重（按 chunk_id），格式化 `[来源 doc_name (回填片段{n})]\n{content}`，截断到 4800 字符上限
- [x] 1.3 将 `_build_backfill_context()` 的输出追加到 `ctx` 变量（`ctx = ctx + "\n\n" + backfill_text`）
- [x] 1.4 新增 `[IMG-FALLBACK]` 日志中追加回填统计信息：`+回填 {N} 文本片段 ({M} 字符)`

## 2. Adjust Fallback Detection Order (agent_mode=none 路径)

- [x] 2.1 将 `is_fallback = _is_empty_context(ctx)` 调用从 bigram 扫描之前移至之后，使用富化后的 ctx
- [x] 2.2 当 ctx 为真正空（fail_response/None/空字符串）时不运行 bigram 扫描（快速返回），当 ctx 有内容（即使是薄上下文）时运行 bigram 扫描 + 回填
- [x] 2.3 在 bigram 回填后重新调用 `_is_empty_context()` 确认最终状态（如果回填成功追加内容 → 可能从 fallback 转为正常）

## 3. Fix agent_mode=react 路径

- [x] 3.1 在 react 路径的 trace 聚合阶段（`all_retrieved_text`），将 bigram 扫描找到的文本内容也注入 `all_retrieved_text`
- [x] 3.2 确保 react 路径的 `_agent_ctx` 变量也包含回填文本，使 citation 回退能扫描到

## 4. Verification & Edge Cases

- [x] 4.1 语法验证：确认 agent.py 无语法错误，helper 函数可正常导入
- [ ] 4.2 集成测试：发送查询到有文档图片的知识库，验证返回结果中既有图片也有对应文本（需运行实际服务器验证）
- [ ] 4.3 边界测试：kv_store_text_chunks.json 为空、bigram score 全 0、回填文本超过 4800 字符截断（需运行实际服务器验证）
- [x] 4.4 确认 agent_mode=cot 路径——CoT 路径在检索前通过 `_is_empty_context(cot_context)` 做检测，空上下文直接返回 fallback 无图片。CoT 路径无 bigram 图片扫描逻辑（只在 react 和 none 路径有），因此不存在"有图片但无文本"的不一致问题。暂不需要修复。
