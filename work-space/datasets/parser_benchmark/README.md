# Parser Benchmark Dataset

Đặt dữ liệu benchmark parser tại:

- `work-space/datasets/parser_benchmark/raw_docs/`

Nguyên tắc:
- Chỉ đặt các tài liệu gốc cần so sánh parser, ví dụ: PDF, DOCX, PPTX, hình ảnh.
- Không trộn dataset parser benchmark với `work-space/data_test/`.
- Nên giữ cùng một tập tài liệu cho cả ba parser để so sánh công bằng.
- Nếu muốn benchmark tốc độ parser công bằng hơn, dùng thêm cờ `--fresh-parser-cache`.

Ví dụ:

```text
work-space/datasets/parser_benchmark/raw_docs/
  report_01.pdf
  report_02.pdf
  paper_03.pdf
```

## Cách chạy
Lưu ý fairness hiện tại:
- `MinerU` được pin rõ `backend`, `device=cuda`, `lang=en`, `source=huggingface`.
- `Docling` được pin rõ `device=cuda`, `ocr_lang=en`.
- `Docling` chỉ parse **một lần** rồi xuất đồng thời `json` và `md`.
- `Source_Pages` được lấy từ file gốc, không còn suy diễn từ `content_list.page_idx`.

Chạy toàn bộ 3 parser:

```bash
cd work-space
python run_extract_bench.py --fresh-run --fresh-parser-cache
```

Chạy riêng 1 parser:

```bash
cd work-space
python run_extract_bench.py --exp ext1_mineru_default_multimodal --fresh-run --fresh-parser-cache
python run_extract_bench.py --exp ext2_docling_default --fresh-run --fresh-parser-cache
python run_extract_bench.py --exp ext3_kreuzberg_paddleocr --fresh-run --fresh-parser-cache
```

Kết quả chính:
- `work-space/benchmark_outputs/reports/parser_benchmark_details.csv`
- `work-space/benchmark_outputs/reports/parser_benchmark_summary.csv`

## Insight hiện tại
Insight dưới đây là từ lần chạy cũ trên tài liệu `CT_MICA_full_body_segmentation.pdf`, nên chỉ xem như kết luận tạm thời trước khi rerun lại benchmark theo fairness patch ở trên.

### MinerU
- Parse thành công.
- Chậm nhất: khoảng `199.08 sec/page`.
- Coverage multimodal mạnh nhất trong 3 parser hiện tại:
  - `table=25.0/100p`
  - `figure=275.0/100p`
- Đổi lại output khá nhiễu và nặng:
  - `Noise Ratio=0.3689`
  - `Tokens/Page=412.25`

Kết luận ngắn:
- mạnh về coverage multimodal
- chi phí downstream cao
- tốc độ kém

### Docling
- Parse thành công.
- Chậm nhưng vẫn tốt hơn MinerU về tốc độ trên file này:
  - `156.60 sec/page`
- Coverage text tốt nhất:
  - `text=19.6/page`
- Output gọn hơn MinerU:
  - `Noise Ratio=0.3359`
  - `Tokens/Page=217.96`
- Có giữ được một phần bảng:
  - `table=8.3/100p`

Kết luận ngắn:
- parser cân bằng nhất hiện tại
- mạnh cho text-centric pipeline
- coverage multimodal không giàu bằng MinerU

### Kreuzberg + PaddleOCR
- Parse thành công sau khi chuyển sang `PaddleOCR`.
- Nhanh nhất rất rõ:
  - `0.87 sec/page`
- Nhưng coverage hiện tại rất yếu trên tài liệu này:
  - `text=1.0/page`
  - `table=0.0/100p`
  - `figure=0.0/100p`
  - `equation=0.0/100p`
- `Tokens/Page=696.12` cho thấy output đang nghiêng về OCR text dài, ít cấu trúc.

Kết luận ngắn:
- rất nhanh
- hiện phù hợp như OCR/text path
- chưa đủ tốt nếu mục tiêu là coverage multimodal fair với MinerU/Docling

## Kết luận tạm thời
- Nếu ưu tiên coverage multimodal: `MinerU`
- Nếu ưu tiên cân bằng chất lượng và chi phí downstream: `Docling`
- Nếu ưu tiên tốc độ tuyệt đối: `Kreuzberg + PaddleOCR`

Ở phase 1 hiện tại, `Docling` là lựa chọn mặc định hợp lý nhất.
