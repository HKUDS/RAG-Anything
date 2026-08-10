## 1. 后端：options 接口下发解析器与分块策略目录

- [x] 1.1 在 `raganything/services/user_settings.py` 增加 `_parser_catalog()`：惰性导入 `raganything.parser`，遍历 `SUPPORTED_PARSERS`，对每个解析器调用 `check_installation()` 并包 try/except 记为 `available=false`，返回 `[{id,name,available}, ...]`；增加进程内 TTL 缓存（默认 60s）。
- [x] 1.2 在 `settings_options()` 增加 `parsers` 与 `chunking_strategies` 字段：后者惰性导入 `raganything.chunking`，由 `STRATEGY_META` 映射为 `[{id,name,description,cost,cost_level}, ...]`，保持无密钥。
- [x] 1.3 在 `project_settings_options()` 按允许 section 投影：仅 ingestion 时保留 `parsers`/`chunking_strategies`，否则从结果中 pop（与 retrieval 的 `preset_values` 处理一致）。
- [x] 1.4 在 `raganything/routers/user_settings.py` 的 `get_my_settings_options` 按平台 `allowed.parsers`/`allowed.chunking_strategies` 过滤目录：非空仅保留列表内项，空保留全部（与模型 profile 过滤模式一致）。

## 2. 前端：个人设置下拉与上传面板选择器

- [x] 2.1 新增共享 helper（`frontend/src/utils/chunkingOptions.js`）：把 `chunking_strategies` 数组归一化为按 id 键的对象（供 `getChunkingStrategyOptions` 使用），`fixed` 旧值映射为 `fixed_size`，目录缺失时回退到内置 6 策略对象。
- [x] 2.2 `PreferencesPage.jsx` 解析器下拉改渲染 `options.parsers`（`available=false` 置灰）；目录缺失（接口失败）时回退 `['docling']` 并并入当前 effective 值。
- [x] 2.3 `PreferencesPage.jsx` 分块策略下拉改渲染 `options.chunking_strategies` 6 项，值用后端规范 id，显示名复用 `getChunkingStrategyPresentation`；渲染与保存时归一化 `fixed→fixed_size`；目录缺失时回退 `['recursive','fixed_size']`。
- [x] 2.4 `KnowledgeDetailPage.jsx` 加载设置 effect 中并行调用 `getPersonalSettingsOptions()`，用共享 helper 归一化后写入 `strategies`；接口失败时写入内置回退对象，保证选择器不停留在加载态。

## 3. 测试与验证

- [x] 3.1 扩展 `tests/test_user_settings_resolution.py`：断言 `settings_options()` 返回 6 个策略 id 与 5 个解析器、不含密钥/主机字段；`project_settings_options` 在无 ingestion 时剔除目录；用 monkeypatch 避免真实安装检查（挂起/异常）。
- [x] 3.2 扩展 `tests/test_personal_settings_capabilities.py`：断言投影后目录键存在/被剔除，允许列表过滤（空=全部、非空=仅列表）。
- [x] 3.3 在 `frontend/src/utils/preferencesPresentation.test.js`（或新测试文件）覆盖共享 helper：数组→对象归一化、`fixed→fixed_size`、目录缺失回退。
- [x] 3.4 运行后端相关套件（test_user_settings_resolution、test_personal_settings_capabilities 等）、前端 `node --test frontend/src/utils/*.test.js`、`vite build`，修复失败项。
- [x] 3.5 更新 `PROJECT_SUMMARY.md`（当前事实 + 近期任务记录），并复核 OpenSpec strict 校验与 `git diff --check`。
