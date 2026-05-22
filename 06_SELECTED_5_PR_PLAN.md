# 06_SELECTED_5_PR_PLAN.md — RAG-Anything: 5 Selected Contribution Candidates

## Selection Criteria
- Impact (user pain points, issue frequency)
- Feasibility (scope, complexity, testability)
- Alignment with project roadmap (multimodal, performance, DX)
- Likelihood of acceptance (maintainer responsiveness, code quality)

---

## Candidate 1: Fix `hashing_kv` / embedding dimension mismatch in multimodal processing
**Issue**: #167 — Multiple `hashing_kv` errors + `ValueError: all the input array dimensions... 3072 and 1024`

### Problem
Users report that during multimodal chunk generation, `hashing_kv` errors appear repeatedly. The error `ValueError: all the input array dimensions... along dimension 1, the array at index 0 has size 3072 and the array at index 1 has size 1024` suggests embedding dimension mismatch between text chunks (3072) and image chunks (1024) when upserting to LightRAG's vector store.

### Investigation Plan
1. Examine `raganything/processor.py` `_apply_chunk_template()` and multimodal chunk insertion
2. Trace how `lightrag.process_document` / `upsert` handles heterogeneous embedding dimensions
3. Check if image/text chunks use different embedding models or dimension settings
4. Determine if this is a LightRAG issue or RAG-Anything configuration issue

### Fix Approach
- Ensure all modalities use the same embedding dimension
- Add dimension validation before upsert
- Add proper error handling for dimension mismatch

### Files Likely to Modify
- `raganything/processor.py`
- `raganything/modalprocessors.py`

---

## Candidate 2: Fix `DocProcessingStatus.__init__()` `multimodal_processed` regression
**Issues**: #119, #91 — `TypeError: DocProcessingStatus.__init__() got an unexpected keyword argument 'multimodal_processed'`

### Problem
Two independent reports of the same regression. The `DocProcessingStatus` class doesn't accept `multimodal_processed` as a keyword argument, causing failures during document processing.

### Investigation Plan
1. Examine `lightrag` package's `DocProcessingStatus` class signature
2. Compare with how RAG-Anything calls it in `processor.py`
3. Check if this is a LightRAG version compatibility issue

### Fix Approach
- If LightRAG recently changed its API, add compatibility shim
- Or use correct kwarg name if API changed
- Add version detection for backward compatibility

### Files Likely to Modify
- `raganything/processor.py`
- `raganything/callbacks.py`

---

## Candidate 3: Add incremental folder scan by date/md5
**Issue**: #156 — `Feature Request: support incremental scan of a folder and update the changed file based on date and md5`

### Problem
Currently every run processes all documents from scratch, re-consuming VLM tokens and time. Users want incremental processing that only re-indexes changed files.

### Implementation Plan
1. Add a file tracking mechanism (db/file that stores path → mtime + md5)
2. Modify `raganything/raganything.py` or `batch.py` to check stored hashes before processing
3. Add CLI/env config: `RAGANYTHING_INCREMENTAL=true`
4. Add a reset mechanism to force full re-index

### Files Likely to Modify
- `raganything/raganything.py` (add hash tracking)
- `raganything/batch.py` (add incremental logic)
- `raganything/config.py` (add config options)

---

## Candidate 4: Add PaddleOCR as parser option
**Issue**: #178 — `Feature Request: PaddleOCR available for parser`

### Problem
MinerU-based parsing doesn't handle scanned PDFs well. PaddleOCR provides better OCR for scanned documents but is not currently a parser option (though the code hints at it in `testpaddleocr_parser.py`).

### Investigation Plan
1. Examine `testpaddleocr_parser.py` to understand intended interface
2. Check if `PaddleOCRParser` was partially implemented but not exported
3. Review how other parsers (MinerU, Docling) are structured

### Implementation Plan
1. Create `PaddleOCRParser` class in `raganything/parser.py` if not exists
2. Register in `SUPPORTED_PARSERS` and `get_parser()`
3. Add to `raganything/config.py` parser list
4. Add tests if missing

### Files Likely to Modify
- `raganything/parser.py`
- `raganything/config.py`
- `tests/testpaddleocr_parser.py`

---

## Candidate 5: Add local Ollama/LM Studio embedding support
**Issue**: #146 + #108 — Local model support questions; Ollama timeout issues

### Problem
Users want to use local embedding models (via Ollama, LM Studio) instead of cloud APIs. The current implementation may not expose embedding model configuration clearly.

### Implementation Plan
1. Document embedding model configuration in `env.example`
2. Add `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `EMBEDDING_DIM` env vars to config
3. Verify LightRAG embedding interface accepts custom base URLs
4. Add integration examples for Ollama embeddings

### Files Likely to Modify
- `raganything/config.py`
- `env.example`
- `examples/ollama_integration_example.py`

---

## Execution Order
1. **Candidate 2** (DocProcessingStatus regression) — Quick fix, high impact, two duplicate issues
2. **Candidate 4** (PaddleOCR parser) — Medium effort, unblocks scanned PDF users
3. **Candidate 1** (hashing_kv / embedding mismatch) — Hard to debug, needs investigation
4. **Candidate 3** (Incremental scan) — Feature addition, significant DX improvement
5. **Candidate 5** (Local embedding support) — Documentation + config, medium effort

---

## Notes on Active PRs
- **PR #283** (MinerU image-text mapping) — Active today, fix likely to land soon
- **PRs #280/#281** (Audio/Video processors) — Major features, depend on each other
- **PR #190** (FastAPI Service) — Jan 2026, may need rebase
- **PR #270** (RAG-Anything Studio) — Large UI feature, longer review cycle