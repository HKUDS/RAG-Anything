## 1. QAEngine.answer() 两级策略

- [x] 1.1 Tier 1：RRF 检索 context → ≥200 字符直接 prompt+LLM → 返回 AgentResponse
- [x] 1.2 置信度判断：≥50 且 <200 字符 → 直接生成后评估置信度 → <0.3 回退 AgenticRAG
- [x] 1.3 Tier 2：回退 AgenticRAG.run()（仅当 Tier 1 结果差）
- [x] 1.4 后处理：图片匹配 + 引用溯源（两个路径共用）

## 2. QAEngine.answer_stream() 两级策略

- [x] 2.1 Tier 1 流式：RRF 检索 → 直接 LLM stream=True → yield thinking+token+done
- [x] 2.2 Tier 2 回退：AgenticRAG.run_stream()
- [x] 2.3 done 事件含后处理结果

## 3. 验证

- [x] 3.1 简单问题 < 5s 返回，不计入 AgenticRAG trace
- [x] 3.2 复杂问题正确回退且 answer 包含完整 reasoning trace
