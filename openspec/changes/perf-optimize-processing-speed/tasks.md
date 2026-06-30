## 1. Update .env configuration defaults

- [ ] 1.1 Add `MAX_ASYNC=12` (raised from 7) with comment explaining LLM concurrency impact
- [ ] 1.2 Add `CHUNK_SIZE=1400` (raised from default 800) with comment explaining trade-off
- [ ] 1.3 Raise `ENTITY_EXTRACT_CONCURRENCY=6` (from 4) with comment about embedding API rate limits
- [ ] 1.4 Add `ENTITY_EXTRACTION_MIN_DEGREE=1` to filter isolated entities
- [ ] 1.5 Add per-document-type multimodal guidance comments (`ENABLE_IMAGE_PROCESSING`, `ENABLE_EQUATION_PROCESSING`, `ENABLE_TABLE_PROCESSING`)
- [ ] 1.6 Add `MAX_CONCURRENT_FILES=3` as optional tuning knob (commented out by default) with memory warning

## 2. Verification

- [ ] 2.1 Restart server and upload a document to verify new defaults take effect
- [ ] 2.2 Check worker logs to confirm `llm_model_max_async=12`, `graph_max_async=24`, `chunk_token_size=1400`
- [ ] 2.3 Compare processing time of a similar document before and after the change
- [ ] 2.4 Verify `ENTITY_EXTRACTION_MIN_DEGREE=1` removes isolated entities from graph output
- [ ] 2.5 Verify multimodal toggles (`ENABLE_IMAGE_PROCESSING=false`) skip VLM calls
