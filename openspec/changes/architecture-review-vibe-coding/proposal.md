## Why

RAG-Anything 项目经过多轮迭代后积累了显著的架构债务：24+ 个文件超过 500 行（最高 1672 行）、模块边界模糊（包内反向依赖根级模块）、共享状态分散在多个 God Module 中、Mixin 隐式契约缺少接口约束。这些问题直接导致 AI 编程工具（Vibe Coding）难以追溯调用链、定位报错根源、理解业务逻辑——每次排错和迭代的效率显著下降。当前进行一次系统性架构治理，以最小风险消除这些结构性障碍，是提升后续开发效率的最优时机。

## What Changes

- **拆分巨型文件**：将 `modalprocessors.py`(1672行)、`query/pipeline.py`(1445行)、`processor/doc_processor.py`(1201行)、`agentic_rag.py`(1145行) 等 24+ 个超长文件按职责拆分为独立模块，每个模块 ≤500 行，函数 ≤100 行
- **修复分层违规**：将根级 `auth.py`、`agent_manager.py` 归入 `raganything/` 包内，消除包内模块反向依赖包外模块的问题；统一 `get_current_user` 和 `Limiter` 的重复定义
- **拆分 God Module**：将 `routers/shared.py`(708行) 拆分为 `state.py`(共享状态)、`kb_service.py`(知识库管理)、`ws_service.py`(WebSocket) 三个独立服务模块
- **规范 Mixin 契约**：为 `QueryMixin`、`ProcessorMixin`、`BatchMixin` 及其子 Mixin 引入 Protocol/ABC 显式定义所需属性接口
- **消除循环依赖与重复**：合并 `dependencies.py` 和 `shared.py` 中的重复代码；清理 `processor/__init__.py` 中仅为向后兼容的跨包导入
- **清理冗余文件**：移除 `parser.py.bak`、`processor.py.bak`、`query.py.bak` 等重构残留备份文件
- **统一注释与命名规范**：标准化 docstring 格式、中英文注释分离、统一类型标注

## Capabilities

### New Capabilities
- `module-boundary-enforcement`: 模块边界与依赖方向约束——定义清晰的分层规则（router → service → core），禁止反向依赖，包内模块统一对外接口
- `shared-state-consolidation`: 共享状态集中管理——消除 server.py、shared.py、dependencies.py 三处分散的状态定义，统一为单一状态管理器
- `code-decomposition-standards`: 代码分解标准——文件上限 500 行、函数上限 100 行、类上限 300 行，超限强制拆分
- `vibe-coding-compatibility`: Vibe Coding 兼容性优化——标准化模块注释头、显式导出清单、调用链标注、类型完备化

### Modified Capabilities
<!-- 纯架构重构，不改动业务行为，无需修改现有功能 spec -->

## Impact

- **受影响代码范围**：`raganything/` 全量（45 个文件）、根级 `auth.py`/`agent_manager.py`/`server.py`、`tests/`（29 个文件导入路径更新）
- **API 接口**：零变更——所有 REST 端点路径、请求/响应结构、状态码保持不变
- **数据库交互**：零变更——LightRAG 存储层、SQLite 用户库、知识图谱数据模型读写逻辑不变
- **依赖项**：无新增外部依赖；内部导入路径变更需全局更新
- **风险控制**：渐进式拆分（每次一个模块）、全量测试回归、导入路径向后兼容别名
