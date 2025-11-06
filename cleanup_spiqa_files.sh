#!/bin/bash
# Cleanup SPIQA files - keep only Test-A/B essential files and overview visualizations

set -e

echo "🧹 Cleaning up SPIQA files..."
echo "================================"

# 1. Delete Test-C related files
echo ""
echo "1. Deleting Test-C related files..."
rm -f spiqa_testc_*.json
rm -f test_spiqa_testc_*.py
rm -f visualizations/testc_*.png
rm -f visualizations/testc_*.html
rm -rf rag_storage_testc*
echo "   ✅ Test-C files deleted"

# 2. Delete Test-B wrong/duplicate files
echo ""
echo "2. Deleting Test-B wrong/duplicate files..."
# Keep: spiqa_testb_simple_results.json (correct composite score)
# Delete: spiqa_comprehensive_results.json (wrong, only has similarity_score=1.0)
rm -f spiqa_comprehensive_results.json
rm -f spiqa_testb_results_from_archive.json
rm -f visualizations/testb_detailed_analysis.png
rm -f visualizations/testb_score_flow.png
rm -f visualizations/testa_vs_testb_comparison.png
echo "   ✅ Test-B wrong files deleted"

# 3. Delete Test-A duplicate/old files
echo ""
echo "3. Deleting Test-A duplicate/old files..."
# Keep: spiqa_testa_full_results_final.json (final version)
# Delete: old versions and duplicates
rm -f spiqa_testa_full_results.json
rm -f spiqa_testa_full_results_kept.json
rm -f spiqa_testa_full_results_ollama.json
rm -f spiqa_testa_results.json
rm -f spiqa_testa_results_final.json
echo "   ✅ Test-A duplicate files deleted"

# 4. Delete non-overview visualizations
echo ""
echo "4. Deleting non-overview visualizations..."
# Keep only: testa_overview.png, testb_overview.png
# Delete: all other visualizations
cd visualizations
rm -f testa_vs_testb_comparison.png
rm -f testb_detailed_analysis.png
rm -f testb_score_flow.png
rm -f testc_*.png
rm -f testc_*.html
rm -f spiqa_*.png
rm -f spiqa_*.html
rm -f error_heatmap.png
rm -f recall_vs_accuracy.png
rm -f latency_analysis.png
rm -f routing_distribution.png
rm -f spiqa_accuracy_heatmap.png
rm -f spiqa_category_analysis.png
rm -f spiqa_comprehensive_dashboard.png
rm -f spiqa_interactive_dashboard.html
rm -f spiqa_overall_comparison.png
rm -f spiqa_question_types.png
rm -f spiqa_radar_chart.png
rm -f spiqa_summary_comparison.html
rm -f testb_score_flow.html
rm -f testc_qtype_heatmap.html
rm -f spiqa_highres_dashboard.html
cd ..
echo "   ✅ Non-overview visualizations deleted"

# 5. Delete Test-C test scripts and keep only essential Test-A/B scripts
echo ""
echo "5. Cleaning up test scripts..."
# Keep essential: test_spiqa_testa.py, test_spiqa_testb_simple.py
# Delete: all testc scripts and other test scripts
rm -f test_spiqa_testc_*.py
rm -f test_spiqa_comprehensive.py
rm -f test_spiqa_new_format.py
rm -f test_spiqa_new.py
rm -f test_spiqa_rag.py
rm -f test_spiqa_simple.py
rm -f test_spiqa_testb_generation.py
rm -f test_spiqa_testc.py
rm -f test_spiqa_testc_full.py
echo "   ✅ Test scripts cleaned"

# 6. Delete Test-C documentation
echo ""
echo "6. Deleting Test-C documentation..."
rm -f SPIQA_COMPREHENSIVE_FINAL_REPORT.md
rm -f SPIQA_FINAL_VISUALIZATION_SUMMARY.md
echo "   ✅ Test-C documentation deleted"

# 7. Delete root level Test-C PNG files
echo ""
echo "7. Deleting root level Test-C files..."
rm -f spiqa_testc_*.png
rm -f spiqa_final_dashboard.png
rm -f spiqa_final_overall_comparison.png
rm -f spiqa_performance_summary.png
rm -f spiqa_testc_analysis.png
echo "   ✅ Root level Test-C files deleted"

# 8. Clean up old/duplicate documentation
echo ""
echo "8. Cleaning up old documentation..."
rm -f SPIQA_AB_REPORT.md
rm -f SPIQA_ALL_TESTS_SUMMARY.md
rm -f SPIQA_TESTA_REPORT.md
rm -f SPIQA_TESTB_GENERATION_REPORT.md
rm -f SPIQA_VISUALIZATION_SUMMARY.md
echo "   ✅ Old documentation deleted"

# 9. Clean up helper scripts (keep only essential)
echo ""
echo "9. Cleaning up helper/commit scripts..."
rm -f commit_spiqa_final.sh
rm -f commit_spiqa_results.sh
rm -f create_final_visualizations.py
rm -f create_interactive_dashboard.py
rm -f create_spiqa_visualizations.py
rm -f create_testb_visualizations.py
rm -f create_updated_visualizations.py
# Keep: fix_testb_overview.py (useful reference)
# Keep: commit_overview_only.sh (useful)
echo "   ✅ Helper scripts cleaned"

# 10. Clean up old progress files
echo ""
echo "10. Cleaning up old progress files..."
rm -f continue_test_b.py
rm -f resume_test_b.py
rm -f save_progress.py
rm -f testb_run.log
echo "   ✅ Old progress files deleted"

echo ""
echo "================================"
echo "✅ Cleanup complete!"
echo ""
echo "📦 Remaining files:"
echo "   Test-A:"
echo "   - spiqa_testa_full_results_final.json"
echo "   - test_spiqa_testa.py"
echo "   - visualizations/testa_overview.png"
echo ""
echo "   Test-B:"
echo "   - spiqa_testb_simple_results.json"
echo "   - test_spiqa_testb_simple.py"
echo "   - visualizations/testb_overview.png"
echo ""
echo "   Documentation:"
echo "   - SPIQA_TESTA_RESULTS_SECTION.md"
echo "   - SPIQA_TESTB_RESULTS_SECTION.md"
echo "   - DATASET_IMAGES_SETUP.md"
echo "   - DATASET_IMAGES_ALTERNATIVES.md"
echo ""
echo "   Tools:"
echo "   - fix_testb_overview.py"
echo "   - commit_overview_only.sh"

