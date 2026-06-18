## Why

RAG-Anything 后端经多轮 Vibe Coding 迭代，积累了大量代码质量问题：`server.py` 膨胀至 3752 行，核心模块 `parser.py`(3346 行)、`processor.py`(2786 行)、`query.py`(1818 行) 均严重超长；代码中混入大量未使用导入、废弃函数、冗余重复逻辑、失效注释和遗留测试代码。这些问题导致 AI 辅助调试时无法完整梳理执行流程，严重拖慢排错和迭代效率。本次重构在不改动任何业务逻辑、API 契约、数据库行为的前提下，彻底清理冗余、重整模块结构、统一编码规范，使代码库进入可维护、可 AI 友好调试的状态。

## What Changes

- **冗余清理**: 删除所有未使用导入、废弃函数/变量、冗余重复逻辑、失效注释、遗留测试/调试代码，提取重复通用逻辑封装为独立工具函数
- **模块拆分**: 将 `server.py` 从 3752 行拆分为 5 个 Router 模块（auth/knowledge/agent/query/admin），精简至 < 300 行；拆分 `parser.py`、`processor.py`、`query.py` 等超长文件
- **结构重组**: 遵循单一职责原则重构高耦合函数和类，降低代码嵌套层级，解耦业务逻辑
- **标准化**: 统一命名规范、异常处理方式、注释格式，补充函数签名文档（入参/出参/业务说明）
- **AI 调试友好**: 拆分大段复杂逻辑为清晰小函数，保证每个函数可被 AI 在单次上下文中完整理解

## Capabilities

### New Capabilities
- `code-structure-standardization`: 后端模块标准化结构 — 5 Router 分层、公共工具提取、单一职责函数
- `code-quality-baseline`: 代码质量基线 — 冗余消除、命名规范、异常处理统一、注释标准

### Modified Capabilities
<!-- 本次为纯代码质量重构，不修改任何功能规范要求 -->

## Impact

**受影响的代码范围**:
- `server.py` (3752 行 → <300 行) — 拆分为 5 个 Router + 启动骨架
- `raganything/parser.py` (3346 行) — 拆分为 parser 子包
- `raganything/processor.py` (2786 行) — 拆分为 processor 子包  
- `raganything/query.py` (1818 行) — 拆分为 query 子包
- `raganything/utils.py` (535 行) — 提取重复工具逻辑
- `auth.py` (403 行) — 合并到 routers/auth.py
- `raganything/manufacturing/` (30+ 文件) — 同步清理冗余
- `tests/` (29 个测试文件) — 清理废弃测试，补充重构后回归测试

**不变保障**:
- 所有 API 端点路径、请求/响应格式完全不变
- 所有数据库查询语句和 ORM 操作不变
- 所有业务逻辑分支和判断条件不变
- 所有环境变量和配置项名称不变
- `pytest` 全部测试通过
