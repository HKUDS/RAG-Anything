## Context

当前 `raganything/processor/` 下的三个处理器（`doc_processor.py`、`multimodal_processor.py`、`chunk_processor.py`）在记录 `updated_at` 时间戳时，统一使用 `time.strftime("%Y-%m-%dT%H:%M:%S+00:00")` 硬编码 UTC 时区后缀。`doc_processor.py` 的 `_current_doc_status_timestamp()` 方法更是显式调用 `time.gmtime()` 返回 UTC 时间。

这导致前端显示的文档处理时间比北京时间少 8 小时。项目面向中文用户，应统一使用北京时间。

`raganything/utils/` 已有 `_general.py` 存放通用工具函数，是放置新时间工具函数的自然位置。

## Goals / Non-Goals

**Goals:**
- 所有 `updated_at` / `created_at` 时间戳统一使用北京时间（UTC+8）
- 提供单一工具函数，避免多处重复时间格式化逻辑
- 保持与现有 `doc_status` JSON 存储格式兼容（仅改变时区后缀从 `+00:00` → `+08:00`）

**Non-Goals:**
- 不修改 `datetime.now()` 调用（这些使用系统本地时间，Windows 下已是北京时间）
- 不修改 `datetime.now(timezone.utc)` 调用（JWT token 过期、token 黑名单等安全相关时间戳保留 UTC 是正确的）
- 不涉及前端时间显示逻辑变更（前端直接展示后端返回的时间戳字符串）

## Decisions

### Decision 1: 工具函数位置 — `raganything/utils/_general.py`

在 `_general.py` 中新增 `beijing_now()` 函数，并通过 `__init__.py` 导出。

**理由**: `_general.py` 已存放 SSE 事件、响应格式化等通用工具，与时间戳生成同类。`utils/` 是项目中已有的共享工具层，三个 processor 均可直接导入。

**备选方案**:
- 新建独立 `_time.py` → 过度拆分，仅一个函数不值得新文件
- 内联到每个 processor → 代码重复，不利于未来统一调整
- 使用 `pytz` / `zoneinfo` → 增加外部依赖，对于固定 UTC+8 偏移不必要

### Decision 2: 实现方式 — `datetime` + 固定 `timezone(timedelta(hours=8))`

```python
from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
```

**理由**:
- `datetime.now(tz)` 是标准库推荐做法，比手动计算 `time.time() + 28800` 更清晰
- 固定偏移足够（中国不使用夏令时）
- 无外部依赖

**备选方案**:
- `zoneinfo.ZoneInfo("Asia/Shanghai")` (Python 3.9+) → 语义更好但项目需兼容 Python 3.8，且固定 UTC+8 等价
- `time.strftime` + `time.localtime()` → 依赖系统时区设置，服务器可能不是北京时间

### Decision 3: 替换范围 — 仅替换显式 UTC 硬编码

只替换包含 `+00:00` 后缀或 `time.gmtime()` 的 5 处调用。其他 `datetime.now()` / `datetime.now().isoformat()` 调用保持不变。

**理由**:
- `datetime.now()` 返回本地时间，在中国 Windows/服务器上已是北京时间
- 安全相关（JWT exp、token blacklist）使用 UTC 是行业最佳实践，不应修改
- 遵循 Minimal Change 原则：仅改有问题的地方

## Risks / Trade-offs

- **风险**: 服务器系统时区非北京时间 → 新旧时间戳不一致
  - **缓解**: 使用显式 UTC+8 偏移而非依赖系统时区
- **风险**: 已有 UTC 时间戳的历史数据与北京时间新数据混存
  - **缓解**: 格式相同仅后缀不同，前端可正常解析；历史数据自然过期
