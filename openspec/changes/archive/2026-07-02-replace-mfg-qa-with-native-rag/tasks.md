## 1. Simplify backend QA endpoints

- [x] 1.1 Remove `ServerLLMAdapter` class from `_get_mfg_agent_components`
- [x] 1.2 Remove `QAEngine` and `image_paths` loading from `_get_mfg_agent_components`
- [x] 1.3 Rewrite `/api/manufacturing/qa` to call `instance.aquery(mode="hybrid")` directly
- [x] 1.4 Rewrite `/api/manufacturing/qa/stream` to use LightRAG native context retrieval + streaming LLM
- [x] 1.5 Remove unused imports — only `FaultDiagnosisEngine` + `FaultCaseLibrary` remain

## 2. Clean up frontend

- [x] 2.1 Remove `related_images` display from QA messages in ManufacturingAgentPage
- [x] 2.2 Stream SSE handling simplified — done event no longer expects images/confidence

## 3. Verify

- [ ] 3.1 Ask "PLC 输出信号无响应" via manufacturing QA — verify answer matches regular agent quality
- [ ] 3.2 Ask "加工精度超差的原因" via manufacturing QA — verify answer matches regular agent quality
- [ ] 3.3 Verify Fault Diagnosis tab still works (uses FaultDiagnosisEngine, not QAEngine)
- [ ] 3.4 Verify Code Parser tab still works
