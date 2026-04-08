# Pipeline QA Dataset

Gold QA benchmark cho phase 2 được sinh tự động bằng OpenAI và lưu tại:

- `work-space/datasets/pipeline_qa/gold_qa/`

Mỗi file gold lưu:

- `document_name`
- `source_path`
- `source_md5`
- `reference_source`
- `questions_per_doc`
- `generator_model`
- danh sách `questions`

Mỗi câu hỏi gồm:

- `question_id`
- `difficulty`
- `question_type`
- `question`
- `gold_answer`
- `evidence_snippets`
- `evidence_keywords`

Mặc định:

- nếu `source_md5` không đổi
- và `questions_per_doc` không đổi

thì runner sẽ reuse file gold hiện có, không gọi lại OpenAI.

Muốn sinh lại gold:

```bash
cd work-space
python run_pipeline_qa_eval.py --regenerate-gold
```
