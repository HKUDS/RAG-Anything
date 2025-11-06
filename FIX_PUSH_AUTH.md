# 修复推送认证问题

## 🔍 问题诊断

**错误**: HTTP 400 Bad Request
**原因**: 很可能是**认证问题**，不是权限问题

### 为什么是认证问题？

1. ✅ 文件大小正常（~1.6MB，只有5个文件）
2. ✅ 可以fetch（说明网络连接正常）
3. ❌ 推送失败（HTTP 400）

**GitHub在2021年8月后不再支持密码认证**，必须使用Personal Access Token。

---

## ✅ 解决方案

### 方案1: 更新Personal Access Token（推荐）

1. **生成新Token**:
   - 访问: https://github.com/settings/tokens
   - 点击 "Generate new token (classic)"
   - 选择权限: `repo` (完整仓库访问)
   - 复制生成的token

2. **清除旧凭证并重新认证**:
   ```bash
   # 清除旧的凭证
   git credential-osxkeychain erase
   host=github.com
   protocol=https
   # 按两次回车
   
   # 或者删除存储的凭证
   git credential reject https://github.com
   
   # 然后推送，会提示输入用户名和密码
   # 用户名: 您的GitHub用户名
   # 密码: 粘贴刚才生成的token（不是GitHub密码）
   git push -u origin spiqa-results-pr-clean
   ```

### 方案2: 临时使用Token在URL中（仅测试）

```bash
# 注意：这会暴露token在URL中，仅用于测试
git remote set-url origin https://<YOUR_TOKEN>@github.com/xiaoranwang1452/RAG-Anything.git

# 推送
git push -u origin spiqa-results-pr-clean

# 之后记得恢复
git remote set-url origin https://github.com/xiaoranwang1452/RAG-Anything.git
```

### 方案3: 切换到SSH（如果已配置SSH密钥）

```bash
# 检查SSH是否可用
ssh -T git@github.com

# 如果成功，切换远程URL
git remote set-url origin git@github.com:xiaoranwang1452/RAG-Anything.git

# 推送
git push -u origin spiqa-results-pr-clean
```

---

## 📝 快速修复步骤

```bash
# 1. 清除旧凭证
git credential-osxkeychain erase <<EOF
host=github.com
protocol=https
EOF

# 2. 推送（会提示输入用户名和token）
git push -u origin spiqa-results-pr-clean
# Username: 您的GitHub用户名
# Password: 粘贴Personal Access Token
```

---

## 🎯 总结

**不是权限问题，是认证问题**。需要：
1. 生成Personal Access Token
2. 清除旧的凭证
3. 使用token重新认证后推送

