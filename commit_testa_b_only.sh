#!/bin/bash
# Commit only Test-A/B essential files

set -e

echo "🚀 Committing Test-A/B overview visualizations and results..."

# Only overview visualizations
git add visualizations/testa_overview.png
git add visualizations/testb_overview.png

# Result JSON files (only Test-A/B final versions)
git add spiqa_testa_full_results_final.json
git add spiqa_testb_simple_results.json

# Essential test scripts
git add test_spiqa_testa.py
git add test_spiqa_testb_simple.py

# Documentation (only Test-A/B)
git add SPIQA_TESTA_RESULTS_SECTION.md
git add SPIQA_TESTB_RESULTS_SECTION.md
git add DATASET_IMAGES_SETUP.md
git add DATASET_IMAGES_ALTERNATIVES.md

# Configuration
git add .gitignore
git add raganything/query.py

# Optional: fix script (for reference)
git add fix_testb_overview.py

echo ""
echo "📋 Files staged:"
git status --short | grep -E "(testa|testb|SPIQA|DATASET|\.gitignore|query\.py|fix_testb)" | head -20

echo ""
read -p "Continue with commit? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git commit -m "docs(spiqa): Add Test-A/B overview visualizations and evaluation results

- Add Test-A overview visualization (82.7% accuracy)
- Add Test-B overview visualization (0.847 composite score, fixed question type normalization)
- Include final result JSON files for Test-A and Test-B
- Add essential test scripts for Test-A and Test-B
- Add detailed result analysis documentation
- Update .gitignore to exclude large image files (~424MB)
- Add dataset images setup guide
- Enhance query.py with Query Layer architecture documentation
- Clean up: removed Test-C files and non-essential visualizations"
    
    echo "✅ Commit successful!"
    echo ""
    echo "📌 Next step: git push"
else
    echo "❌ Commit cancelled"
fi

