#!/bin/bash
# 直接添加图像文件到Git（不使用Git LFS）
# 注意：这会让仓库变大，但可以确保所有文件都在GitHub中

set -e

echo "📦 直接添加数据集图像文件到Git..."
echo "================================================"
echo "⚠️  警告: 这将添加约424MB的文件到git"
echo "   提交和推送可能需要较长时间"
echo ""

read -p "确认继续? (y/n): " confirm
if [[ $confirm != "y" ]]; then
    echo "❌ 已取消"
    exit 0
fi

# 更新.gitignore - 移除图像目录的排除规则
echo ""
echo "1. 更新.gitignore..."
cp .gitignore .gitignore.bak

# 移除图像相关的排除规则
sed -i.bak '/dataset\/\*\*\/SPIQA_\*_Images\//d' .gitignore
sed -i.bak '/dataset\/\*\*\/\*\.zip/d' .gitignore
sed -i.bak '/dataset\/\*\*\/\*_extracted\//d' .gitignore

echo "   ✅ .gitignore已更新"

# 添加图像文件到git
echo ""
echo "2. 添加图像文件到Git..."
echo "   (这可能需要一些时间，请耐心等待)..."

# 添加图像目录
if [ -d "dataset/test-A/SPIQA_testA_Images" ]; then
    echo "   添加Test-A图像..."
    git add dataset/test-A/SPIQA_testA_Images/
fi

if [ -d "dataset/test-B/SPIQA_testB_Images" ]; then
    echo "   添加Test-B图像..."
    git add dataset/test-B/SPIQA_testB_Images/
fi

if [ -d "dataset/test-C/SPIQA_testC_Images" ]; then
    echo "   添加Test-C图像..."
    git add dataset/test-C/SPIQA_testC_Images/
fi

# 添加zip文件（如果存在）
if [ -f "dataset/test-A/test-A/SPIQA_testA_Images.zip" ]; then
    echo "   添加Test-A zip文件..."
    git add dataset/test-A/test-A/SPIQA_testA_Images.zip
fi
if [ -f "dataset/test-B/test-B/SPIQA_testB_Images.zip" ]; then
    git add dataset/test-B/test-B/SPIQA_testB_Images.zip
fi
if [ -f "dataset/test-C/test-C/SPIQA_testC_Images.zip" ]; then
    git add dataset/test-C/test-C/SPIQA_testC_Images.zip
fi

echo ""
echo "================================================"
echo "✅ 图像文件已添加到Git暂存区"
echo ""
echo "📊 状态:"
echo "   已暂存的文件数量:"
git diff --cached --name-only | grep -E "dataset.*SPIQA.*Images" | wc -l
echo ""
echo "📝 下一步:"
echo "   git commit -m 'Add SPIQA dataset images (client requirement)'"
echo "   git push"
echo ""
echo "⚠️  注意:"
echo "   - 提交时可能需要较长时间（424MB）"
echo "   - 推送时可能需要较长时间"
echo "   - 确保GitHub仓库有足够空间"

