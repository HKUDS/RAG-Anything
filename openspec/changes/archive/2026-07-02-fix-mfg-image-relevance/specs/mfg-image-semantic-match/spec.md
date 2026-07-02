# Manufacturing Image Semantic Match

## Purpose

确保制造智能体 QA 引擎返回的"相关图片"与用户查询具有语义相关性，避免在无明确图号引用时返回不相关图片。

## ADDED Requirements

### Requirement: 三级图片匹配策略
QA 引擎 SHALL 使用三级策略匹配相关图片，按优先级依次执行：

1. **图号精确匹配**：从检索文本和查询中提取 "图N"/"Figure N" 引用，将图号映射为 parse cache 中按 page_idx 排序的第 N-1 张图片
2. **Caption 关键字符匹配**：当无图号匹配时，对图片 caption 文本与用户查询进行 jieba 分词后取关键字交集，返回交集非空的图片（按交集大小降序）
3. **路径关键字符匹配**：当 caption 不可用时，对图片文件路径/文件名与查询进行 jieba 分词后取关键字交集

#### Scenario: 图号精确匹配成功
- **WHEN** 检索文本中包含"如图5所示"或"Figure 5"等图号引用
- **THEN** QA 引擎 SHALL 返回 parse cache 中按 page_idx 排序的第 4 张图片（索引 4）

#### Scenario: 无图号引用时 caption 匹配
- **WHEN** 检索文本中不存在图号引用，且所有图片 caption 列表中存在与查询关键字交集的图片
- **THEN** QA 引擎 SHALL 返回 caption 有交集的图片，按交集关键字数量降序排列，最多返回 2 张

#### Scenario: Caption 为空时路径匹配
- **WHEN** 检索文本中不存在图号引用，且图片无 caption 或 caption 为空
- **THEN** QA 引擎 SHALL 使用图片文件路径/文件名与查询进行 jieba 分词匹配，返回有交集的图片

#### Scenario: 三级匹配全部失败
- **WHEN** 检索文本中不存在图号引用，且 caption 和路径匹配均无交集
- **THEN** QA 引擎 SHALL 返回空图片列表（不展示任何图片），`related_images` 字段为空数组 `[]`

### Requirement: 图片编码安全校验
QA 引擎 SHALL 对匹配到的图片进行安全校验后再编码为 base64 data URL。

#### Scenario: 图片文件缺失
- **WHEN** 匹配到的图片路径在磁盘上不存在
- **THEN** 系统 SHALL 跳过该图片并记录 WARNING 级别日志

#### Scenario: 图片过大
- **WHEN** 匹配到的图片 base64 编码后超过 2MB
- **THEN** 系统 SHALL 跳过该图片并记录 WARNING 级别日志
