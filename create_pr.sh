#!/bin/bash
# 创建PR的完整流程

set -e

echo "🚀 创建Pull Request流程..."
echo "================================================"

# 检查是否有未提交的更改
if [ -z "$(git diff --cached --name-only)" ]; then
    echo "❌ 没有暂存的文件，请先运行 prepare_pr_commit.sh"
    exit 1
fi

# 获取当前分支
current_branch=$(git branch --show-current)
echo ""
echo "当前分支: $current_branch"

# 创建新分支
echo ""
read -p "创建新分支名称 (或按回车使用 'spiqa-results'): " branch_name
branch_name=${branch_name:-spiqa-results}

echo ""
echo "1. 创建新分支: $branch_name"
git checkout -b "$branch_name" 2>/dev/null || git checkout "$branch_name"
echo "   ✅ 分支已创建/切换"

# 提交更改
echo ""
echo "2. 提交更改..."
git commit -m "Add SPIQA Test-A/B evaluation results and visualizations

- Add Test-A overview visualization (82.7% accuracy)
- Add Test-B overview visualization (0.847 composite score, fixed question type normalization)
- Include comprehensive result JSON files for Test-A and Test-B
- Add essential test scripts for Test-A and Test-B
- Add detailed result analysis documentation
- Enhance query.py with Query Layer architecture documentation
- Update .gitignore to exclude large image files (~424MB)
- Note: Dataset images excluded from this PR (to be added separately after resolving LFS permissions)"

echo "   ✅ 已提交"

# 推送到远程
echo ""
echo "3. 推送到远程仓库..."
git push -u origin "$branch_name"
echo "   ✅ 已推送"

# 显示PR链接
repo_url=$(git remote get-url origin | sed 's/\.git$//' | sed 's/git@github.com:/https:\/\/github.com\//')
echo ""
echo "================================================"
echo "✅ 完成！"
echo ""
echo "📝 下一步：在GitHub上创建Pull Request"
echo ""
echo "🔗 PR链接（如果已创建）:"
echo "   $repo_url/compare/$branch_name"
echo ""
echo "或者访问:"
echo "   $repo_url"
echo "   然后点击 'New Pull Request' 按钮"

