# Workbench README

Thư mục `work-space/` là nơi chạy toàn bộ benchmark và dashboard cho RAG-Anything.

## Thành phần chính

- `run_extract_bench.py`: benchmark parser
- `run_bench.py`: benchmark pipeline end-to-end
- `run_pipeline_qa_eval.py`: benchmark QA end-to-end
- `run_retrieval_bench.py`: benchmark retrieval
- `run_pruning_bench.py`: benchmark graph pruning cho FE
- `app.py`: dashboard Streamlit

## Các nhóm thí nghiệm

1. `Parser benchmark`
- so parser theo quality, modalities, noise, tốc độ

2. `Pipeline benchmark phase 1`
- đo parse + graph build + indexing cost

3. `Pipeline benchmark phase 2 QA`
- đo chất lượng hỏi đáp end-to-end

4. `Retrieval benchmark`
- đo Recall/MRR/Precision của các query modes và reranker

5. `Pruning benchmark`
- chọn `display graph` gọn cho FE
- không sửa graph/storage gốc
- hiện có thêm method `embedding_semantic_summary` bám paper semantic-summary + linking

6. `Postprocess graph`
- tài liệu giải thích phần graph FE và pruning

## Tài liệu

Các tài liệu benchmark nằm trong:

- `work-space/docs/parser_benchmark_phase1.md`
- `work-space/docs/pipeline_benchmark_phase1.md`
- `work-space/docs/pipeline_benchmark_phase2_qa.md`
- `work-space/docs/retrieval_benchmark_phase_a.md`
- `work-space/docs/retrieval_benchmark_phase_b.md`
- `work-space/docs/pruning_benchmark_phase_a.md`
- `work-space/docs/postprocess_graph.md`
- `work-space/docs/streamlit_workbench.md`
- `work-space/docs/pipeline_smoke_test_mineru_cloud_openai.md`

PDF tham khảo:

- `work-space/docs/mineruV2.5.pdf`
- `work-space/docs/docling.pdf`

## Lệnh chạy nhanh

Parser:

```bash
cd work-space
python run_extract_bench.py --fresh-run --fresh-parser-cache
```

Pipeline:

```bash
python run_bench.py --fresh-run
```

QA:

```bash
python run_pipeline_qa_eval.py --fresh-report
```

QA cho riêng `exp5`:

```bash
python run_pipeline_qa_eval.py --exp exp5_medical_scope_mineru_ollama_radgraph_xl --fresh-report
```

QA cho riêng `exp6` và append vào report hiện có:

```bash
python run_pipeline_qa_eval.py --exp exp6_medical_scope_mineru_ollama_iter_ade
```

QA cho riêng `exp7` và append vào report hiện có:

```bash
python run_pipeline_qa_eval.py --exp exp7_medical_scope_mineru_ollama_iter_scierc
```

QA cho riêng `exp8` và append vào report hiện có:

```bash
python run_pipeline_qa_eval.py --exp exp8_default_mineru_ollama_radgraph_xl
```

QA cho riêng `exp9` và append vào report hiện có:

```bash
python run_pipeline_qa_eval.py --exp exp9_default_mineru_ollama_iter_ade
```

QA cho riêng `exp10` và append vào report hiện có:

```bash
python run_pipeline_qa_eval.py --exp exp10_default_mineru_ollama_iter_scierc
```

Retrieval:

```bash
python run_retrieval_bench.py --fresh-report
```

Retrieval cho riêng `exp5`:

```bash
python run_retrieval_bench.py --base-exp exp5_medical_scope_mineru_ollama_radgraph_xl --fresh-report
```

Retrieval cho riêng `exp6` và append vào report hiện có:

```bash
python run_retrieval_bench.py --base-exp exp6_medical_scope_mineru_ollama_iter_ade
```

Retrieval cho riêng `exp7` và append vào report hiện có:

```bash
python run_retrieval_bench.py --base-exp exp7_medical_scope_mineru_ollama_iter_scierc
```

Retrieval cho riêng `exp8` và append vào report hiện có:

```bash
python run_retrieval_bench.py --base-exp exp8_default_mineru_ollama_radgraph_xl
```

Retrieval cho riêng `exp9` và append vào report hiện có:

```bash
python run_retrieval_bench.py --base-exp exp9_default_mineru_ollama_iter_ade
```

Retrieval cho riêng `exp10` và append vào report hiện có:

```bash
python run_retrieval_bench.py --base-exp exp10_default_mineru_ollama_iter_scierc
```

Pruning:

```bash
python run_pruning_bench.py --fresh-report
```

Pruning cho riêng `exp5`:

```bash
python run_pruning_bench.py --base-exp exp5_medical_scope_mineru_ollama_radgraph_xl --fresh-report
```

Pruning cho riêng `exp6` và append vào report hiện có:

```bash
python run_pruning_bench.py --base-exp exp6_medical_scope_mineru_ollama_iter_ade
```

Pruning cho riêng `exp7` và append vào report hiện có:

```bash
python run_pruning_bench.py --base-exp exp7_medical_scope_mineru_ollama_iter_scierc
```

Pruning cho riêng `exp8` và append vào report hiện có:

```bash
python run_pruning_bench.py --base-exp exp8_default_mineru_ollama_radgraph_xl
```

Pruning cho riêng `exp9` và append vào report hiện có:

```bash
python run_pruning_bench.py --base-exp exp9_default_mineru_ollama_iter_ade
```

Pruning cho riêng `exp10` và append vào report hiện có:

```bash
python run_pruning_bench.py --base-exp exp10_default_mineru_ollama_iter_scierc
```

Nếu chạy `exp6` hoặc `exp7`, cần cài thêm ITER:

```bash
/mnt/disk1/aiotlab/envs/raganything/bin/pip install git+https://github.com/fleonce/iter
```

Dashboard:

```bash
streamlit run app.py
```

## Kết quả

Report CSV/JSONL nằm ở:

- `work-space/benchmark_outputs/reports/`

Log của từng lần chạy benchmark nằm ở:

- `work-space/benchmark_outputs/logs/`

Artifacts theo từng experiment nằm ở:

- `work-space/benchmark_outputs/`
