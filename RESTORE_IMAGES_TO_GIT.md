# 恢复数据集图像文件到Git

## 当前状态

✅ **本地文件完整存在**：
- `dataset/test-A/SPIQA_testA_Images/` (119MB, 2,252个PNG文件)
- `dataset/test-B/SPIQA_testB_Images/` (190MB, 794个PNG文件)  
- `dataset/test-C/SPIQA_testC_Images/` (115MB, 2,243个PNG文件)

❌ **Git中未跟踪**：之前从git跟踪中移除了（因为文件太大）

---

## 选项1: 直接添加回Git（不推荐）

**问题**：
- 总共约424MB，会让仓库变得很大
- GitHub可能会拒绝或警告大文件
- 克隆和推送会很慢

**如果确实需要**：
```bash
# 从.gitignore中移除图像目录的排除规则
# 然后添加文件
git add dataset/test-A/SPIQA_testA_Images/
git add dataset/test-B/SPIQA_testB_Images/
git add dataset/test-C/SPIQA_testC_Images/
```

---

## 选项2: 使用Git LFS（推荐）

Git LFS专门用于大文件，可以跟踪但不增加主仓库大小。

**步骤**：
```bash
# 1. 安装Git LFS
brew install git-lfs  # macOS
# 或访问: https://git-lfs.github.com/

# 2. 初始化Git LFS
git lfs install

# 3. 跟踪PNG文件
git lfs track "dataset/**/SPIQA_*_Images/**/*.png"

# 4. 添加.gitattributes（自动创建）
git add .gitattributes

# 5. 添加图像文件
git add dataset/test-A/SPIQA_testA_Images/
git add dataset/test-B/SPIQA_testB_Images/
git add dataset/test-C/SPIQA_testC_Images/

# 6. 提交
git commit -m "Add SPIQA dataset images via Git LFS"
```

**注意**：
- GitHub免费账户有1GB Git LFS配额
- 您的424MB图像在配额内
- 协作人员需要安装Git LFS才能克隆

---

## 选项3: 保持当前状态（推荐用于client交付）

**当前方案**：
- ✅ JSON元数据文件在git中（已足够）
- ✅ 图像文件在本地（可以通过下载脚本获取）
- ✅ 文档中有下载指南（DATASET_IMAGES_SETUP.md）

**优点**：
- 仓库轻量，易于克隆
- 符合标准做法（大数据集通常不直接提交）
- 可以通过官方源重新下载

---

## 我的建议

**如果这是给client的项目**：
- 保持当前状态（图像不在git中）
- 提供下载脚本和说明文档
- 这是业界标准做法

**如果client需要所有文件都在git中**：
- 使用Git LFS方案（选项2）
- 需要安装Git LFS并配置

**如果只是个人使用**：
- 可以选择直接添加（选项1），但要注意仓库大小

---

## 快速恢复命令（如果决定添加）

如果您确实需要图像文件在git中，我可以帮您：
1. 恢复git跟踪
2. 配置Git LFS（如果选择）
3. 或者直接添加（如果选择）

请告诉我您的选择！

