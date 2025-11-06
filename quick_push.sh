#!/bin/bash
# 快速推送脚本

set -e

echo "🚀 自动化推送脚本"
echo "================================================"

cd "$(dirname "$0")"

TOKEN="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"
BRANCH="spiqa-results-pr-clean"
REPO="xiaoranwang1452/RAG-Anything"

echo ""
echo "1. 检查当前分支..."
current_branch=$(git branch --show-current)
if [ "$current_branch" != "$BRANCH" ]; then
    echo "   切换到分支: $BRANCH"
    git checkout $BRANCH
fi

echo ""
echo "2. 配置Git优化设置..."
git config http.postBuffer 524288000
git config http.lowSpeedLimit 0
git config http.lowSpeedTime 0
echo "   ✅ 已配置"

echo ""
echo "3. 尝试使用GitHub CLI推送..."
if command -v gh &> /dev/null; then
    echo "   GitHub CLI已安装，尝试使用..."
    gh auth status &> /dev/null || gh auth login --with-token <<< "$TOKEN"
    if gh pr view $BRANCH &> /dev/null; then
        echo "   PR已存在，更新分支..."
        git push -u origin $BRANCH
    else
        echo "   创建PR..."
        gh pr create --head $BRANCH --base main \
            --title "Add SPIQA Test-A/B results" \
            --body "Add SPIQA Test-A/B evaluation results and visualizations"
    fi
    echo "   ✅ 使用GitHub CLI完成"
    exit 0
fi

echo ""
echo "4. 尝试使用SSH方式..."
if ssh -T git@github.com &> /dev/null <<< "yes"; then
    echo "   SSH可用，切换为SSH..."
    git remote set-url origin git@github.com:${REPO}.git
    git push -u origin $BRANCH
    echo "   ✅ SSH推送成功"
    exit 0
fi

echo ""
echo "5. 使用HTTPS + Token方式..."
git remote set-url origin https://${TOKEN}@github.com/${REPO}.git
if git push -u origin $BRANCH 2>&1; then
    echo "   ✅ HTTPS推送成功"
    git remote set-url origin https://github.com/${REPO}.git
    exit 0
else
    echo "   ❌ HTTPS推送失败"
    git remote set-url origin https://github.com/${REPO}.git
    echo ""
    echo "建议:"
    echo "  1. 安装GitHub CLI: brew install gh"
    echo "  2. 或配置SSH密钥: ssh-keygen -t ed25519 -C 'your_email@example.com'"
    exit 1
fi

