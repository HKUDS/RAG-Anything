#!/bin/bash
# Commit only Test-A/B/C overview visualizations and result JSONs

set -e

echo "🚀 Committing SPIQA overview visualizations and results..."

# Only overview visualizations
git add visualizations/testa_overview.png
git add visualizations/testb_overview.png
git add visualizations/testc_overview.png

# Result JSON files
git add spiqa_testa_full_results_final.json
git add spiqa_comprehensive_results.json
git add spiqa_testc_relaxed_results.json

# Documentation
git add SPIQA_TESTA_RESULTS_SECTION.md 2>/dev/null || true
git add SPIQA_TESTB_RESULTS_SECTION.md 2>/dev/null || true
git add SPIQA_COMPREHENSIVE_FINAL_REPORT.md 2>/dev/null || true
git add DATASET_IMAGES_SETUP.md
git add DATASET_IMAGES_ALTERNATIVES.md

# Configuration
git add .gitignore
git add raganything/query.py

# Fix script (optional, for reference)
git add fix_testb_overview.py

echo ""
echo "📋 Files staged:"
git status --short | grep -E "(testa_overview|testb_overview|testc_overview|\.json|\.md|\.py|\.gitignore)" | head -20

echo ""
read -p "Continue with commit? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git commit -m "docs(spiqa): Add Test-A/B/C overview visualizations and evaluation results

- Add Test-A overview visualization (82.7% accuracy)
- Add Test-B overview visualization (0.847 composite score, fixed question type normalization)
- Add Test-C overview visualization (60.0% accuracy)
- Include comprehensive result JSON files for all test sets
- Add detailed result analysis documentation
- Update .gitignore to exclude large image files (~424MB)
- Add dataset images setup guide
- Enhance query.py with Query Layer architecture documentation
- Fix Test-B question type normalization (shallow/testing/deep-complex variants)"
    
    echo "✅ Commit successful!"
    echo ""
    echo "📌 Next step: git push"
else
    echo "❌ Commit cancelled"
fi

