#!/bin/bash
# 解决Git LFS推送错误

set -e

echo "🔧 解决Git LFS推送错误..."
echo "================================================"
echo ""
echo "问题: GitHub不允许向public fork上传新的Git LFS对象"
echo ""
echo "解决方案选项:"
echo "1. 推送到自己的仓库（如果您有自己的仓库）"
echo "2. 请求原始仓库的写权限"
echo "3. 暂时跳过LFS文件，先推送其他文件"
echo ""
read -p "选择方案 [1/2/3]: " choice

case $choice in
  1)
    echo ""
    read -p "请输入您的GitHub用户名: " username
    read -p "请输入您的仓库名称 (或按回车使用 RAG-Anything): " reponame
    reponame=${reponame:-RAG-Anything}
    
    echo ""
    echo "添加新的remote..."
    git remote add mine "https://github.com/${username}/${reponame}.git" 2>/dev/null || \
      git remote set-url mine "https://github.com/${username}/${reponame}.git"
    
    echo ""
    echo "推送到您的仓库..."
    git push mine main
    
    echo ""
    echo "✅ 已推送到: https://github.com/${username}/${reponame}"
    ;;
    
  2)
    echo ""
    echo "⚠️  需要联系原始仓库所有者 (xiaoranwang1452) 授予您写权限"
    echo "   或者请求client在GitHub仓库中添加您为collaborator"
    echo ""
    echo "当前remote:"
    git remote -v
    echo ""
    echo "请先获得权限，然后再次运行: git push"
    ;;
    
  3)
    echo ""
    echo "⚠️  暂时跳过LFS文件，先推送其他文件..."
    echo ""
    echo "1. 取消暂存LFS文件..."
    git reset HEAD dataset/test-A/SPIQA_testA_Images/ 2>/dev/null || true
    git reset HEAD dataset/test-B/SPIQA_testB_Images/ 2>/dev/null || true
    git reset HEAD dataset/test-C/SPIQA_testC_Images/ 2>/dev/null || true
    
    echo ""
    echo "2. 先推送其他文件..."
    git push
    
    echo ""
    echo "✅ 其他文件已推送"
    echo "⚠️  图像文件需要等待权限或使用其他方案"
    ;;
    
  *)
    echo "❌ 无效选择"
    exit 1
    ;;
esac

