#!/bin/bash
# 恢复图像文件到git跟踪

echo "🔄 恢复数据集图像文件到Git跟踪..."
echo ""

read -p "选择方案: [1] 直接添加 (不推荐，424MB) [2] 使用Git LFS (推荐) [3] 取消: " choice

case $choice in
  1)
    echo "⚠️  警告: 这将添加424MB的文件到git，可能很慢..."
    read -p "确认继续? (y/n): " confirm
    if [[ $confirm == "y" ]]; then
      # 从.gitignore中移除图像目录（临时）
      sed -i.bak '/dataset\/\*\*\/SPIQA_\*_Images\//d' .gitignore
      sed -i.bak '/dataset\/\*\*\/\*\.zip/d' .gitignore
      
      # 添加文件
      git add dataset/test-A/SPIQA_testA_Images/
      git add dataset/test-B/SPIQA_testB_Images/
      git add dataset/test-C/SPIQA_testC_Images/
      
      echo "✅ 图像文件已添加到git暂存区"
      echo "⚠️  注意: 提交时可能需要较长时间"
    fi
    ;;
  2)
    echo "📦 使用Git LFS方案..."
    
    # 检查Git LFS是否安装
    if ! command -v git-lfs &> /dev/null; then
      echo "❌ Git LFS未安装"
      echo "   安装方法: brew install git-lfs"
      exit 1
    fi
    
    # 初始化Git LFS
    git lfs install
    
    # 跟踪PNG文件
    git lfs track "dataset/**/SPIQA_*_Images/**/*.png"
    
    # 添加.gitattributes
    git add .gitattributes
    
    # 从.gitignore中移除图像目录（因为LFS会处理）
    sed -i.bak '/dataset\/\*\*\/SPIQA_\*_Images\//d' .gitignore
    
    # 添加文件
    git add dataset/test-A/SPIQA_testA_Images/
    git add dataset/test-B/SPIQA_testB_Images/
    git add dataset/test-C/SPIQA_testC_Images/
    
    echo "✅ 图像文件已通过Git LFS添加到git暂存区"
    echo "📌 需要提交: git commit -m 'Add dataset images via Git LFS'"
    ;;
  3)
    echo "❌ 已取消"
    ;;
  *)
    echo "❌ 无效选择"
    ;;
esac

