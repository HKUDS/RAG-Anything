#!/bin/bash
# 准备PR提交：包括Test-A/B结果、可视化文件、query.py

set -e

echo "📦 准备PR提交内容..."
echo "================================================"

# 确保在正确的目录
cd "$(dirname "$0")"

# 1. 移除datasets图像文件（不推送）
echo ""
echo "1. 移除数据集图像文件（不推送）..."
git reset HEAD dataset/test-A/SPIQA_testA_Images/ 2>/dev/null || true
git reset HEAD dataset/test-B/SPIQA_testB_Images/ 2>/dev/null || true
git reset HEAD dataset/test-C/SPIQA_testC_Images/ 2>/dev/null || true
git reset HEAD .gitattributes 2>/dev/null || true
echo "   ✅ 已移除"

# 2. 确保Test-A/B文件已添加
echo ""
echo "2. 确保Test-A/B文件已添加..."
git add spiqa_testa_full_results_final.json 2>/dev/null || true
git add spiqa_testb_simple_results.json 2>/dev/null || true
git add visualizations/testa_overview.png 2>/dev/null || true
git add visualizations/testb_overview.png 2>/dev/null || true
git add test_spiqa_testa.py 2>/dev/null || true
git add test_spiqa_testb_simple.py 2>/dev/null || true
echo "   ✅ 已添加"

# 3. 确保query.py已添加
echo ""
echo "3. 确保query.py已添加..."
git add raganything/query.py
echo "   ✅ 已添加"

# 4. 确保文档文件已添加
echo ""
echo "4. 添加文档文件..."
git add SPIQA_TESTA_RESULTS_SECTION.md 2>/dev/null || true
git add SPIQA_TESTB_RESULTS_SECTION.md 2>/dev/null || true
git add DATASET_IMAGES_SETUP.md 2>/dev/null || true
git add .gitignore 2>/dev/null || true
echo "   ✅ 已添加"

# 5. 显示将要提交的文件
echo ""
echo "================================================"
echo "📋 将要提交的文件:"
echo ""
git status --short | grep -E "^A|^M" | head -20
echo "   ... (更多文件)"
echo ""
echo "总文件数: $(git diff --cached --name-only | wc -l | tr -d ' ')"
echo ""
echo "关键文件:"
echo "  ✅ Test-A结果: $(git diff --cached --name-only | grep -c 'testa.*\.json' || echo 0)"
echo "  ✅ Test-B结果: $(git diff --cached --name-only | grep -c 'testb.*\.json' || echo 0)"
echo "  ✅ 可视化: $(git diff --cached --name-only | grep -c 'overview\.png' || echo 0)"
echo "  ✅ Query.py: $(git diff --cached --name-only | grep -c 'query\.py' || echo 0)"
echo ""
echo "================================================"
echo "✅ 准备完成！"
echo ""
echo "下一步:"
echo "  1. 提交: git commit -m 'Your commit message'"
echo "  2. 创建PR: 推送到新分支然后创建Pull Request"

