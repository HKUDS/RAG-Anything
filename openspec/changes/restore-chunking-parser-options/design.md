## Context

设置整合迁移（提交 `1857767`，2026-07-31）重写个人设置页后，分块策略下拉被硬编码为 `recursive`/`fixed` 两项（`fixed` 与后端规范 id `fixed_size` 不一致），解析器下拉渲染 `options.allowed.parsers`——迁移 `023` 将平台策略允许列表初始化为空数组（语义为“不限制”），前端 `[] || fallback` 在 JS 中保留 `[]`，因此渲染为空。同时 `KnowledgeDetailPage` 从 `getSettings()`（返回 `chunking_strategies` 目录）改为 `getPersonalSettings()`（不含目录）后，`strategies` state 永远为 `{}`，上传面板切块选择器停在“正在读取可用的切块方式…”。

后端事实来源：`raganything/chunking.STRATEGY_META` 定义 6 种策略；`raganything/parser.SUPPORTED_PARSERS` 定义 5 种解析器；平台策略 `allowed.parsers`/`allowed.chunking_strategies` 空数组 = 不限制（`_validate_section_against_platform_policy` 仅在非空时校验）。

## Goals / Non-Goals

**Goals:**
- `/api/users/me/settings/options` 下发无密钥的解析器与分块策略目录（含解析器安装可用性）。
- 个人设置两个下拉按目录渲染，空允许列表展示全部、非空允许列表过滤；解析器未安装置灰。
- 恢复上传面板切块方式选择器，不再卡在加载态。
- 目录缺失时前端回退到最小可用集合，控件保持可用。

**Non-Goals:**
- 不修改数据库迁移或存量 `platform_settings` 数据（空数组继续表示不限制）。
- 不改变 `/api/settings` 兼容接口行为。
- 不做 `semantic`/`agentic` 策略的 LLM/Embedding 可用性校验（后端 `build_chunking_func` 已有运行时回退）。

## Decisions

1. **目录由后端 options 接口下发，而非前端静态常量**。与现有模型 profile 目录模式一致，单一事实来源；前端仅做渲染与允许列表过滤。目录在 `settings_options()` 内惰性导入 `raganything.parser`/`raganything.chunking`，避免启动期循环导入与重依赖。
2. **解析器可用性通过 `check_installation()` 计算**（实例方法，按 `raganything.py` 既有调用模式）。每个解析器返回 `{id, name, available}`；opendataloader 经 `_get_odl_parser()` 惰性获取实例。异常按不可用处理，不阻断目录。
3. **允许列表过滤语义**：`allowed` 非空 → 目录仅保留列表内项；空 → 保留全部。在路由 `get_my_settings_options` 中与模型 profile 过滤并排放置，`project_settings_options` 仅负责按 section 投影（ingestion 才包含 `parsers`/`chunking_strategies`）。
4. **前端回退**：`options.parsers`/`options.chunking_strategies` 缺失（接口失败）时回退 `['docling']` 与 `['recursive','fixed_size']`；空数组目录（允许列表过滤后为空）仍渲染为空，与平台限制一致。
5. **分块策略显示名**：个人设置与上传面板统一复用 `getChunkingStrategyPresentation`，选项值用后端规范 id，消除 `fixed`/`fixed_size` 不一致。

## Risks / Trade-offs

- `check_installation()` 在每次 options 请求时执行 → 结果缓存于目录构建函数内不做全局缓存，但开销为轻量依赖探测；如出现性能问题可在后续引入短 TTL 缓存。
- 惰性导入失败（可选依赖缺失导致 import 错误）→ 用 try/except 将受影响解析器标记为不可用并继续返回目录。
- 前端回退集合与平台允许列表冲突（接口失败时可能显示平台不允许的项）→ 回退仅在目录缺失时生效，且保存仍受服务端 `_validate_section_against_platform_policy` 校验保护。
- 新增目录字段对既有测试断言（如“不含密钥/主机字段”）需同步扩展，避免误报失败。

## Migration Plan

- 无数据库迁移；后端接口为纯新增字段（向后兼容）。
- 部署顺序：后端接口先行（前端依赖新字段），前端随后；前端对缺失目录有回退，因此单侧发布不破坏功能。
- 回滚：撤销前端两处渲染改动即可恢复现状；后端新增字段可保留（不影响旧前端）。
6. **安装检查异常兜底与进程内 TTL 缓存**。目录构建把每次 `check_installation()` 包在 try/except 中，异常记为 `available=false`，保证 Windows/docling 运行时异常不导致 options 接口 500；安装探测结果按解析器 id 做进程内 TTL 缓存（默认 60s），避免每次请求都重跑子进程/重导入。
7. **前端目录归一化共享 helper**。新增 `frontend/src/utils/chunkingOptions.js`（或并入 `preferencesPresentation.js`）：把后端 `chunking_strategies` 数组归一化为按 id 键的对象（`ChunkingStrategySelector`/`getChunkingStrategyOptions` 需要对象形态），把 `fixed` 旧值映射为 `fixed_size`，并在目录缺失时回退到内置 6 策略对象；个人设置与上传面板共用，显示名统一以 `getChunkingStrategyPresentation` 为准。
8. **旧值兼容与失败回退**。个人设置渲染/保存时对 `chunking_strategy=fixed` 做归一化；解析器目录缺失（接口失败）时回退集并入当前 effective 值，避免受控下拉与实际值错位；KnowledgeDetailPage 在 options 失败时写入内置回退对象，保证上传面板切块选择器永不停留在加载态。
9. **section 投影与允许列表过滤**。`project_settings_options` 在无 ingestion 权限时 pop 掉 `parsers`/`chunking_strategies`（与 retrieval 的 `preset_values` 处理一致）；路由按允许列表过滤目录，空=全部；目录仅含 `SUPPORTED_PARSERS` 内置解析器（自定义 `register_parser` 解析器暂不纳入目录，作为已知取舍）。
