#!/bin/bash
# 最终自动化推送脚本 - 使用GitHub CLI

set -e

echo "🚀 自动化推送脚本 (使用GitHub CLI)"
echo "================================================"

cd "$(dirname "$0")"

BRANCH="spiqa-results-pr-clean"
REPO="xiaoranwang1452/RAG-Anything"

# 检查GitHub CLI
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI未安装"
    echo "安装: brew install gh"
    exit 1
fi

# 检查登录状态
if ! gh auth status &> /dev/null; then
    echo "❌ 未登录GitHub CLI"
    echo "登录: gh auth login"
    exit 1
fi

echo ""
echo "✅ GitHub CLI已安装并登录"
echo ""

# 设置默认仓库（如果还没有设置）
echo "设置GitHub CLI默认仓库..."
gh repo set-default xiaoranwang1452/RAG-Anything 2>/dev/null || true
echo ""

# 切换到目标分支
current_branch=$(git branch --show-current)
if [ "$current_branch" != "$BRANCH" ]; then
    echo "切换到分支: $BRANCH"
    git checkout $BRANCH
fi

echo ""
echo "当前分支: $(git branch --show-current)"
echo ""

# 尝试推送（多次尝试不同的方式）
echo "尝试方式1: 标准推送..."
if git push -u origin $BRANCH 2>&1 | grep -q "Everything up-to-date\|error"; then
    echo "标准推送失败，尝试方式2..."
    
    # 方式2: 使用GitHub CLI创建PR（会自动推送）
    echo "使用GitHub CLI创建PR（会自动推送分支）..."
    gh pr create \
        --head $BRANCH \
        --base main \
        --title "Add SPIQA Test-A/B evaluation results and visualizations" \
        --body "Add SPIQA Test-A/B evaluation results, visualizations, and documentation.

## Changes
- Add Test-A overview visualization (82.7% accuracy)
- Add Test-B overview visualization (0.847 composite score)
- Include comprehensive result JSON files
- Add test scripts and documentation
- Enhance query.py with Query Layer architecture documentation

## Files
- Test-A: \`spiqa_testa_full_results_final.json\`, \`visualizations/testa_overview.png\`
- Test-B: \`spiqa_testb_simple_results.json\`, \`visualizations/testb_overview.png\`
- Documentation: \`SPIQA_TESTA_RESULTS_SECTION.md\`, \`SPIQA_TESTB_RESULTS_SECTION.md\`
- Code: \`raganything/query.py\` (enhanced)" 2>&1
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ PR已创建！"
        echo "查看: https://github.com/$REPO/pulls"
        exit 0
    fi
else
    echo "✅ 分支推送成功！"
    echo ""
    echo "创建PR..."
    gh pr create \
        --head $BRANCH \
        --base main \
        --title "Add SPIQA Test-A/B evaluation results and visualizations" \
        --body "Add SPIQA Test-A/B evaluation results, visualizations, and documentation." 2>&1
    exit 0
fi

echo ""
echo "❌ 所有推送方式都失败了"
echo ""
echo "建议:"
echo "1. 检查网络连接"
echo "2. 检查GitHub服务状态"
echo "3. 使用GitHub网页手动创建PR"
echo ""
exit 1

