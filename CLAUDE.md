# RAG-Anything Project Instructions

## 项目核心总结（强制）

`PROJECT_SUMMARY.md` 是所有项目任务的首要阅读入口。

- 启动任何任务前必须完整阅读该文件，再定向核验任务相关源码、配置、迁移和规格。
- 总结不替代代码、数据库迁移、运行配置或 OpenSpec 主规格；发现冲突时以实际实现和验证结果为准。
- 任务完成前由唯一协调者更新当前事实并追加近期任务记录；并行子任务只在 handoff 提交“总结增量”。
- 无持久行为变化也要记录结论；禁止写入密钥、用户数据、日志或生成产物。

## 铁律集成

本项目遵循全局铁律（`~/.claude/CLAUDE.md`）：每次收到用户请求必须执行两级智能体调度。

### OpenSpec + 调度联动规则

使用 OpenSpec 命令时必须遵循以下时序：

```
/opsx:propose → 先调度（至少 2 专家评审提案质量）
/opsx:apply   → 先调度（至少 3 专家：执行+审查+测试）
/opsx:archive → 调度确认后归档
```

**不可跳过**：即使任务看起来简单（如单行修复、配置修改），也必须走完两级调度。OpenSpec 管产出结构化，调度管执行质量，两者叠加而非替代。

OpenSpec 的 `propose` 必须将总结同步列入最终任务，`apply` 在验证后更新，`archive` 前确认总结已经同步。

## 当前认证边界

- 权限使用 `resource:action` 格式，五级角色为 `super_admin`、`dept_admin`、`teacher`、`assistant`、`student`。
- 用户、角色、审计和 Token 撤销使用 PostgreSQL；当前认证服务无 SQLite 回退。
- `is_admin` 仅为兼容字段，由 `super_admin` 角色派生。完整现状以 `PROJECT_SUMMARY.md` 和 `raganything/permissions.py` 为准。
