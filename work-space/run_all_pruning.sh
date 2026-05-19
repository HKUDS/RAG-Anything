#!/bin/bash

# ============================================================
#  run_all_pruning.sh — Chạy lần lượt tất cả pruning benchmarks
# ============================================================
#  Lưu ý: KHÔNG dùng "set -e" vì Python đôi khi trả exit code != 0
#  do "Exception ignored in sys.unraisablehook" khi thoát — đây là
#  cleanup warning vô hại, không phải lỗi thật.
#  Script kiểm tra kết quả thực bằng cách đọc "'Status': 'Success'"
#  trong log output thay vì chỉ dựa vào exit code.
# ============================================================

TOTAL=9
PASS=0
FAIL=0
FAILED_EXPS=()
TMPLOG=$(mktemp /tmp/pruning_exp_XXXX.log)

echo "============================================================"
echo "  Bắt đầu chạy $TOTAL pruning benchmark experiments"
echo "  Thời gian bắt đầu: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

run_exp() {
    local idx=$1
    local exp=$2

    echo "------------------------------------------------------------"
    echo "  [$idx/$TOTAL] Đang chạy: $exp"
    echo "  Thời gian: $(date '+%H:%M:%S')"
    echo "------------------------------------------------------------"

    # Chạy Python, hiện log ra màn hình, đồng thời ghi vào file tạm
    python run_pruning_bench.py --exp "$exp" 2>&1 | tee "$TMPLOG"
    local exit_code=${PIPESTATUS[0]}

    # Kiểm tra kết quả thực sự từ log:
    # Ưu tiên dòng "'Status': 'Success'" — tức experiment hoàn thành đúng.
    # "Exception ignored" khi Python thoát sẽ bị bỏ qua.
    if grep -q "'Status': 'Success'" "$TMPLOG"; then
        echo ""
        echo "  ✅  [$idx/$TOTAL] THÀNH CÔNG: $exp"
        PASS=$((PASS + 1))
    elif [ "$exit_code" -eq 0 ]; then
        echo ""
        echo "  ✅  [$idx/$TOTAL] THÀNH CÔNG: $exp"
        PASS=$((PASS + 1))
    else
        echo ""
        echo "  ❌  [$idx/$TOTAL] THẤT BẠI (exit=$exit_code): $exp"
        FAIL=$((FAIL + 1))
        FAILED_EXPS+=("$exp")
        # Bỏ comment dòng dưới nếu muốn dừng hẳn khi có lỗi thật:
        # exit 1
    fi

    > "$TMPLOG"   # xóa nội dung file tạm cho lần chạy tiếp
    echo ""
}

# ---------- Danh sách experiments ----------
run_exp 1  "pruning_exp1_baseline_mineru_cloud_openai_global_narrative_steiner_summary_top50"
run_exp 2  "pruning_exp2_default_mineru_cloud_ollama_global_narrative_steiner_summary_top50"
run_exp 3  "pruning_exp4_medical_scope_mineru_cloud_ollama_global_narrative_steiner_summary_top50"
run_exp 4  "pruning_exp5_medical_scope_mineru_ollama_radgraph_xl_global_narrative_steiner_summary_top50"
run_exp 5  "pruning_exp6_medical_scope_mineru_ollama_iter_ade_global_narrative_steiner_summary_top50"
run_exp 6  "pruning_exp7_medical_scope_mineru_ollama_iter_scierc_global_narrative_steiner_summary_top50"
run_exp 7  "pruning_exp8_default_mineru_ollama_radgraph_xl_global_narrative_steiner_summary_top50"
run_exp 8  "pruning_exp9_default_mineru_ollama_iter_ade_global_narrative_steiner_summary_top50"
run_exp 9  "pruning_exp10_default_mineru_ollama_iter_scierc_global_narrative_steiner_summary_top50"
# -------------------------------------------

rm -f "$TMPLOG"

echo "============================================================"
echo "  KẾT QUẢ TỔNG THỂ"
echo "  Thời gian kết thúc: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  ✅  Thành công : $PASS / $TOTAL"
echo "  ❌  Thất bại   : $FAIL / $TOTAL"

if [ ${#FAILED_EXPS[@]} -gt 0 ]; then
    echo ""
    echo "  Các experiment bị lỗi:"
    for exp in "${FAILED_EXPS[@]}"; do
        echo "    - $exp"
    done
fi

echo "============================================================"