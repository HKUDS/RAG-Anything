### 1. Definition exp in file work-space/src/definitions.py
Example: 
    "exp1_baseline": ExperimentDef(
        id="exp1_baseline",
        description="Baseline MinerU (default parser, auto parse)",
        parser="mineru",
        parse_method="auto",
        parser_kwargs={},
        lightrag_kwargs={}
    ),

Parser benchmark variants available by default:
- `exp1_baseline_docling`
- `exp1_baseline_kreuzberg`
- `exp1_baseline_marker`
- `exp1_baseline_marker_ocr`

### 2. Run all exps:
``` bash
python run_bench.py
```

Fresh run (clear `rag_storage` + `parser_output` before each experiment):
``` bash
python run_bench.py --fresh-run
```

### 3. Run a specific exp:
``` bash
python run_bench.py --exp ${exp_name}
```
Output will be in benchmark_report.csv

Specific experiment with fresh run:
``` bash
python run_bench.py --exp ${exp_name} --fresh-run
```

### 4. Recommended commands for parser end-to-end baseline
``` bash
python run_bench.py --exp exp1_baseline
python run_bench.py --exp exp1_baseline_docling
python run_bench.py --exp exp1_baseline_kreuzberg
python run_bench.py --exp exp1_baseline_marker
python run_bench.py --exp exp1_baseline_marker_ocr
```

### 5. Extract benchmark with fresh run/cache
``` bash
python run_extract_bench.py --fresh-run
python run_extract_bench.py --exp ext3_kreuzberg_default --fresh-run --fresh-parser-cache
```

### Streamlit web based
``` bash
python -m streamlit run app.py --server.fileWatcherType none
```

### Query answer pipeline defaults
- Workspace query path now defaults to core RAG retrieval:
  - primary strategy: ask LightRAG/RAG-Anything for retrieved context first
  - answer generation: grounded synthesis from that retrieved context
  - fallback mode: direct `rag.aquery(...)`
  - query-time vision/VLM: disabled
  - `aquery_with_multimodal`: not used in workspace answer flow
  - answer prompt: grounded, no guessing when context is insufficient
- Query-time knobs can be overridden in `work-space/.env`:
``` bash
QUERY_DEFAULT_MODE=mix
QUERY_TOP_K=40
QUERY_CHUNK_TOP_K=12
QUERY_RESPONSE_TYPE=Multiple Paragraphs
QUERY_ENABLE_RERANK=false
```
