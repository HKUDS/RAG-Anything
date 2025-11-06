#!/bin/bash
# 将数据集图像文件添加到Git（使用Git LFS）

set -e

echo "📦 添加数据集图像文件到GitHub..."
echo "================================================"

# 检查Git LFS
if ! command -v git-lfs &> /dev/null; then
    echo ""
    echo "❌ Git LFS未安装"
    echo ""
    echo "请先安装Git LFS:"
    echo "  macOS: brew install git-lfs"
    echo "  或访问: https://git-lfs.github.com/"
    echo ""
    exit 1
fi

echo ""
echo "✅ Git LFS已安装"
git-lfs version

# 初始化Git LFS（如果还没有）
echo ""
echo "1. 初始化Git LFS..."
git lfs install

# 跟踪PNG文件
echo ""
echo "2. 配置Git LFS跟踪PNG文件..."
git lfs track "dataset/**/SPIQA_*_Images/**/*.png"
git lfs track "dataset/**/*.zip"

# 添加.gitattributes
echo ""
echo "3. 添加.gitattributes文件..."
git add .gitattributes

# 更新.gitignore（移除图像目录的排除，因为LFS会处理）
echo ""
echo "4. 更新.gitignore..."
# 备份
cp .gitignore .gitignore.bak

# 移除图像相关的排除规则（LFS会处理）
sed -i.bak '/dataset\/\*\*\/SPIQA_\*_Images\//d' .gitignore
sed -i.bak '/dataset\/\*\*\/\*\.zip/d' .gitignore

# 添加图像文件到git
echo ""
echo "5. 添加图像文件到Git..."
echo "   (这可能需要一些时间，因为文件较多)..."
git add dataset/test-A/SPIQA_testA_Images/
git add dataset/test-B/SPIQA_testB_Images/
git add dataset/test-C/SPIQA_testC_Images/

# 检查是否有zip文件
if [ -f "dataset/test-A/test-A/SPIQA_testA_Images.zip" ]; then
    echo "   添加zip文件..."
    git add dataset/test-A/test-A/SPIQA_testA_Images.zip 2>/dev/null || true
fi
if [ -f "dataset/test-B/test-B/SPIQA_testB_Images.zip" ]; then
    git add dataset/test-B/test-B/SPIQA_testB_Images.zip 2>/dev/null || true
fi
if [ -f "dataset/test-C/test-C/SPIQA_testC_Images.zip" ]; then
    git add dataset/test-C/test-C/SPIQA_testC_Images.zip 2>/dev/null || true
fi

echo ""
echo "================================================"
echo "✅ 图像文件已添加到Git暂存区"
echo ""
echo "📊 状态:"
git status --short | grep -E "dataset.*SPIQA.*Images|\.gitattributes" | head -5
echo "   ... (更多文件)"
echo ""
echo "📝 下一步:"
echo "   git commit -m 'Add SPIQA dataset images via Git LFS'"
echo "   git push"
echo ""
echo "⚠️  注意:"
echo "   - 提交时Git LFS会处理大文件"
echo "   - 首次推送可能需要较长时间"
echo "   - 确保GitHub仓库有Git LFS配额空间"

