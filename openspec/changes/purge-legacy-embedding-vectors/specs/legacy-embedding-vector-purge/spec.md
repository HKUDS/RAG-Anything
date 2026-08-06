## ADDED Requirements

### Requirement: 脚本发现并报告 legacy 向量数据
系统 SHALL 提供一次性运维脚本，大小写不敏感地发现 PostgreSQL 中无 identity 后缀的 legacy 向量表（含 `workspace` 列），动态枚举其中含数据的 workspace，并按表×workspace 输出行数基线；同时枚举全部带后缀向量表中每个 workspace 的行数（孤儿行清单）。

#### Scenario: dry-run 输出基线
- **WHEN** 以默认 `--dry-run` 模式运行脚本且存在 legacy 向量行
- **THEN** 脚本输出每张 legacy 表、每个 workspace 的行数，列出将受影响的所有 workspace，并输出各 suffixed 表中每 workspace 的行数

#### Scenario: dry-run 无 legacy 行
- **WHEN** 以 `--dry-run` 运行且任何 legacy 向量表都没有数据
- **THEN** 脚本报告 0 行基线、无受影响 workspace，并以退出码 0 结束

### Requirement: apply 模式在单事务内清理并注册身份
`--apply` 模式 SHALL 在单事务内完成：在事务内重新发现受影响 workspace（不依赖 dry-run 结果），为每个受影响 workspace 写入 `kb_text_embedding_identities` 注册（身份与权威来源一致并逐字段校验；已存在且一致的行标记为 EXISTED 不重复写入），删除这些 workspace 在全部 legacy 向量表中的行，并逐表校验删除后行数为 0；任一失败整体回滚。

#### Scenario: apply 成功
- **WHEN** 以 `--apply` 运行且 legacy 行存在、新后缀表对该 workspace 无数据、身份校验通过
- **THEN** 全部受影响 workspace 的 legacy 行被删除，身份注册行存在（新增为 INSERTED、已有且一致为 EXISTED），脚本报告删除行数与校验结果

#### Scenario: 目标 workspace 已有冲突注册
- **WHEN** 某受影响 workspace 在 `kb_text_embedding_identities` 已存在与权威身份不一致的注册
- **THEN** 脚本以非 0 退出码中止，不删除任何行，并报告冲突 workspace

#### Scenario: 事务回滚
- **WHEN** apply 事务中任一步骤（身份注册、DELETE、行数校验）失败
- **THEN** 整个事务回滚，数据库中不残留任何部分删除或部分注册

### Requirement: 新表已有数据时的安全护栏
当某 workspace 在任何带 identity 后缀的向量表中已存在数据时，脚本 SHALL 要求显式 `--force` 才允许清理该 workspace 的 legacy 行；未带 `--force` 时拒绝执行并说明原因。

#### Scenario: 未带 force 拒绝
- **WHEN** 某 workspace 在带后缀向量表已有数据且未传 `--force`
- **THEN** 脚本拒绝清理该 workspace 并列出需要 `--force` 的 workspace

#### Scenario: 带 force 继续
- **WHEN** 同一情况且显式传入 `--force`
- **THEN** 脚本继续执行，并在输出中记录该 workspace 使用了 force

### Requirement: 幂等与可重复执行
脚本 SHALL 幂等：重复运行 `--apply` 时未清理任何行也不报错，并报告删除 0 行。

#### Scenario: 重复 apply
- **WHEN** 脚本已成功执行过一次后再次以 `--apply` 运行
- **THEN** 脚本报告 0 行删除且退出码为 0

#### Scenario: 无 legacy 行时 apply
- **WHEN** 以 `--apply` 运行且没有任何 legacy 向量行
- **THEN** 脚本报告 0 行删除、不写入任何身份注册，并以退出码 0 结束

### Requirement: apply 前置备份校验
`--apply` SHALL 要求提供 `--backup-dir`，并在执行任何写操作前校验：每张实际存在的 legacy 向量表都有对应的非空 dump 文件且内容包含该表的 COPY 数据；任一校验不满足即以非 0 退出码拒绝执行。

#### Scenario: 未提供备份目录
- **WHEN** 以 `--apply` 运行且未提供 `--backup-dir`
- **THEN** 脚本拒绝执行并提示必须提供备份目录

#### Scenario: 备份文件缺失或为空
- **WHEN** 提供的备份目录中缺少某 legacy 表 dump 文件、文件为空或不含该表 COPY 数据
- **THEN** 脚本拒绝执行，以非 0 退出码结束且不执行任何写操作

### Requirement: 身份来源与运行时一致性校验
脚本 SHALL 以 `kb_text_embedding_identities` 中 `./rag_storage` 的注册为唯一权威身份来源：该行缺失、与运行时 env 重算的 canonical identity 不一致、或存在与权威身份不一致的其他注册时，dry-run 与 apply 均 fail-closed 中止。

#### Scenario: 权威来源缺失
- **WHEN** `kb_text_embedding_identities` 中不存在 `./rag_storage` 注册行
- **THEN** 脚本中止并报告权威身份来源缺失

#### Scenario: env 与权威来源不一致
- **WHEN** 运行时 env 重算的 canonical identity 与 `./rag_storage` 注册逐字段不一致
- **THEN** 脚本中止，提示以与生产 API/Worker 相同的 embedding env 运行