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

Chạy thêm MinerU official cloud API:

```bash
cd work-space
python run_extract_bench.py --exp ext4_mineru_cloud_vlm --fresh-run
```

Lưu ý:
- `ext4_mineru_cloud_vlm` cần `MINERU_API_KEY` trong `work-space/.env`
- đây là benchmark cloud service latency, không phải local parser throughput thuần

Kết quả chính:
- `work-space/benchmark_outputs/reports/parser_benchmark_details.csv`
- `work-space/benchmark_outputs/reports/parser_benchmark_summary.csv`

## Insight hiện tại
Kết quả hiện tại trên `CT_MICA_full_body_segmentation.pdf`:

- `ext1_mineru_default_multimodal`:
  - coverage multimodal mạnh nhất
  - nhưng local runtime rất chậm
- `ext2_docling_default`:
  - local parser cân bằng nhất
  - text coverage dày, output gọn hơn MinerU
- `ext3_kreuzberg_paddleocr`:
  - nhanh nhất local
  - nhưng coverage table/figure hiện rất yếu trên file này
- `ext4_mineru_cloud_vlm`:
  - quality profile gần như trùng `MinerU` local
  - nhưng service latency nhanh hơn rất nhiều

Kết luận ngắn:
- nếu ưu tiên coverage multimodal: `MinerU cloud`
- nếu cần local parser cân bằng: `Docling`
- nếu chỉ cần OCR/text cực nhanh: `Kreuzberg`
