## ADDED Requirements

### Requirement: BM25 索引构建

系统 SHALL 在知识库文档完成分块入库后，为所有文本 chunk 构建 Okapi BM25 倒排索引，使用 jieba 作为默认中文分词器。

#### Scenario: 初始索引构建
- **WHEN** 知识库首次启用 RRF 模式或已有文档触发索引构建
- **THEN** 系统遍历所有 chunk 的文本内容
- **THEN** 使用 jieba 对每个 chunk 进行分词
- **THEN** 构建 `BM25Okapi` 索引对象并缓存在内存中

#### Scenario: 自定义分词器
- **WHEN** 环境变量 `BM25_TOKENIZER=nltk`
- **THEN** 系统使用 NLTK 分词器替代 jieba
- **THEN** 索引构建使用自定义分词器进行 tokenization

### Requirement: 增量索引更新

系统 SHALL 在新文档入库后异步重建 BM25 索引，重建期间使用旧索引继续服务查询，重建完成后原子替换为新索引。

#### Scenario: 文档入库触发增量更新
- **WHEN** 新文档被上传并通过解析分块后插入知识库
- **THEN** 系统异步触发 BM25 索引重建
- **THEN** 重建期间的查询使用当前索引，不阻塞
- **THEN** 重建完成后通过原子引用替换更新索引

#### Scenario: 批量文档入库
- **WHEN** 批量上传 50 个文档
- **THEN** 系统在所有文档入库完成后触发一次索引重建（而非每个文档触发一次）

### Requirement: BM25 关键词检索

系统 SHALL 对输入查询进行分词后，调用 `BM25Okapi.get_scores()` 计算每个 chunk 的 BM25 相关性分数，返回 top_k 个候选结果。

#### Scenario: 基本关键词检索
- **WHEN** 查询 "年假天数 工龄计算公式" 且 `BM25_TOP_K=50`
- **THEN** 系统对查询分词为 ["年假", "天数", "工龄", "计算", "公式"]
- **THEN** 返回 BM25 分数最高的 50 个 chunk

#### Scenario: 空关键词处理
- **WHEN** 查询经分词后为空列表
- **THEN** 返回空结果列表，不抛出异常

### Requirement: BM25 参数配置

系统 SHALL 通过环境变量 `BM25_K1`（默认 1.5）和 `BM25_B`（默认 0.75）控制 Okapi BM25 的调参，通过 `BM25_TOP_K`（默认 50）控制返回候选数。

#### Scenario: 使用默认参数
- **WHEN** 未设置 BM25 相关环境变量
- **THEN** 系统使用 k1=1.5, b=0.75, top_k=50 进行检索

#### Scenario: 自定义参数
- **WHEN** 环境变量 `BM25_K1=2.0`, `BM25_B=0.5`, `BM25_TOP_K=80`
- **THEN** 系统使用自定义参数进行检索
